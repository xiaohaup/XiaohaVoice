"""Account-scoped sync. No endpoint accepts audio or full dictation history."""
from __future__ import annotations

import base64
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

ROOT = Path(__file__).resolve().parent.parent
COOKIE = 'xh_sync_session'
SESSION_SECONDS = 30 * 24 * 3600
MAX_BODY = 1_048_576
PREFS = {'theme': ('mint', 'ink', 'cocoa'), 'text_size': ('normal', 'large'),
         'apply_replacements': (True, False), 'sync_dictation_text': (True, False)}


@dataclass
class Config:
    data_dir: Path
    origin: str = 'http://127.0.0.1:8765'
    allow_signup: bool = False
    signup_code: str = ''

    def __post_init__(self):
        u = urlsplit(self.origin)
        if u.scheme not in ('https', 'http') or not u.hostname or u.path not in ('', '/') or u.username or u.query or u.fragment:
            raise ValueError('PUBLIC_ORIGIN must be an exact origin')
        if u.scheme == 'http' and u.hostname not in ('127.0.0.1', 'localhost', '::1', 'testserver'):
            raise ValueError('Non-loopback deployments require HTTPS')
        self.origin = self.origin.rstrip('/')
        if self.allow_signup and u.scheme == 'https' and len(self.signup_code) < 20:
            raise ValueError('Internet registration requires an invitation code of at least 20 characters')


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)


class Store:
    def __init__(self, config: Config):
        self.config = config
        config.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(config.data_dir, 0o700)
        key_path = config.data_dir / 'master.key'
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'wb') as f:
                f.write(secrets.token_bytes(32))
        os.chmod(key_path, 0o600)
        key = key_path.read_bytes()
        if len(key) != 32:
            raise RuntimeError('Invalid server encryption key; preserve data and restore the original key')
        self.aes = AESGCM(key)
        self.csrf_key = hashlib.sha256(key + b'csrf-v1').digest()
        self.path = config.data_dir / 'sync.sqlite3'
        self.lock = threading.RLock()
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
              salt BLOB NOT NULL, password BLOB NOT NULL, revision INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS devices(account_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL,
              platform TEXT NOT NULL, seen REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY(account_id,id));
            CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL,
              device_id TEXT NOT NULL, csrf_hash TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS items(account_id TEXT NOT NULL, kind TEXT NOT NULL, item_id TEXT NOT NULL,
              revision INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0, payload BLOB NOT NULL,
              source_device TEXT NOT NULL, updated REAL NOT NULL, PRIMARY KEY(account_id,kind,item_id));
            CREATE TABLE IF NOT EXISTS operations(account_id TEXT NOT NULL, operation_id TEXT NOT NULL,
              device_id TEXT NOT NULL, request_hash TEXT NOT NULL, result_revision INTEGER NOT NULL,
              PRIMARY KEY(account_id,operation_id));
            CREATE TABLE IF NOT EXISTS usage(account_id TEXT NOT NULL, session_id TEXT NOT NULL,
              device_id TEXT NOT NULL, created_at TEXT NOT NULL, characters INTEGER NOT NULL,
              seconds REAL NOT NULL, PRIMARY KEY(account_id,session_id));
            CREATE INDEX IF NOT EXISTS item_changes ON items(account_id,revision);
            CREATE INDEX IF NOT EXISTS usage_device ON usage(account_id,device_id);
            ''')
        os.chmod(self.path, 0o600)

    @contextmanager
    def db(self):
        with self.lock:
            con = sqlite3.connect(self.path, timeout=10)
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA journal_mode=WAL')
            try:
                con.execute('BEGIN IMMEDIATE')
                yield con
                con.commit()
            except Exception:
                con.rollback()
                raise
            finally:
                con.close()

    def encrypt(self, account: str, kind: str, item_id: str, value: dict) -> bytes:
        nonce = secrets.token_bytes(12)
        aad = f'{account}/{kind}/{item_id}'.encode()
        return nonce + self.aes.encrypt(nonce, json.dumps(value, ensure_ascii=False).encode(), aad)

    def csrf(self, token: str) -> str:
        return hmac.new(self.csrf_key, token.encode(), hashlib.sha256).hexdigest()

    def item(self, row) -> dict:
        aad = f'{row["account_id"]}/{row["kind"]}/{row["item_id"]}'.encode()
        payload = row['payload']
        value = json.loads(self.aes.decrypt(payload[:12], payload[12:], aad))
        return {'kind': row['kind'], 'id': row['item_id'], 'revision': row['revision'],
                'deleted': bool(row['deleted']), 'value': value, 'device_id': row['source_device'],
                'updated_at': row['updated']}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)


class Login(StrictModel):
    username: str = Field(min_length=3, max_length=64, pattern=r'^[A-Za-z0-9_.@-]+$')
    password: str = Field(min_length=12, max_length=256)
    device_id: UUID
    device_name: str = Field(min_length=1, max_length=80)
    platform: Literal['Mac', 'Windows', 'iPhone', 'iPad', 'Android', 'Web']
    invite: str = Field(default='', max_length=256)


class Mutation(StrictModel):
    operation_id: UUID
    kind: Literal['clipboard', 'glossary', 'preference']
    id: str = Field(min_length=1, max_length=80)
    base_revision: int = Field(ge=0)
    deleted: bool = False
    value: dict

    @field_validator('value')
    @classmethod
    def bounded_value(cls, v):
        if len(json.dumps(v, ensure_ascii=False).encode()) > 500_000:
            raise ValueError('value too large')
        return v


class UsageEvent(StrictModel):
    session_id: UUID
    created_at: datetime
    characters: int = Field(ge=0, le=1_000_000, strict=True)
    seconds: float = Field(ge=0, le=86400, allow_inf_nan=False)

    @field_validator('created_at')
    @classmethod
    def aware(cls, v):
        if v.tzinfo is None:
            raise ValueError('timezone required')
        return v.astimezone(timezone.utc)


class UsageBatch(StrictModel):
    events: list[UsageEvent] = Field(max_length=500)


class Limiter:
    def __init__(self):
        self.rows = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, key: str, limit: int = 20):
        now = time.monotonic()
        with self.lock:
            if len(self.rows) > 4096:
                self.rows = defaultdict(deque, {k: v for k, v in self.rows.items() if v and now - v[-1] < 300})
                if len(self.rows) > 4096:
                    raise HTTPException(429, '请求较多，请稍后重试')
            row = self.rows[key]
            while row and row[0] < now - 300:
                row.popleft()
            if len(row) >= limit:
                raise HTTPException(429, '尝试较多，请五分钟后重试')
            row.append(now)


def validate_mutation(m: Mutation):
    v = m.value
    if m.kind == 'clipboard':
        if m.id != 'current' or m.deleted or set(v) != {'text'} or not isinstance(v['text'], str) or len(v['text']) > 100_000:
            raise HTTPException(422, '当前文字格式无效')
    elif m.kind == 'glossary':
        try:
            UUID(m.id)
        except ValueError:
            raise HTTPException(422, '词条编号无效')
        if m.deleted:
            if v:
                raise HTTPException(422, '删除词条不携带正文')
        elif (set(v) != {'term', 'aliases'} or not isinstance(v['term'], str) or not 1 <= len(v['term'].strip()) <= 100
              or not isinstance(v['aliases'], list) or len(v['aliases']) > 20
              or any(not isinstance(a, str) or not 1 <= len(a.strip()) <= 100 for a in v['aliases'])):
            raise HTTPException(422, '词条格式无效')
    else:
        if m.id not in PREFS or m.deleted or set(v) != {'value'} or v['value'] not in PREFS[m.id] or type(v['value']) is not type(PREFS[m.id][0]):
            raise HTTPException(422, '偏好格式无效或属于本设备设置')


def create_app(config: Config | None = None):
    cfg = config or Config(Path(os.getenv('XH_DATA_DIR', str(ROOT / 'private/server'))),
        os.getenv('PUBLIC_ORIGIN', 'http://127.0.0.1:8765'),
        os.getenv('ALLOW_SIGNUP', '') == '1', os.getenv('SIGNUP_CODE', ''))
    store = Store(cfg)
    limiter = Limiter()
    app = FastAPI(title='小哈语音同步', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(cfg.origin).hostname])

    @app.middleware('http')
    async def boundary(request: Request, call_next):
        if request.url.path.startswith('/api/'):
            if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                if 'application/json' not in request.headers.get('content-type', ''):
                    return JSONResponse({'detail': '需要JSON请求'}, status_code=415)
                native = request.headers.get('authorization', '').startswith('Bearer ') or request.headers.get('x-xiaoha-native') == '1'
                origin = request.headers.get('origin')
                if (origin is not None and origin != cfg.origin) or (not native and origin != cfg.origin):
                    return JSONResponse({'detail': '请求来源不匹配'}, status_code=403)
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > MAX_BODY:
                        return JSONResponse({'detail': '内容过大'}, status_code=413)
                request._body = bytes(body)
            response = await call_next(request)
            response.headers['Cache-Control'] = 'no-store'
        else:
            response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    def auth(request: Request):
        header = request.headers.get('authorization', '')
        bearer = header.startswith('Bearer ')
        raw = header[7:] if bearer else request.cookies.get(COOKIE, '')
        if not raw or len(raw) > 256:
            raise HTTPException(401, '请重新登录')
        with store.db() as db:
            row = db.execute('''SELECT s.*,a.username FROM sessions s JOIN accounts a ON a.id=s.account_id
              JOIN devices d ON d.account_id=s.account_id AND d.id=s.device_id
              WHERE s.token_hash=? AND s.expires>? AND d.revoked=0''', (digest(raw), time.time())).fetchone()
            if row is None:
                raise HTTPException(401, '登录已失效，请重新登录')
            result = dict(row)
        if request.method != 'GET' and not bearer:
            if not hmac.compare_digest(result['csrf_hash'], digest(request.headers.get('x-csrf-token', ''))):
                raise HTTPException(403, '页面已过期，请刷新后重试')
        return result

    def browser_origin(request: Request):
        # Native login is explicit and never leaks its token into browser storage.
        return request.headers.get('x-xiaoha-native') == '1' and not request.headers.get('origin')

    def issue(db, model: Login, account, request: Request, response: Response):
        did = str(model.device_id)
        db.execute('''INSERT INTO devices VALUES(?,?,?,?,?,0) ON CONFLICT(account_id,id)
            DO UPDATE SET name=excluded.name,platform=excluded.platform,seen=excluded.seen,revoked=0''',
            (account['id'], did, model.device_name, model.platform, time.time()))
        token = secrets.token_urlsafe(32)
        csrf = store.csrf(token)
        db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
        db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)', (digest(token), account['id'], did, digest(csrf), time.time() + SESSION_SECONDS))
        response.set_cookie(COOKIE, token, httponly=True, secure=cfg.origin.startswith('https:'), samesite='strict', max_age=SESSION_SECONDS, path='/api/')
        value = {'account_id': account['id'], 'username': account['username'], 'device_id': did, 'csrf': csrf}
        if browser_origin(request):
            value['token'] = token
        return value

    @app.get('/api/health')
    def health():
        return {'ok': True, 'version': '0.2.0', 'signup_enabled': cfg.allow_signup,
                'local_only': cfg.origin.startswith(('http://127.', 'http://localhost', 'http://testserver'))}

    @app.post('/api/register')
    def register(model: Login, request: Request, response: Response):
        limiter.check('register:' + str(request.client.host), 8)
        if not cfg.allow_signup:
            raise HTTPException(403, '当前服务未开放注册')
        if cfg.signup_code and not hmac.compare_digest(cfg.signup_code, model.invite):
            raise HTTPException(403, '邀请码不正确')
        salt = secrets.token_bytes(16)
        hashed = password_hash(model.password, salt)
        username = model.username.lower()
        with store.db() as db:
            try:
                db.execute('INSERT INTO accounts(id,username,salt,password) VALUES(?,?,?,?)', (str(uuid4()), username, salt, hashed))
            except sqlite3.IntegrityError:
                raise HTTPException(409, '账号已存在，请登录')
            account = db.execute('SELECT * FROM accounts WHERE username=?', (username,)).fetchone()
            return issue(db, model, account, request, response)

    @app.post('/api/login')
    def login(model: Login, request: Request, response: Response):
        limiter.check('login-ip:' + str(request.client.host), 60)
        limiter.check('login:' + str(request.client.host) + ':' + model.username.lower())
        with store.db() as db:
            account = db.execute('SELECT * FROM accounts WHERE username=?', (model.username.lower(),)).fetchone()
        salt = account['salt'] if account else b'no-account-salt!'
        calculated = password_hash(model.password, salt)
        if account is None or not hmac.compare_digest(account['password'], calculated):
            raise HTTPException(401, '账号或密码不正确')
        with store.db() as db:
            return issue(db, model, account, request, response)

    @app.get('/api/me')
    def me(request: Request, session=Depends(auth)):
        # Stable per session: another browser tab must not invalidate queued edits.
        header = request.headers.get('authorization', '')
        raw = header[7:] if header.startswith('Bearer ') else request.cookies.get(COOKIE, '')
        csrf = store.csrf(raw)
        return {'account_id': session['account_id'], 'username': session['username'], 'device_id': session['device_id'], 'csrf': csrf}

    @app.post('/api/logout')
    def logout(response: Response, session=Depends(auth)):
        with store.db() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (session['token_hash'],))
        response.delete_cookie(COOKIE, path='/api/')
        return {'ok': True}

    @app.get('/api/state')
    def state(since: int = 0, session=Depends(auth)):
        if since < 0:
            raise HTTPException(422, '游标无效')
        with store.db() as db:
            uid = session['account_id']
            revision = db.execute('SELECT revision FROM accounts WHERE id=?', (uid,)).fetchone()[0]
            reset = since > revision
            rows = db.execute('SELECT * FROM items WHERE account_id=? AND revision>? ORDER BY revision', (uid, 0 if reset else since)).fetchall()
            devices = [dict(r) for r in db.execute('SELECT id,name,platform,seen,revoked FROM devices WHERE account_id=? ORDER BY seen DESC', (uid,))]
            usage = [dict(r) for r in db.execute('''SELECT device_id,COUNT(*) AS sessions,COALESCE(SUM(characters),0) AS characters,
                COALESCE(SUM(seconds),0) AS seconds FROM usage WHERE account_id=? GROUP BY device_id''', (uid,))]
            total = {'sessions': sum(r['sessions'] for r in usage), 'characters': sum(r['characters'] for r in usage), 'seconds': sum(r['seconds'] for r in usage)}
            return {'revision': revision, 'reset': reset, 'items': [store.item(r) for r in rows], 'devices': devices, 'usage_by_device': usage, 'usage_total': total}

    @app.post('/api/mutate')
    def mutate(model: Mutation, session=Depends(auth)):
        validate_mutation(model)
        uid, did, oid = session['account_id'], session['device_id'], str(model.operation_id)
        encoded = json.dumps(model.model_dump(mode='json'), sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        request_hash = digest(encoded)
        with store.db() as db:
            prior = db.execute('SELECT * FROM operations WHERE account_id=? AND operation_id=?', (uid, oid)).fetchone()
            if prior:
                if prior['request_hash'] != request_hash or prior['device_id'] != did:
                    raise HTTPException(409, '重复编号对应了不同操作')
                return {'ok': True, 'revision': prior['result_revision'], 'duplicate': True}
            old = db.execute('SELECT * FROM items WHERE account_id=? AND kind=? AND item_id=?', (uid, model.kind, model.id)).fetchone()
            if (old['revision'] if old else 0) != model.base_revision:
                raise HTTPException(409, {'message': '另一设备已更新，请选择保留哪一份', 'current': store.item(old) if old else None})
            revision = db.execute('UPDATE accounts SET revision=revision+1 WHERE id=? RETURNING revision', (uid,)).fetchone()[0]
            db.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(account_id,kind,item_id) DO UPDATE SET revision=excluded.revision,deleted=excluded.deleted,payload=excluded.payload,source_device=excluded.source_device,updated=excluded.updated',
                (uid, model.kind, model.id, revision, int(model.deleted), store.encrypt(uid, model.kind, model.id, model.value), did, time.time()))
            db.execute('INSERT INTO operations VALUES(?,?,?,?,?)', (uid, oid, did, request_hash, revision))
            return {'ok': True, 'revision': revision, 'duplicate': False}

    @app.post('/api/usage')
    def usage(model: UsageBatch, session=Depends(auth)):
        with store.db() as db:
            for event in model.events:
                uid, sid = session['account_id'], str(event.session_id)
                value = (session['device_id'], event.created_at.isoformat(), event.characters, event.seconds)
                old = db.execute('SELECT device_id,created_at,characters,seconds FROM usage WHERE account_id=? AND session_id=?', (uid, sid)).fetchone()
                if old and tuple(old) != value:
                    raise HTTPException(409, '同一次录音的统计已经存在，拒绝重复或改写')
                if old is None:
                    db.execute('INSERT INTO usage VALUES(?,?,?,?,?,?)', (uid, sid, *value))
        return {'ok': True, 'accepted': len(model.events)}

    @app.post('/api/devices/{device_id}/revoke')
    def revoke(device_id: UUID, session=Depends(auth)):
        with store.db() as db:
            uid, did = session['account_id'], str(device_id)
            db.execute('UPDATE devices SET revoked=1 WHERE account_id=? AND id=?', (uid, did))
            db.execute('DELETE FROM sessions WHERE account_id=? AND device_id=?', (uid, did))
        return {'ok': True}

    @app.get('/')
    def index():
        return FileResponse(ROOT / 'web/index.html', headers={'Cache-Control': 'no-cache'})

    @app.get('/sw.js')
    def worker():
        return FileResponse(ROOT / 'web/sw.js', media_type='application/javascript', headers={'Cache-Control': 'no-cache'})

    app.mount('/assets', StaticFiles(directory=ROOT / 'web'), name='assets')
    return app
