"""Isolated Qt WebEngine smoke. Fake native adapters; no recording or OS input."""
import os,sys,json,socket,tempfile,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'devkit/Components/workbench')]
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from xiaoha_windows.qt_ui import Workbench

def main():
    with tempfile.TemporaryDirectory(prefix='xhvoice-ui-') as temporary:
        data=Path(temporary)/'Data';data.mkdir();history=data/'history.json';history.write_text('[]')
        os.environ.update(XH_VOICE_DATA=str(data),XH_VOICE_WORKBENCH=str(ROOT/'devkit/Components/workbench'),XH_VOICE_ENGINE=str(ROOT/'devkit/Components/engine'),XH_VOICE_IDENTITY=str(data/'recognition'))
        from desktop.control import Companion,create_control
        import uvicorn
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        origin='http://127.0.0.1:'+str(port)
        class Clipboard:
            def read(self):raise AssertionError('OS clipboard must not be accessed')
            def write(self,*args):raise AssertionError('OS clipboard must not be accessed')
        class Vault:
            def load(self,*args):raise AssertionError('credential vault must not be accessed')
        companion=Companion(data/'desktop',Clipboard(),Vault(),history_path=history)
        server=uvicorn.Server(uvicorn.Config(create_control(companion,origin),host='127.0.0.1',port=port,log_level='error',access_log=False))
        thread=threading.Thread(target=server.run,daemon=True);thread.start()
        deadline=time.monotonic()+10
        while not server.started:
            if time.monotonic()>deadline:raise RuntimeError('Local fixture server did not start')
            time.sleep(.03)
        calls=[]
        def dispatch(action,value):
            calls.append(action)
            if action=='status':return {'version':'test-only','platform':'Windows','recording':False,'input_monitoring':True,'accessibility':True,'microphone':True,'shortcut':'右 Alt','capsule_theme':'follow'}
            if action=='recovery':return {'records':[]}
            if action=='capsuleAppearance':return {'mode':'follow'}
            raise ValueError('Test prohibits OS operations')
        app=QApplication.instance() or QApplication([]);window=Workbench(ROOT/'devkit',origin,dispatch)
        results=[];failed=[];stage=[0]
        def fail(message):failed.append(message);app.quit()
        def probe():
            window.page.runJavaScript("JSON.stringify({title:document.getElementById('local-title')?.textContent,native:!!window.webkit?.messageHandlers?.xiaoha,bridge:window.__smokeBridge,section:typeof section==='string'?section:null,error:document.getElementById('local-message')?.textContent})",received)
        def received(raw):
            try:value=json.loads(raw)
            except Exception:fail('Invalid browser result');return
            if not value.get('native') or value.get('bridge')!='Windows':fail('Native bridge not ready: '+str(value));return
            if value.get('error'):fail('Workbench error: '+value['error']);return
            expected=['使用统计','语音输入','账号同步'][stage[0]]
            if value['title']!=expected:fail('Wrong workbench section: '+str(value));return
            results.append(value)
            if stage[0]==0:
                stage[0]=1;window.page.runJavaScript("location.hash='voice'");QTimer.singleShot(700,probe)
            elif stage[0]==1:
                stage[0]=2;window.page.runJavaScript("location.hash='sync'");QTimer.singleShot(900,probe)
            else:
                window.page.runJavaScript("(()=>{const d=document.getElementById('account-sync-frame').contentDocument;return JSON.stringify({frame:!!d?.getElementById('auth'),tabs:[...(d?.querySelectorAll('[data-tab]')||[])].filter(n=>!n.hidden).length,navHeight:d?.getElementById('nav').getBoundingClientRect().height,formWidth:d?.getElementById('auth').getBoundingClientRect().width});})()",frame_ready)
        def frame_ready(raw):
            value=json.loads(raw);results.append(value)
            if not value['frame'] or value['tabs']!=5 or value['navHeight']>70 or value['formWidth']<500:fail('Account sync frame layout failed: '+str(value));return
            app.quit()
        def loaded(ok):
            if not ok:fail('Page failed to load');return
            window.page.runJavaScript("window.webkit.messageHandlers.xiaoha.postMessage({action:'status'}).then(v=>window.__smokeBridge=v.platform)")
            QTimer.singleShot(1200,probe)
        window.page.loadFinished.connect(loaded);window.resize(1100,760);window.show();window.open(origin)
        QTimer.singleShot(20000,lambda:fail('UI test timeout'));app.exec()
        server.should_exit=True;thread.join(timeout=3);window.hide()
        report={'passed':not failed,'checks':results,'actions':sorted(set(calls)),'errors':failed,'real_windows_test':False,'os_input_used':False,'microphone_used':False}
        print(json.dumps(report,ensure_ascii=False))
        return 0 if not failed else 1
if __name__=='__main__':raise SystemExit(main())
