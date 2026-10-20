import argparse
import os
from pathlib import Path
import uvicorn
from server.app import Config,create_app

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='小哈语音同步服务：默认仅本机')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--data',type=Path,default=Path(__file__).resolve().parent/'private/server')
    parser.add_argument('--preview',action='store_true',help='隔离的本机预览；只使用合成账号和示例数据')
    args=parser.parse_args()
    if args.preview:
        args.data=Path(__file__).resolve().parent/'private/preview'
    origin='http://127.0.0.1:'+str(args.port)
    config=Config(args.data,origin,args.preview,'')
    uvicorn.run(create_app(config),host='127.0.0.1',port=args.port,access_log=False)
