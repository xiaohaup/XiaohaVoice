"""Console worker with valid stdin/stdout; GUI host launches it without a console window."""
import os,sys
from pathlib import Path

def main():
    root=Path(os.environ['XH_VOICE_WORKBENCH']).parent.parent
    sys.path[:0]=[str(root/'Components/workbench'),str(root/'Components/engine')]
    if len(sys.argv)<2: raise ValueError('运行模式缺失')
    mode=sys.argv.pop(1)
    if mode=='control':
        from desktop.control import main as control
        control();return
    if mode=='bridge':
        import asyncio,argparse,channel_probe
        try: asyncio.run(channel_probe.main(argparse.Namespace(mode='bridge',register_if_needed=False,pcm=None,label='',expected='',output=None)))
        except SystemExit: raise
        except Exception:
            channel_probe.emit({'event':'error','message':'识别尚未初始化或运行组件不可用，请检查识别服务设置。'})
            raise SystemExit(1)
        return
    if mode=='selfcheck':
        import channel_probe
        encoder=channel_probe.Opus();data=encoder.encode(bytes(640));encoder.close()
        print(__import__('json').dumps({'runtime':True,'opus':bool(data),'network_called':False,'microphone_opened':False}));return
    raise ValueError('运行模式无效')
if __name__=='__main__':main()
