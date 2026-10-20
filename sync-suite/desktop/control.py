"""Local-only desktop companion. Same web UI, OS-vault tokens, opt-in background sync."""
from __future__ import annotations
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import secrets
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
import httpx

from desktop.client import ApiError, MacClipboard, Remote, SyncEngine, Vault, WindowsClipboard, read_json, validate_server, write_json

ROOT = Path(os.environ.get('XH_VOICE_WORKBENCH') or Path(__file__).resolve().parent.parent)


class Companion:
    def __init__(self, directory: Path, clipboard=None, vault=None, remote_factory=Remote, history_path=None, wordbook_path=None):
        self.directory, self.clipboard, self.vault, self.remote_factory = directory, clipboard, vault or Vault(), remote_factory
        self.config_path = directory / 'device.json'
        self.config = read_json(self.config_path, {'device_id': str(__import__('uuid').uuid4()), 'server': '', 'account_id': ''})
        self.history_path, self.wordbook_path = history_path, wordbook_path
        self.remote = self.engine = None
        self.local_session = secrets.token_urlsafe(32)
        self.csrf = ''
        self.lock = threading.RLock()
        write_json(self.config_path, self.config)

    def connect(self, server):
        server = validate_server(server)
        with self.lock:
            if server != self.config['server']:
                self.config.update(server=server, account_id='')
                self.remote = self.engine = None
                self.csrf = ''
                self.local_session = secrets.token_urlsafe(32)
                write_json(self.config_path, self.config)

    def ensure_remote(self):
        with self.lock:
            if self.remote:
                return self.remote
            if not self.config['server'] or not self.config['account_id']:
                raise ApiError(401, '请先连接同步账号')
            token = self.vault.load(self.config['server'], self.config['account_id'])
            if not token:
                raise ApiError(401, '请重新登录')
            self.remote = self.remote_factory(self.config['server'], token)
            return self.remote

    def bind(self, identity):
        with self.lock:
            self.config['account_id'] = identity['account_id']
            self.config['username'] = identity['username']
            write_json(self.config_path, self.config)
            self.csrf = identity['csrf']
            key = hashlib.sha256((self.config['server'] + '/' + identity['account_id']).encode()).hexdigest()
            if self.engine is None or self.engine.identity['account_id'] != identity['account_id']:
                self.engine = SyncEngine(self.directory / 'accounts' / key, self.remote, identity, self.clipboard, self.history_path, self.wordbook_path)
            return {k:v for k,v in identity.items() if k != 'token'}

    def login(self, body):
        with self.lock:
            if not self.config['server']:
                raise ApiError(422, '请先填写同步服务地址')
            remote = self.remote_factory(self.config['server'])
            body = dict(body)
            body['device_id'] = self.config['device_id']
            body['platform'] = 'Mac' if platform.system() == 'Darwin' else 'Windows'
            identity = remote.call('POST', '/api/login', body)
            self.vault.save(self.config['server'], identity['account_id'], identity['token'])
            remote.token = identity['token']
            self.remote = remote
            self.local_session = secrets.token_urlsafe(32)
            return self.bind(identity)

    def logout(self):
        with self.lock:
            remote = self.ensure_remote()
            remote.call('POST', '/api/logout', {})
            self.vault.remove(self.config['server'], self.config['account_id'])
            if self.engine:
                self.engine.set_settings({'enabled': False})
            self.remote = self.engine = None
            self.csrf = ''
            self.local_session = secrets.token_urlsafe(32)
            # Only local synced correction material is cleared; dictation history is untouched.
            if self.wordbook_path:
                write_json(self.wordbook_path, {'enabled': False, 'words': []})

    def cycle(self):
        with self.lock:
            engine = self.engine
        if engine:
            engine.sync_once()


def create_control(companion: Companion, origin='http://127.0.0.1:8766'):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.companion = companion
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

    @app.middleware('http')
    async def guard(request, call_next):
        if request.url.path.startswith(('/api/', '/local/')):
            if request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'detail':'仅允许本机页面访问'}, 403)
            if request.method != 'GET':
                if request.headers.get('origin') != origin or 'application/json' not in request.headers.get('content-type',''):
                    return JSONResponse({'detail':'请求来源或格式不匹配'}, 403)
                data=bytearray()
                async for chunk in request.stream():
                    data.extend(chunk)
                    if len(data)>1_048_576:
                        return JSONResponse({'detail':'内容过大'},413)
                request._body=bytes(data)
            public = request.url.path in ('/api/health','/api/login','/api/me','/local/connect')
            if not public:
                cookie=request.cookies.get('xh_local_session','')
                if not hmac.compare_digest(cookie,companion.local_session):
                    return JSONResponse({'detail':'请先登录本机同步页'},401)
                if request.method!='GET' and not hmac.compare_digest(request.headers.get('x-csrf-token',''),companion.csrf):
                    return JSONResponse({'detail':'页面已过期，请刷新'},403)
        try:
            response=await call_next(request)
        except ApiError as e:
            return JSONResponse({'detail':e.detail},e.status)
        response.headers['Cache-Control']='no-store' if request.url.path.startswith(('/api/','/local/')) else 'no-cache'
        # The embedded account panel may only be framed by this same local origin.
        ancestors = "'self'" if request.url.path == '/' and request.query_params.get('embedded') == '1' else "'none'"
        response.headers['Content-Security-Policy']=f"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors {ancestors}; base-uri 'none'; form-action 'self'"
        response.headers['X-Content-Type-Options']='nosniff'
        return response

    @app.exception_handler(ApiError)
    async def api_error(request, error):
        return JSONResponse({'detail':error.detail},error.status)

    @app.exception_handler(httpx.HTTPError)
    async def network_error(request,error):
        return JSONResponse({'detail':'同步服务暂时无法访问，未丢弃本机待同步数据'},503)

    @app.get('/api/health')
    def health():
        return {'ok':True,'desktop':True,'local_only':True,'signup_enabled':False,'server':companion.config['server'],
                'service':'xiaoha-voice-companion','protocol':3,
                'instance':hashlib.sha256(str(companion.directory.resolve()).encode()).hexdigest()}

    @app.post('/local/connect')
    async def connect(request:Request):
        value=await request.json()
        try: companion.connect(value['server'])
        except (ValueError,KeyError): raise ApiError(422,'请填写有效的HTTPS同步服务地址')
        return {'ok':True}

    @app.post('/api/login')
    async def login(request:Request):
        identity=companion.login(await request.json())
        response=JSONResponse(identity)
        response.set_cookie('xh_local_session',companion.local_session,httponly=True,samesite='strict',path='/')
        return response

    @app.get('/api/me')
    def me():
        identity=companion.ensure_remote().call('GET','/api/me')
        result=companion.bind(identity)
        response=JSONResponse(result)
        response.set_cookie('xh_local_session',companion.local_session,httponly=True,samesite='strict',path='/')
        return response

    @app.post('/api/logout')
    def logout():
        companion.logout()
        response=JSONResponse({'ok':True});response.delete_cookie('xh_local_session',path='/');return response

    @app.get('/local/settings')
    def settings():
        if not companion.engine: raise ApiError(401,'请重新登录')
        return companion.engine.settings()

    @app.post('/local/settings')
    async def settings_save(request:Request):
        value=await request.json()
        if set(value)-{'enabled','send_clipboard','receive_clipboard','usage_sync'} or any(type(v) is not bool for v in value.values()):
            raise ApiError(422,'本机设置格式无效')
        companion.engine.set_settings(value)
        return {'ok':True}

    @app.post('/local/resolve')
    async def resolve(request:Request):
        value=await request.json()
        try: companion.engine.resolve(value['operation_id'],value['choice'])
        except (ValueError,KeyError) as e: raise ApiError(422,str(e))
        return {'ok':True}

    @app.get('/local/history')
    def history():
        return {'records':companion.engine.read_history()}

    @app.get('/api/state')
    def state(since:int=0):
        return companion.ensure_remote().call('GET','/api/state?since='+str(max(0,since)))

    @app.post('/api/mutate')
    async def mutate(request:Request):
        return companion.ensure_remote().call('POST','/api/mutate',await request.json())

    @app.post('/api/devices/{device_id}/revoke')
    def revoke(device_id:str):
        from uuid import UUID
        try: UUID(device_id)
        except ValueError: raise ApiError(422,'设备编号无效')
        return companion.ensure_remote().call('POST','/api/devices/'+device_id+'/revoke',{})

    @app.get('/')
    def index(): return FileResponse(ROOT/'web/index.html')
    @app.get('/sw.js')
    def worker(): return FileResponse(ROOT/'web/sw.js',media_type='application/javascript')
    app.mount('/assets',StaticFiles(directory=ROOT/'web'),name='assets')
    from desktop.workbench import install_workbench
    install_workbench(app,companion,origin,ROOT)
    return app


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--data',type=Path,default=Path.home()/'.xiaoha-voice-sync')
    parser.add_argument('--history',type=Path)
    parser.add_argument('--wordbook',type=Path)
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    if platform.system()=='Darwin':
        clip=MacClipboard(ROOT/'desktop/clipboard-macos')
        prototype=ROOT.parent/'mac-prototype/private'
        args.history=args.history or (prototype/'history.json' if prototype.exists() else None)
        args.wordbook=args.wordbook or (prototype/'sync-wordbook.json' if prototype.exists() else None)
    elif platform.system()=='Windows': clip=WindowsClipboard()
    else: raise SystemExit('桌面后台组件仅支持Mac和Windows；其他设备使用浏览器入口')
    companion=Companion(args.data,clip,history_path=args.history,wordbook_path=args.wordbook)
    stop=threading.Event()
    def work():
        while not stop.wait(1):
            try: companion.cycle()
            except Exception: pass  # Status is visible locally; never log tokens/text.
    threading.Thread(target=work,daemon=True).start()
    origin='http://127.0.0.1:'+str(args.port)
    if not args.no_browser:
        import webbrowser
        threading.Timer(.8,lambda:webbrowser.open(origin)).start()
    import uvicorn
    try: uvicorn.run(create_control(companion,origin),host='127.0.0.1',port=args.port,access_log=False)
    finally: stop.set()


if __name__=='__main__': main()
