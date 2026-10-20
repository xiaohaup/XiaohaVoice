"""Shared workbench host and non-activating recording capsule."""
from __future__ import annotations
import json,time
from pathlib import Path
from urllib.parse import urlsplit
from PySide6.QtCore import Qt,QObject,Signal,Slot,QFile,QUrl,QTimer,QPoint,QRectF
from PySide6.QtGui import QColor,QPainter,QPainterPath,QDesktopServices,QIcon,QPixmap,QRegion,QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget,QLabel,QPushButton,QVBoxLayout,QHBoxLayout,QMainWindow,QScrollArea
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineScript,QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel

INITIAL = {'background':'#23272f','foreground':'#ffffff','muted':'#bfbfbf','border':'#3b3e45','accent':'#94dee8','dark':True}

class Palettes:
    def __init__(self, root): self.root = Path(root); self.stamp = None; self.values = {}; self.preview = None
    def resolve(self):
        from .core import load_json
        catalog = self.root/'Components/workbench/web/capsule-palettes.json'
        stamp = (catalog.stat().st_mtime_ns,catalog.stat().st_size) if catalog.exists() else None
        if self.stamp != stamp:
            self.stamp = stamp; self.values = {}
            try:
                raw = load_json(catalog,{}) if catalog.stat().st_size <= 64_000 else {}
                for key,value in list(raw.items())[:32]:
                    if isinstance(value,dict) and type(value.get('dark')) is bool and all(
                        isinstance(value.get(k),str) and __import__('re').fullmatch(r'#[\da-fA-F]{6}',value[k])
                        for k in ('background','foreground','muted','border','accent')):
                        self.values[key] = value
            except (ValueError,OSError,TypeError,AttributeError): pass
        mode = load_json(self.root/'Data/capsule-settings.json',{}).get('mode','initial')
        if mode == 'follow': mode = self.preview or load_json(self.root/'Data/desktop/workbench.json',{}).get('theme','cocoa')
        return self.values.get(mode,INITIAL)

class Wave(QWidget):
    def __init__(self): super().__init__(); self.rms = 0; self.color = '#94dee8'; self.setFixedSize(35,24)
    def paintEvent(self,event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(self.color))
        level = max(.08,min(1,(max(0,self.rms)*9)**.6))
        for i,ratio in enumerate((.35,.6,.9,.65,1,.7,.4)):
            height = max(2,24*ratio*level); painter.drawRoundedRect(QRectF(i*5,(24-height)/2,3,height),1.5,1.5)

class Capsule(QWidget):
    cancel = Signal(); copied = Signal(); retried = Signal()
    def __init__(self, root):
        super().__init__(None,Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint|Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground); self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating); self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setObjectName('capsule'); self.setWindowTitle('小哈语音 · 悬浮窗'); self.setFixedWidth(420)
        self.palettes = Palettes(root); self.wave = Wave(); self.preview_until = 0
        self.status = QLabel('准备好'); self.clock = QLabel('00:00'); self.hint = QLabel('右 Alt 开始')
        self.line = QLabel('说话时，文字会显示在这里…'); self.line.setWordWrap(True); self.line.setMaximumHeight(55)
        self.close_button = QPushButton('×'); self.copy = QPushButton('复制'); self.retry = QPushButton('重试识别')
        for button in (self.close_button,self.copy,self.retry): button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.setFixedSize(25,25); self.copy.setFixedWidth(45); self.retry.setFixedWidth(80)
        self.close_button.clicked.connect(self.cancel); self.copy.clicked.connect(self.copied); self.retry.clicked.connect(self.retried)
        top = QHBoxLayout(); top.setSpacing(10)
        top.addWidget(self.wave); top.addWidget(self.status,1); top.addWidget(self.clock); top.addWidget(self.hint); top.addWidget(self.retry); top.addWidget(self.close_button)
        bottom = QHBoxLayout(); bottom.addWidget(self.line,1); bottom.addWidget(self.copy)
        layout = QVBoxLayout(self); layout.setContentsMargins(16,8,12,12); layout.setSpacing(5); layout.addLayout(top); layout.addLayout(bottom)
        self.preview_timer = QTimer(self); self.preview_timer.setSingleShot(True); self.preview_timer.timeout.connect(self._end_preview)
        self.busy = False; self.retry.hide(); self.recolor()
    def recolor(self):
        p = self.palettes.resolve(); self.colors = p; self.wave.color = p['accent']; self.wave.update(); self.update()
        self.setStyleSheet(f'''
        QLabel{{color:{p['foreground']};background:transparent;font:13px 'Microsoft YaHei UI';border:0;}}
        QPushButton{{background:transparent;border:0;border-radius:6px;color:{p['muted']};font:11px 'Microsoft YaHei UI';padding:3px;}}
        QPushButton:hover{{background:{p['border']};}} QPushButton:disabled{{color:{p['border']};}}''')
        self.clock.setStyleSheet('color:'+p['muted']); self.hint.setStyleSheet('color:'+p['muted']+';font-size:11px;')
    def paintEvent(self,event):
        # A translucent QWidget subclass does not paint stylesheet backgrounds.
        # Paint an opaque panel explicitly; only the rounded outer corners clear.
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(self.colors['border']),1))
        painter.setBrush(QColor(self.colors['background']))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),20,20)
    def present(self):
        screen = self.screen() or __import__('PySide6.QtWidgets',fromlist=['QApplication']).QApplication.primaryScreen()
        area = screen.availableGeometry(); self.adjustSize(); self.move(area.center().x()-self.width()//2,area.bottom()-self.height()-30)
        self.show()
    def update_session(self, session, shortcut):
        self.recolor()
        if self.preview_until > time.monotonic() and not self.busy: return
        if session:
            seconds = int(session.seconds); self.clock.setText(f'{seconds//60:02d}:{seconds%60:02d}')
            self.status.setText('录音中' if session.recording else '识别中' if not session.complete and not session.failure else '已保留' if session.failure else '已完成')
            self.hint.setText(shortcut+(' 结束' if session.recording else ' 开始'))
            self.line.setText(session.delivery or session.text[-220:] or (session.failure if session.failure else '正在听，文字会显示在这里…'))
            self.copy.setEnabled(bool(session.text)); self.retry.setVisible(bool(session.failure and not session.recording)); self.hint.setVisible(not bool(session.failure and not session.recording))
            self.wave.rms = session.activity.last_rms if session.recording else 0; self.wave.update()
    def preview(self):
        if self.busy: self.present(); return
        self.preview_until = time.monotonic()+4; self.recolor(); self.status.setText('配色预览'); self.clock.setText('00:00')
        self.hint.setText('悬浮窗配色预览'); self.hint.show(); self.retry.hide(); self.copy.setEnabled(False)
        self.line.setText('说话时，文字会显示在这里…'); self.present(); self.preview_timer.start(4000)
    def _end_preview(self):
        self.preview_until = 0
        if not self.busy: self.hide()

class Page(QWebEnginePage):
    def __init__(self, profile, origin, parent): super().__init__(profile,parent); self.origin = origin
    def acceptNavigationRequest(self,url,kind,main):
        text = url.toString(); parsed = urlsplit(text)
        if parsed.scheme == 'about': return True
        if parsed.scheme in ('http','https') and text.startswith(self.origin+'/'):
            return not main or parsed.path == '/workbench'
        if main and kind == QWebEnginePage.NavigationType.NavigationTypeLinkClicked and parsed.scheme == 'https':
            QDesktopServices.openUrl(url)
        return False

class NativeChannel(QObject):
    response = Signal(str,str)
    def __init__(self, page, dispatch, origin): super().__init__(page); self.page = page; self.dispatch = dispatch; self.origin = origin
    @Slot(str)
    def postMessage(self, raw):
        rid = ''
        try:
            if len(raw)>2_100_000: raise ValueError('请求内容过大')
            url = self.page.url(); parsed = urlsplit(url.toString())
            if parsed.scheme != 'http' or parsed.netloc != urlsplit(self.origin).netloc or parsed.path != '/workbench': raise ValueError('仅允许本机主工作台请求')
            value = json.loads(raw); rid = value['id']
            if not isinstance(rid,str) or len(rid)>100: raise ValueError('请求编号无效')
            result = self.dispatch(value['action'],value.get('value'))
            from concurrent.futures import Future
            if isinstance(result,Future):
                def finished(future):
                    try: payload={'ok':True,'value':future.result()}
                    except Exception as error: payload={'ok':False,'error':str(error) if isinstance(error,(ValueError,OSError)) else '本机操作未完成，原资料保留'}
                    self.response.emit(rid,json.dumps(payload,ensure_ascii=False))
                result.add_done_callback(finished)
            else: self.response.emit(rid,json.dumps({'ok':True,'value':result},ensure_ascii=False))
        except Exception as exc:
            message = str(exc) if isinstance(exc,(ValueError,OSError)) else '本机操作未完成，原资料保留'
            self.response.emit(rid,json.dumps({'ok':False,'error':message},ensure_ascii=False))

class WindowChrome(QWidget):
    """Content overlay: no extra title row; Qt owns moving/resizing on any DPI."""
    BORDER=5
    def __init__(self,window):
        super().__init__(window); self.window=window; self.setObjectName('window-chrome')
        self.main_color='#f2efe8'; self.sidebar_color='#fbf9f5'; self.ink='#514a3e'; self.sidebar_width=184
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground); self.setMouseTracking(True)
        self.buttons=[]
        for label,symbol,action in [('最小化','−',window.showMinimized),('最大化','□',self.toggle_maximized),('关闭窗口，保留托盘','×',window.close)]:
            button=QPushButton(symbol,self); button.setAccessibleName(label); button.setToolTip(label)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus); button.clicked.connect(action); self.buttons.append(button)
        self.buttons[-1].setObjectName('close-window')
        self.recolor(); self.fit()
    def recolor(self,colors=None):
        if isinstance(colors,dict) and all(QColor(str(colors.get(k,''))).isValid() for k in ('main','sidebar','text')):
            self.main_color=colors['main'];self.sidebar_color=colors['sidebar'];self.ink=colors['text']
            self.sidebar_width=int(colors.get('sidebar_width',184))
        self.setStyleSheet(f'QPushButton{{background:transparent;border:0;border-radius:0;color:{self.ink};font:18px "Segoe UI";padding:0;}} QPushButton:hover{{background:rgba(120,110,95,35);}} QPushButton#close-window:hover{{background:#c84b42;color:white;}}')
        self.update()
    def fit(self):
        self.setGeometry(self.window.rect()); w,h=self.width(),self.height(); b=self.BORDER
        region=QRegion(0,0,w,24).united(QRegion(w-138,0,138,28))
        if not self.window.isMaximized():
            region=region.united(QRegion(0,0,b,h)).united(QRegion(w-b,0,b,h)).united(QRegion(0,h-b,w,b))
        self.setMask(region)
        for i,button in enumerate(self.buttons): button.setGeometry(w-138+i*44,0,44,28)
        self.buttons[1].setText('❐' if self.window.isMaximized() else '□')
        self.buttons[1].setAccessibleName('还原窗口' if self.window.isMaximized() else '最大化')
        self.raise_()
    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor(self.main_color))
        painter.fillRect(0,0,self.sidebar_width,self.height(),QColor(self.sidebar_color))
    def edges(self,point):
        if self.window.isMaximized(): return Qt.Edge(0)
        b=self.BORDER; edge=Qt.Edge(0)
        if point.x()<b: edge|=Qt.Edge.LeftEdge
        elif point.x()>=self.width()-b: edge|=Qt.Edge.RightEdge
        if point.y()<b: edge|=Qt.Edge.TopEdge
        elif point.y()>=self.height()-b: edge|=Qt.Edge.BottomEdge
        return edge
    def mouseMoveEvent(self,event):
        edge=self.edges(event.position().toPoint())
        diagonal1=Qt.Edge.LeftEdge|Qt.Edge.TopEdge; diagonal2=Qt.Edge.RightEdge|Qt.Edge.TopEdge
        cursor=(Qt.CursorShape.SizeFDiagCursor if edge in (diagonal1,Qt.Edge.RightEdge|Qt.Edge.BottomEdge)
                else Qt.CursorShape.SizeBDiagCursor if edge in (diagonal2,Qt.Edge.LeftEdge|Qt.Edge.BottomEdge)
                else Qt.CursorShape.SizeHorCursor if edge & (Qt.Edge.LeftEdge|Qt.Edge.RightEdge)
                else Qt.CursorShape.SizeVerCursor if edge else Qt.CursorShape.ArrowCursor)
        self.setCursor(cursor)
    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton: return
        handle=self.window.windowHandle(); edge=self.edges(event.position().toPoint())
        if handle:
            import os
            if os.name=='nt':
                # Qt posts SC_DRAGMOVE asynchronously on Windows. Dispatch it
                # while the press is still active, even for a short gesture.
                import ctypes as C
                from ctypes import wintypes as W
                sizes={Qt.Edge.LeftEdge:1,Qt.Edge.RightEdge:2,Qt.Edge.TopEdge:3,
                       Qt.Edge.LeftEdge|Qt.Edge.TopEdge:4,Qt.Edge.RightEdge|Qt.Edge.TopEdge:5,
                       Qt.Edge.BottomEdge:6,Qt.Edge.LeftEdge|Qt.Edge.BottomEdge:7,Qt.Edge.RightEdge|Qt.Edge.BottomEdge:8}
                user=C.WinDLL('user32',use_last_error=True)
                user.SendMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM];user.SendMessageW.restype=C.c_ssize_t
                user.ReleaseCapture(); user.SendMessageW(W.HWND(int(self.window.winId())),0x112,0xf000+sizes[edge] if edge else 0xf012,0)
            elif edge: handle.startSystemResize(edge)
            else: handle.startSystemMove()
    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and not self.edges(event.position().toPoint()): self.toggle_maximized()
    def toggle_maximized(self):
        self.window.showNormal() if self.window.isMaximized() else self.window.showMaximized()

class Workbench(QMainWindow):
    closing = Signal()
    def __init__(self, root, origin, dispatch):
        super().__init__(); self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.root = Path(root); self.setWindowTitle('小哈语音'); self.resize(1100,760); self.setMinimumSize(820,600)
        self.browser = QWebEngineView(self); self.setCentralWidget(self.browser)
        self.profile = QWebEngineProfile(self); self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.page = Page(self.profile,origin,self.browser); self.browser.setPage(self.page)
        self.channel = QWebChannel(self.page); self.native = NativeChannel(self.page,dispatch,origin)
        self.channel.registerObject('nativeHost',self.native); self.page.setWebChannel(self.channel)
        source = QFile(':/qtwebchannel/qwebchannel.js')
        if not source.open(QFile.OpenModeFlag.ReadOnly): raise RuntimeError('桌面桥接资源缺失')
        channel_js = bytes(source.readAll()).decode(); source.close()
        bridge = '''(()=>{if(window!==window.top)return;window.xiaohaPlatform='Windows';let channelReady;
        const pending=new Map();let next=0;
        const ready=new Promise(resolve=>channelReady=resolve);
        window.webkit={messageHandlers:{xiaoha:{postMessage(value){return ready.then(host=>new Promise((resolve,reject)=>{const id=String(++next);const timer=setTimeout(()=>{pending.delete(id);reject(Error('本机操作等待超时，请查看当前状态'));},120000);pending.set(id,{resolve,reject,timer});host.postMessage(JSON.stringify({...value,id}));}));}}}};
        new QWebChannel(qt.webChannelTransport,channel=>{const host=channel.objects.nativeHost;host.response.connect((id,raw)=>{const item=pending.get(id);if(!item)return;clearTimeout(item.timer);pending.delete(id);const result=JSON.parse(raw);result.ok?item.resolve(result.value):item.reject(Error(result.error));});channelReady(host);});})();'''
        script = QWebEngineScript(); script.setName('XiaohaLocalNativeBridge'); script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld); script.setRunsOnSubFrames(False); script.setSourceCode(channel_js+'\n'+bridge)
        self.page.scripts().insert(script)
        self.chrome=WindowChrome(self)
        self.chrome_timer=QTimer(self);self.chrome_timer.timeout.connect(self.sync_chrome);self.chrome_timer.start(500)
        self.page.loadFinished.connect(lambda _:self.sync_chrome())
    def sync_chrome(self):
        self.page.runJavaScript("(()=>{if(!document.body)return null;const s=getComputedStyle(document.body),a=document.querySelector('aside');return {main:s.getPropertyValue('--main').trim(),sidebar:s.getPropertyValue('--sidebar').trim(),text:s.getPropertyValue('--text').trim(),sidebar_width:a?Math.round(a.getBoundingClientRect().right):184}})()",self.chrome.recolor)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'chrome'): self.chrome.fit()
    def changeEvent(self,event):
        super().changeEvent(event)
        if hasattr(self,'chrome'): self.chrome.fit()
    def open(self, origin): self.page.setUrl(QUrl(origin+'/workbench'))
    def activate(self):
        if self.isMinimized(): self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show(); self.raise_(); self.activateWindow()
    def closeEvent(self,event): event.ignore(); self.hide(); self.closing.emit()
    def announce_history(self):
        self.page.runJavaScript("if(typeof historySignature!=='undefined'){historySignature='';summarySignature='';if(section==='history')safe(history);if(section==='overview')safe(summary);}")
    def insert(self, token, text, done):
        self.page.runJavaScript('window.xiaohaInsertField?.('+json.dumps(token)+','+json.dumps(text)+')||false',done)
    def capture_field(self, done): self.page.runJavaScript('window.xiaohaCaptureField?.()||null',done)
    def mouse_shortcut(self,value): self.page.runJavaScript("window.dispatchEvent(new CustomEvent('xiaoha-mouse-shortcut',{detail:"+json.dumps(value)+"}));")


def make_icon(root):
    pix = QPixmap(256,256); pix.fill(Qt.GlobalColor.transparent); painter = QPainter(pix); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor('#e6dfd3')); painter.drawRoundedRect(0,0,256,256,64,64)
    path = Path(root)/'Components/workbench/web/voice-glyph.svg'
    if path.exists():
        raw = path.read_bytes().replace(b'currentColor',b'#715b42').replace(b'black',b'#715b42').replace(b'<svg ',b'<svg fill="#715b42" '); renderer = QSvgRenderer(raw)
        painter.translate(35,35); renderer.render(painter,__import__('PySide6.QtCore',fromlist=['QRectF']).QRectF(0,0,186,186))
    painter.end(); return QIcon(pix)
