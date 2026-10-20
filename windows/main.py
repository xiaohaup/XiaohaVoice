from pathlib import Path
import argparse,json,os,sys

def main():
    p=argparse.ArgumentParser();p.add_argument('--toolkit',type=Path);p.add_argument('--startup',action='store_true')
    p.add_argument('--selfcheck',type=Path,help=argparse.SUPPRESS);a=p.parse_args()
    root=(a.toolkit or (Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent/'devkit')).resolve()
    if sys.platform!='win32': raise SystemExit('Windows宿主仅可在Windows启动；本机Mac程序未改变。')
    if not (root/'toolkit.json').is_file(): raise SystemExit('完整工具包缺失，请一起解压全部文件。')
    os.environ.update(XH_VOICE_DATA=str(root/'Data'),XH_VOICE_ENGINE=str(root/'Components/engine'),
                      XH_VOICE_WORKBENCH=str(root/'Components/workbench'),XH_VOICE_IDENTITY=str(root/'Data/recognition'),
                      XH_VOICE_OPUS=str(root/'Components/engine/opus.dll'))
    sys.path[:0]=[str(root/'Components/workbench'),str(root/'Components/engine')]
    if a.selfcheck:
        from PySide6.QtCore import qVersion
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtMultimedia import QAudioSource
        with a.selfcheck.open('x',encoding='utf-8') as stream:
            json.dump({'qt':True,'qt_version':qVersion(),'webengine':True,'multimedia':True,
                       'network_called':False,'microphone_opened':False},stream)
        return 0
    from xiaoha_windows.app import run
    return run(root,a.startup)
if __name__=='__main__':raise SystemExit(main())
