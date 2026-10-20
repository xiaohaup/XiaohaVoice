"""Windows host. Imported only after the per-toolkit paths have been set."""
from __future__ import annotations
import hashlib,json,os,socket,subprocess,sys,time,threading
from pathlib import Path
from uuid import UUID
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject,Signal,Qt,QTimer,QUrl,QLockFile
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication,QSystemTrayIcon,QMenu,QFileDialog,QMessageBox
from PySide6.QtNetwork import QLocalServer,QLocalSocket
from . import __version__
from .core import Session,History,Recovery,Deliveries,Shortcut,load_json,atomic_json
from .services import Capture,Speech,environment,runtime_command,NO_WINDOW
from .qt_ui import Workbench,Capsule,make_icon
from .win32 import Windows,Clipboard

class Controller(QObject):
    hook_event = Signal(str,object)
    work_finished = Signal(str,object)
    def __init__(self, application, root, startup=False):
        super().__init__(); self.app = application; self.root = Path(root); self.data = self.root/'Data'
        self.data.mkdir(parents=True,exist_ok=True)
        self.settings_path = self.data/'windows-settings.json'
        self.settings = {**{'silent_startup':True,'show_dock':True,'shortcut':{'keyCode':165,'modifiers':0,'label':'右 Alt'}},**load_json(self.settings_path,{})}
        self.windows = Windows(); self.sessions = {}; self.active = None; self.displayed = None; self.closed = False
        self.deliveries = Deliveries(); self.bridges = {}; self.retired_bridges = set(); self.exit_timers = {}; self.worker = ThreadPoolExecutor(max_workers=1)
        self.history = History(self.data); self.recovery = Recovery(self.data)
        completed = [r['id'] for r in load_json(self.history.path,[])]
        restored,self.recovery_issues = self.recovery.load(completed)
        self.sessions.update((s.id,s) for s in restored)
        self.toolkit_busy = False; self.toolkit_status = ''; self.paste_test_status = ''; self.paste_test_running = False
        self.restore_choice = None; self.server = None; self.server_started = 0; self.origin = self._origin()
        self.window = Workbench(root,self.origin,self.dispatch); self.window.setWindowIcon(make_icon(root))
        self.window.setWindowFlag(Qt.WindowType.Tool,not self.settings['show_dock'])
        # Qt can recreate the HWND on first show or after changing window flags.
        self.clipboard = Clipboard(self.windows,lambda:int(self.window.winId()))
        self.capsule = Capsule(root); self.capsule.cancel.connect(self.cancel); self.capsule.copied.connect(self.copy_displayed); self.capsule.retried.connect(self.retry_displayed)
        self.capture = Capture(); self.capture.audio.connect(self.audio); self.capture.failed.connect(self.capture_error)
        from .win32 import Hooks
        self.hooks = Hooks(self.windows,lambda kind,value:self.hook_event.emit(kind,value))
        self.hook_event.connect(self.on_hook)
        self.hooks.gesture.shortcut = self.decode_shortcut(self.settings['shortcut']); self.hooks.start()
        self.work_finished.connect(self._work_finished)
        self.tray = QSystemTrayIcon(self.window.windowIcon(),self); self.tray.setToolTip('小哈语音')
        menu = QMenu(); menu.addAction('打开小哈语音',self.window.activate); menu.addAction('开始／结束语音',self.toggle)
        menu.addAction('本机历史',lambda:self.open_section('history')); menu.addSeparator(); menu.addAction('退出小哈语音',self.quit)
        self.tray.setContextMenu(menu); self.tray.activated.connect(lambda reason:self.window.activate() if reason in (QSystemTrayIcon.ActivationReason.Trigger,QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self.tray.show()
        self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(100)
        self.health_timer = QTimer(self); self.health_timer.timeout.connect(self.health); self.server_started = time.monotonic()
        self.start_server(); self.health_timer.start(250)
        self.single = QLocalServer(self); self.single.newConnection.connect(self.receive_activation)
        self.single.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.single.listen('XiaohaVoice-Desktop')
        if not startup or not self.settings['silent_startup']: self.window.activate()
    def _origin(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0)); self.port = probe.getsockname()[1]
        return 'http://127.0.0.1:'+str(self.port)
    def receive_activation(self):
        connection = self.single.nextPendingConnection()
        if connection: connection.disconnectFromServer(); connection.deleteLater()
        self.window.activate()
    def start_server(self):
        args = runtime_command(self.root,'control','--no-browser','--port',str(self.port),'--data',str(self.data/'desktop'),
                               '--history',str(self.history.path),'--wordbook',str(self.data/'sync-wordbook.json'))
        self.server = subprocess.Popen(args,env=environment(self.root),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=NO_WINDOW)
    def health(self):
        import urllib.request
        try:
            request = urllib.request.Request(self.origin+'/api/health')
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=.12) as response: value=json.load(response)
            expected = hashlib.sha256(str((self.data/'desktop').resolve()).encode()).hexdigest()
            if value.get('service') != 'xiaoha-voice-companion' or value.get('instance') != expected: raise ValueError('本机服务身份不匹配')
            self.health_timer.stop(); self.window.open(self.origin)
        except Exception:
            if self.server.poll() is not None or time.monotonic()-self.server_started>25:
                self.health_timer.stop(); self.toolkit_status='本机工作台未启动；请检查运行组件，原资料保留。'
                self.window.browser.setHtml('<body style="font:16px sans-serif;padding:50px">'+self.toolkit_status+'</body>')
    def save_settings(self): atomic_json(self.settings_path,self.settings)
    def diagnostic(self,event,**fields):
        from desktop.runtime_log import append
        try: append(self.data,event,**fields)
        except (ValueError,OSError): pass
    def decode_shortcut(self,value):
        if not isinstance(value,dict): raise ValueError('快捷键格式无效')
        result = Shortcut(key=value.get('keyCode',0),modifiers=value.get('modifiers',0),label=value.get('label',''),mouse=value.get('mouseButton',0))
        if not all(type(x) is int for x in (result.key,result.modifiers,result.mouse)) or not result.validate() or not isinstance(result.label,str) or len(result.label)>100:
            raise ValueError('请选择单侧修饰键、功能键、组合键或鼠标侧键')
        return result
    def on_hook(self,kind,value):
        if kind == 'toggle': self.toggle(value)
        elif kind == 'cancel': self.cancel()
        elif kind == 'mouseShortcut': self.window.mouse_shortcut(value)
    def toggle(self,target=None):
        if self.toolkit_busy or self.hooks.suspended: return
        if self.active: self.stop(target or self.windows.capture()); return
        asr = load_json(self.data/'asr-settings.json',{})
        if asr.get('provider','ime') == 'ime' and not (self.data/'recognition/device.json').is_file():
            self.open_section('asr'); self.tray.showMessage('小哈语音','首次使用请在识别服务里初始化这台设备。'); return
        session = Session(); self.sessions[session.id] = session; self.active = self.displayed = session
        self.capsule.preview_until = 0; self.hooks.recording = True
        try: self.capture.start(); self.connect(session); self.diagnostic('capture',phase='start')
        except Exception:
            session.failure='无法启动麦克风或识别组件，请检查系统设置。'; self.capture.stop(); session.recording=False; self.active=None; self.hooks.recording=False
            if session.pcm: self.resolve_failure(session,'failed')
            else:
                message=session.failure; session.cancel(); session.delivery=message
                self.hide_if_current(session,2500)
        self.capsule.present(); self.tick()
    def stop(self,target):
        session = self.active
        if not session: return
        self.capture.stop(); session.recording=False; self.active=None; self.hooks.recording=False
        self.diagnostic('capture',phase='stop',seconds=session.seconds)
        session.target=target; session.application=(target.application or self.windows.application(target.pid)) if target else None
        if target and target.pid == os.getpid():
            session.target_ready=False
            self.window.capture_field(lambda token:self._captured_field(session,token))
        self.deliveries.append(session.id)
        if not session.pcm and not session.has_text: self.quiet(session)
        elif session.failure: self.resolve_failure(session,'failed')
        else: self.flush(session)
        self.tick()
    def _captured_field(self,session,token):
        session.local_token = token if isinstance(token,str) else None; session.target_ready=True; self.drain()
    def audio(self,data):
        if self.active:
            self.active.append(data); self.flush(self.active)
    def capture_error(self,message):
        if self.active: self.active.failure=message
    def connect(self,session):
        old=self.bridges.pop(session.id,None)
        if old: self.retired_bridges.add(old); old.cancel()
        bridge = Speech(self.root,session); bridge.event.connect(self.bridge_event); bridge.exited.connect(self.bridge_exited)
        self.bridges[session.id]=bridge; bridge.start()
    def flush(self,session):
        bridge=self.bridges.get(session.id)
        if not bridge or not session.ready or session.complete or session.failure: return
        for _ in range(16):
            if session.sent>=len(session.pcm): break
            chunk=bytes(session.pcm[session.sent:session.sent+3200])
            if not bridge.audio(chunk,session.retrying): break
            session.sent+=len(chunk)
        if not session.recording and session.sent==len(session.pcm) and not session.stop_sent:
            session.stop_sent=bridge.finish()
    def bridge_event(self,sid,generation,value):
        session=self.sessions.get(sid)
        if not session or session.generation!=generation or session.complete: return
        event=value.get('event')
        if isinstance(value.get('text'),str): session.text=value['text']
        if isinstance(value.get('original_text'),str): session.original_text=value['original_text']
        if event == 'ready': session.ready=True; self.flush(session)
        elif event == 'done':
            if session.recording:
                session.failure='识别提前结束，录音仍在继续，请按启停键结束后重试。'; session.ready=False
            elif session.has_text:
                try:
                    text=session.text; self.history.add(session,text,session.original_text); session.finish(text)
                    self.window.announce_history(); self.drain()
                    if session.id not in self.deliveries.ids: self.hide_if_current(session,1000)
                    # The old recoverable source remains until saved text is durable; then it goes to Recycle Bin.
                    try: self.recovery.discard(session.id,self.windows.trash)
                    except OSError: pass
                except (ValueError,OSError): session.failure='文字未能保存，音频仍保留，请检查磁盘空间。'; self.preserve(session)
            else: self.resolve_failure(session,'empty')
        elif event == 'empty': self.resolve_failure(session,'empty')
        elif event == 'error':
            session.failure=str(value.get('message') or '识别连接未完成，请检查通道与网络')[:500]; session.ready=False
            if not session.recording: self.resolve_failure(session,'failed')
        self.tick()
    def bridge_exited(self,sid,generation,code):
        bridge=self.bridges.get(sid)
        # A late exit from an earlier retry must never remove the current bridge.
        if bridge and bridge.generation==generation:
            self.bridges.pop(sid); self.retired_bridges.add(bridge)
        session=self.sessions.get(sid)
        if not session or session.generation!=generation or session.complete or session.failure: return
        session.failure='识别进程已结束，录音内容已保留。'; session.ready=False
        if not session.recording: self.resolve_failure(session,'failed')
    def quiet(self,session):
        bridge=self.bridges.pop(session.id,None)
        if bridge: self.retired_bridges.add(bridge); bridge.cancel()
        session.cancel(); session.delivery='未听到内容，已结束'; self.drain(); self.hide_if_current(session,0)
    def resolve_failure(self,session,ending):
        decision=session.disposition(ending)
        if decision == 'quiet': self.quiet(session)
        elif decision == 'retain':
            session.failure=session.failure or '没有生成最终文字，可在本机历史中重试。'; session.retrying=False
            self.preserve(session); self.drain(); self.hide_if_current(session,1500)
    def preserve(self,session):
        try: self.recovery.save(session)
        except OSError: session.failure='录音暂存失败，请保留程序并检查磁盘空间。'
    def cancel(self):
        if self.active:
            session=self.active; self.capture.stop(); self.active=None; self.hooks.recording=False
            bridge=self.bridges.pop(session.id,None)
            if bridge: self.retired_bridges.add(bridge); bridge.cancel()
            session.cancel(); self.drain()
        self.capsule.preview_until=0; self.capsule.hide()
    def hide_if_current(self,session,delay):
        QTimer.singleShot(delay,lambda:self.capsule.hide() if not self.active and self.displayed is session else None)
    def tick(self):
        self.reap_bridges()
        for session in list(self.sessions.values()): self.flush(session)
        self.capsule.busy=bool(self.active or any(not s.complete and not s.failure for s in self.sessions.values()))
        self.capsule.update_session(self.displayed,self.hooks.gesture.shortcut.label)
        self.drain()
        self.prune_sessions()
    def reap_bridges(self):
        for bridge in tuple(self.retired_bridges):
            # The exit signal can arrive just before the reader thread returns.
            # Delete the Qt object only after both worker threads have stopped.
            if bridge.finished:
                self.retired_bridges.remove(bridge); bridge.deleteLater()
    def prune_sessions(self):
        live={*self.bridges,*(bridge.sid for bridge in self.retired_bridges)}
        settled=[sid for sid,session in self.sessions.items()
                 if session.complete and session.delivery and not session.failure and not session.pcm
                 and session is not self.active and session is not self.displayed
                 and sid not in self.deliveries.ids and sid not in live]
        # Durable text lives in History. Keep recent settled results in memory;
        # pending delivery, current display, failures and recovery stay intact.
        for sid in settled[:-32]: self.sessions.pop(sid)
    def drain(self):
        sid=self.deliveries.begin(self.sessions)
        if sid: self.deliver(self.sessions[sid],time.monotonic())
    def deliver(self,session,started):
        from desktop.runtime_settings import RuntimeSettings
        settings=RuntimeSettings(self.data).load()
        if settings['auto_paste'] and self.windows.modifiers_down() and time.monotonic()-started<.8:
            QTimer.singleShot(15,lambda:self.deliver(session,started)); return
        def finish(message):
            session.delivery=message; self.paste_test_status=message; self.deliveries.finish(session.id)
            self.diagnostic('delivery',phase='pasted' if message.startswith('已粘贴') else 'retained',characters=len(session.text))
            if self.displayed is session: self.capsule.line.setText(message)
            self.hide_if_current(session,550 if message.startswith('已粘贴') else 2500); self.drain()
        if session.local_token and settings['auto_paste']:
            def inserted(ok):
                copied=False
                if settings['keep_transcription'] or not ok:
                    try: self.clipboard.stage(session.text,True); copied=True
                    except (ValueError,OSError): pass
                finish('已粘贴到本机输入框' if ok else '文字已复制，请重新点击输入框' if copied else '文字已保留，请重新点击输入框')
            self.window.insert(session.local_token,session.text,inserted); return
        try: token=self.clipboard.stage(session.text,settings['keep_transcription'] or not settings['auto_paste'])
        except (ValueError,OSError) as exc: finish(str(exc)); return
        if not settings['auto_paste']: finish('已复制到剪贴板'); return
        if not session.target or session.target.pid==os.getpid() or not self.windows.matches(session.target):
            finish('文字已复制，目标已改变或未定位输入框'); return
        if self.windows.modifiers_down(): finish('文字已复制，请松开修饰键后手动粘贴'); return
        if not self.windows.paste_keys(): finish('文字已复制，系统未能触发粘贴；管理员窗口受权限限制'); return
        if not settings['keep_transcription']:
            self.restore_clipboard(token, time.monotonic()+5,1500)
        finish('已粘贴 · 请在输入框核对')
    def restore_clipboard(self,token,deadline,delay):
        def restore():
            try:
                if self.clipboard.restore(token): return
            except (ValueError,OSError): pass
            if self.clipboard.original is not None and time.monotonic()<deadline: self.restore_clipboard(token,deadline,80)
            elif self.clipboard.original is not None and token[0]==self.clipboard.generation:
                self.paste_test_status='原剪贴板恢复未完成，暂存在本次进程内；转写文字已保留。'
        QTimer.singleShot(delay,restore)
    def copy_displayed(self):
        if self.displayed and self.displayed.has_text: self.clipboard.stage(self.displayed.text,True)
    def retry_displayed(self):
        if self.displayed: self.retry(self.displayed.id)
    def retry(self,sid):
        session=self.sessions.get(str(UUID(sid)).upper())
        if self.active or not session or session.complete or session.recording or session.retrying or not session.pcm: raise ValueError('请结束录音，或等待当前重试完成')
        session.retry(); self.connect(session); self.displayed=session; self.capsule.present()
    def open_section(self,section):
        self.window.activate(); self.window.page.setUrl(QUrl(self.origin+'/workbench#'+section))
    def startup_enabled(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
                value,_=winreg.QueryValueEx(key,'XiaohaVoice')
            return value == self.startup_command()
        except FileNotFoundError: return False
    def startup_command(self):
        if not getattr(sys,'frozen',False): raise ValueError('登录自启请在构建好的Windows程序中设置')
        return subprocess.list2cmdline([sys.executable,'--startup','--toolkit',str(self.root)])
    def set_startup(self,enabled):
        import winreg
        command=self.startup_command()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            if enabled: winreg.SetValueEx(key,'XiaohaVoice',0,winreg.REG_SZ,command)
            else:
                try:
                    previous,_=winreg.QueryValueEx(key,'XiaohaVoice')
                    if previous == command: winreg.DeleteValue(key,'XiaohaVoice')
                except FileNotFoundError: pass
    def async_work(self,label,function):
        if self.toolkit_busy or self.active or any(not s.complete and not s.failure for s in self.sessions.values()): raise ValueError('请结束录音并等待识别或本机操作完成')
        self.toolkit_busy=True; self.toolkit_status=label+'中…'
        if label=='恢复': self.stop_server()
        def run():
            try:
                result=function(); self.work_finished.emit(label,result); return result
            except Exception:
                self.work_finished.emit(label,{'error':True}); raise
        return self.worker.submit(run)
    def _work_finished(self,label,result):
        self.toolkit_busy=False
        self.toolkit_status=label+('未完成，原资料保留' if result.get('error') else '已完成')
        if label=='恢复' and not result.get('error'):
            completed=[row['id'] for row in load_json(self.history.path,[])]
            restored,issues=self.recovery.load(completed); self.recovery_issues=issues
            self.sessions.update((s.id,s) for s in restored); self.window.announce_history()
        if label=='恢复':
            self.server_started=time.monotonic(); self.start_server(); self.health_timer.start(250)
    def status(self):
        from PySide6.QtMultimedia import QMediaDevices
        return {'version':__version__,'platform':'Windows','recording':bool(self.active),'input_monitoring':self.hooks.running,
                'accessibility':True,'microphone':bool(QMediaDevices.audioInputs()),'microphone_status':'录音时由系统检查授权',
                'shortcut':self.hooks.gesture.shortcut.label,'hotkey_enabled':self.hooks.running,
                'launch_at_login':self.startup_enabled() if getattr(sys,'frozen',False) else False,
                'silent_startup':self.settings['silent_startup'],'show_dock':self.settings['show_dock'],
                'capsule_theme':load_json(self.data/'capsule-settings.json',{}).get('mode','initial'),
                'pending_count':sum(not s.complete for s in self.sessions.values()),'toolkit_busy':self.toolkit_busy,
                'toolkit_status':self.toolkit_status,'paste_test_running':self.paste_test_running,'paste_test_status':self.paste_test_status,
                'last_paste_status':self.paste_test_status}
    def dispatch(self,action,value):
        if action=='status': return self.status()
        if action=='recovery':
            return {'records':[{'id':s.id,'created_at':s.created_at,'text':s.text,'seconds':s.seconds,
                     'recording':s.recording,'retrying':s.retrying} for s in self.sessions.values() if not s.complete and s.pcm]}
        if action=='copy':
            if not isinstance(value,str) or len(value)>1_000_000: raise ValueError('复制文字无效')
            self.clipboard.stage(value,True); return {'ok':True}
        if action=='capsuleAppearance':
            from .qt_ui import INITIAL
            if not isinstance(value,dict): raise ValueError('配色设置无效')
            if 'theme' in value:
                if value['theme'] not in ('cocoa','mint','ink'): raise ValueError('主题无效')
                self.capsule.palettes.preview=value['theme']
            self.capsule.palettes.resolve()
            if 'mode' in value:
                mode=value['mode']
                if not isinstance(mode,str) or mode not in ('initial','follow') and mode not in self.capsule.palettes.values: raise ValueError('请选择可用的悬浮窗配色')
                atomic_json(self.data/'capsule-settings.json',{'mode':mode})
            self.capsule.recolor(); return {'mode':load_json(self.data/'capsule-settings.json',{}).get('mode','initial')}
        if action=='previewCapsule': self.capsule.preview(); return {'ok':True}
        if action in ('beginShortcut','cancelShortcut'):
            if self.active: raise ValueError('请结束录音后再登记快捷键')
            self.hooks.suspended=action=='beginShortcut'; self.hooks.capture_mouse=self.hooks.suspended
            if self.hooks.suspended: QTimer.singleShot(30000,lambda:self.cancel_shortcut())
            return {'ok':True}
        if action=='shortcut':
            if self.active: raise ValueError('请结束录音后再修改快捷键')
            shortcut=self.decode_shortcut(value); self.settings['shortcut']=value; self.save_settings()
            self.hooks.gesture=__import__('xiaoha_windows.core',fromlist=['Gesture']).Gesture(shortcut); self.cancel_shortcut(); return {'ok':True}
        if action=='launchAtLogin':
            if type(value) is not bool: raise ValueError('启动开关格式无效')
            self.set_startup(value); return {'ok':True}
        if action=='startup':
            if not isinstance(value,dict) or any(type(value.get(k)) is not bool for k in ('silent_startup','show_dock')): raise ValueError('启动设置无效')
            self.settings.update(value); self.save_settings()
            visible=self.window.isVisible(); self.window.setWindowFlag(Qt.WindowType.Tool,not value['show_dock'])
            if visible: self.window.show()
            return {'ok':True}
        if action in ('microphoneSettings','inputPermission','pastePermission'):
            uri='ms-settings:privacy-microphone' if action=='microphoneSettings' else 'ms-settings:typing' if action=='inputPermission' else 'ms-settings:easeofaccess-keyboard'
            QDesktopServices.openUrl(QUrl(uri)); return {'ok':True}
        if action=='pasteTest':
            if self.active or self.paste_test_running: raise ValueError('请结束录音或等待当前测试完成')
            self.paste_test_running=True; self.paste_test_status='5秒内切到空白输入框，不发送。'
            QTimer.singleShot(5000,self._paste_test); return {'ok':True}
        if action in ('retryRecovery','discardRecovery'):
            if not isinstance(value,dict) or not isinstance(value.get('id'),str): raise ValueError('录音编号无效')
            sid=str(UUID(value['id'])).upper(); session=self.sessions.get(sid)
            if self.active or not session or session.complete or session.retrying or session.recording: raise ValueError('录音正在使用或已完成，未执行操作')
            if action=='retryRecovery': self.retry(sid)
            else:
                if value.get('confirmed') is not True or not session.failure: raise ValueError('请先在工作台确认移至回收站')
                self.recovery.save(session); self.recovery.discard(sid,self.windows.trash)
                bridge=self.bridges.pop(sid,None)
                if bridge: self.retired_bridges.add(bridge); bridge.cancel()
                del self.sessions[sid]
            return {'ok':True}
        if action=='export':
            if not isinstance(value,dict) or not isinstance(value.get('text'),str) or len(value['text'])>2_000_000: raise ValueError('导出文字格式无效')
            name=value.get('filename','小哈语音-本机历史.txt')
            if not isinstance(name,str) or Path(name).name!=name or ':' in name or '\\' in name: raise ValueError('导出文件名无效')
            path,_=QFileDialog.getSaveFileName(self.window,'导出文字',name)
            if not path: return {'cancelled':True}
            Path(path).write_text(value['text'],encoding='utf-8'); return {'ok':True}
        if action=='backupToolkit':
            path,_=QFileDialog.getSaveFileName(self.window,'创建完整备份','小哈语音-Windows完整备份.zip','ZIP (*.zip)')
            if not path: return {'cancelled':True}
            for s in self.sessions.values(): self.preserve(s)
            from desktop.toolkit_archive import create_backup
            return self.async_work('备份',lambda:create_backup(self.root,path))
        if action=='chooseRestore':
            if self.active or any(not s.complete and not s.failure for s in self.sessions.values()): raise ValueError('请先结束录音并等待识别完成')
            path,_=QFileDialog.getOpenFileName(self.window,'选择完整备份','','ZIP (*.zip)')
            if not path: return {'cancelled':True}
            from desktop.toolkit_archive import verify
            token=__import__('uuid').uuid4().hex
            def inspect():
                report=verify(path)
                self.restore_choice=(token,path,hashlib.sha256(Path(path).read_bytes()).hexdigest())
                return {'token':token,'created':report['created'],'records':report['records']}
            return self.async_work('检查备份',inspect)
        if action=='restoreToolkit':
            if not isinstance(value,dict) or not self.restore_choice or value.get('token')!=self.restore_choice[0]: raise ValueError('请重新选择备份文件')
            _,path,digest=self.restore_choice; self.restore_choice=None
            from desktop.toolkit_archive import restore_data
            def restore():
                if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest: raise ValueError('备份文件已变化，原资料保留')
                return restore_data(path,self.data)
            return self.async_work('恢复',restore)
        raise ValueError('操作无法识别')
    def cancel_shortcut(self): self.hooks.suspended=False; self.hooks.capture_mouse=False
    def _paste_test(self):
        self.paste_test_running=False
        if self.active: self.paste_test_status='正在录音，已取消测试'; return
        target=self.windows.capture()
        if not target or target.pid==os.getpid(): self.paste_test_status='请切到其他应用的空白输入框再测试'; return
        try:
            self.clipboard.stage('小哈语音自动粘贴测试',True)
            self.paste_test_status='已触发测试粘贴，请在输入框核对；未回车发送。' if self.windows.matches(target) and not self.windows.modifiers_down() and self.windows.paste_keys() else '已复制测试文字，系统未触发粘贴。'
        except (ValueError,OSError) as exc: self.paste_test_status='粘贴测试未完成：'+str(exc)
    def quit(self):
        if self.active:
            QMessageBox.information(self.window,'仍在录音','请先按启停键结束录音，再退出小哈语音。'); return
        if self.toolkit_busy:
            QMessageBox.information(self.window,'本机操作进行中','请等待备份或恢复完成后再退出。'); return
        for session in self.sessions.values(): self.preserve(session)
        self.shutdown(); self.app.quit()
    def shutdown(self):
        if self.closed: return
        self.closed=True
        self.timer.stop(); self.health_timer.stop(); self.hooks.stop(); self.capture.stop()
        bridges=set(self.bridges.values())|self.retired_bridges
        for bridge in bridges: bridge.cancel()
        deadline=time.monotonic()+3
        for bridge in bridges: bridge.wait_finished(max(0,deadline-time.monotonic()))
        self.retired_bridges.update(bridges); self.bridges.clear(); self.reap_bridges()
        self.stop_server()
        self.tray.hide(); self.capsule.hide(); self.worker.shutdown(wait=False,cancel_futures=True)
    def stop_server(self):
        if self.server and self.server.poll() is None:
            self.server.terminate()
            try: self.server.wait(timeout=2)
            except subprocess.TimeoutExpired: self.server.kill()
            self.server.wait(timeout=2)


def run(root,startup=False):
    if os.name!='nt': raise SystemExit('这是Windows桌面宿主；Mac使用现有小哈语音。')
    app=QApplication(sys.argv); app.setApplicationName('小哈语音'); app.setQuitOnLastWindowClosed(False)
    from PySide6.QtCore import QDir
    name='XiaohaVoice-Desktop'
    lock=QLockFile(QDir.tempPath()+'/'+name+'.lock'); lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        socket=QLocalSocket(); socket.connectToServer(name)
        if socket.waitForConnected(1000): socket.write(b'show'); socket.flush(); socket.waitForBytesWritten(200); socket.disconnectFromServer()
        return 0
    controller=Controller(app,root,startup)
    controller.single.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    app.aboutToQuit.connect(controller.shutdown)
    return app.exec()
