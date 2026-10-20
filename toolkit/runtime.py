"""Frozen local runtime for the macOS toolkit. No UI automation or hidden startup."""
from pathlib import Path
import argparse, asyncio, json, os, sys

def main():
    if len(sys.argv)<2:raise ValueError('请选择运行模式')
    mode=sys.argv.pop(1)
    if mode=='control':
        from desktop.control import main as control
        control();return
    if mode=='bridge':
        import channel_probe
        args=argparse.Namespace(mode='bridge',register_if_needed=False,pcm=None,label='',expected='',output=None)
        try:asyncio.run(channel_probe.main(args))
        except SystemExit:raise
        except Exception:
            channel_probe.emit({'event':'error','message':'识别尚未初始化或运行组件不可用；请检查识别服务设置，没有自动重新注册身份。'})
            raise SystemExit(1)
        return
    if mode=='initialize':
        import channel_probe
        channel_probe.credentials(channel_probe.constants(),allow_register=True)
        print(json.dumps({'ready':True}));return
    if mode=='selfcheck':
        import channel_probe,fastapi,uvicorn,websockets,jieba,keyring,requests,certifi
        encoder=channel_probe.Opus();encoded=encoder.encode(bytes(640));encoder.close()
        print(json.dumps({'runtime':True,'opus':bool(encoded),'network_called':False,'microphone_opened':False}));return
    from desktop.toolkit_archive import create_backup,verify,restore_data,restore_new
    p=argparse.ArgumentParser();p.add_argument('--toolkit');p.add_argument('--output');p.add_argument('--archive');p.add_argument('--data');p.add_argument('--destination');a=p.parse_args()
    if mode=='backup':result=create_backup(a.toolkit,a.output)
    elif mode=='inspect':result=verify(a.archive);result={k:result[k] for k in ('created','records','native_records','imported_records','platform')}
    elif mode=='restore-data':result=restore_data(a.archive,a.data)
    elif mode=='restore-new':result=restore_new(a.archive,a.destination);result={k:result[k] for k in ('created','records')}
    else:raise ValueError('不支持的运行模式')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'error':str(exc) if isinstance(exc,(ValueError,FileExistsError)) else '本机操作未完成，原资料已保留'},ensure_ascii=False));raise SystemExit(1)
