"""Offline desktop sync engine. Clipboard reads require explicit local switches."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unicodedata
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temp = path.with_suffix(path.suffix + '.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, separators=(',', ':'))
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)
    os.chmod(path, 0o600)


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return fallback


def validate_server(value: str) -> str:
    u = urlsplit(value)
    if (u.scheme not in ('https', 'http') or not u.hostname or u.username or u.password
        or u.path not in ('', '/') or u.query or u.fragment
        or (u.scheme == 'http' and u.hostname not in ('127.0.0.1', 'localhost', '::1', 'testserver'))):
        raise ValueError('服务地址需为HTTPS网址；本机预览可使用localhost或127.0.0.1')
    return value.rstrip('/')


def characters(text: str) -> int:
    # Foundation's alphanumerics includes Unicode Letters, Marks and Numbers.
    return sum(unicodedata.category(c)[0] in 'LMN' for c in text)


class ApiError(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail
        super().__init__(detail if isinstance(detail, str) else detail.get('message', '同步请求失败'))


class Remote:
    def __init__(self, server: str, token='', transport=None):
        self.server = validate_server(server)
        self.token = token
        from desktop.runtime_settings import RuntimeSettings, data_directory
        options = RuntimeSettings(data_directory()).httpx_options(self.server) if transport is None else {'trust_env':False}
        self.client = httpx.Client(base_url=self.server, timeout=12, follow_redirects=False, transport=transport, **options)

    def call(self, method, path, body=None):
        headers = {'X-Xiaoha-Native': '1'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        response = self.client.request(method, path, json=body, headers=headers)
        if response.is_redirect:
            raise ApiError(502, '服务地址发生重定向，请检查地址；不会携带会话跟随跳转')
        if not response.is_success:
            try:
                detail = response.json()['detail']
            except Exception:
                detail = '服务暂时不可用'
            raise ApiError(response.status_code, detail)
        return response.json()


class Vault:
    SERVICE = 'com.xiaoha.voice.sync'

    @staticmethod
    def key(server, account_id):
        return hashlib.sha256((server + '/' + account_id).encode()).hexdigest()

    def load(self, server, account_id):
        import keyring
        return keyring.get_password(self.SERVICE, self.key(server, account_id))

    def save(self, server, account_id, token):
        import keyring
        keyring.set_password(self.SERVICE, self.key(server, account_id), token)

    def remove(self, server, account_id):
        import keyring
        try:
            keyring.delete_password(self.SERVICE, self.key(server, account_id))
        except keyring.errors.PasswordDeleteError:
            pass


class MacClipboard:
    def __init__(self, executable: Path):
        self.executable = executable

    def read(self):
        result = subprocess.run([str(self.executable), 'read'], capture_output=True, check=True, timeout=3)
        return json.loads(result.stdout)

    def write(self, text, expected):
        data = json.dumps({'text': text, 'expected': expected}, ensure_ascii=False).encode()
        result = subprocess.run([str(self.executable), 'write'], input=data, capture_output=True, check=True, timeout=3)
        return json.loads(result.stdout)['written']


class WindowsClipboard:
    """Only Unicode text; guards against a newer local copy before writing."""
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.wintypes = ctypes, wintypes
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.user.CreateWindowExW.argtypes = [wintypes.DWORD,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD,
            ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.HWND,wintypes.HMENU,wintypes.HINSTANCE,wintypes.LPVOID]
        self.user.CreateWindowExW.restype = wintypes.HWND
        self.user.OpenClipboard.argtypes = [wintypes.HWND]
        # EmptyClipboard with a NULL owner can make SetClipboardData fail.
        self.hwnd = self.user.CreateWindowExW(0,'STATIC','XiaohaVoiceClipboard',0,0,0,0,0,None,None,None,None)
        if not self.hwnd:
            raise RuntimeError('无法建立剪贴板同步窗口')
        self.user.GetClipboardData.restype = wintypes.HANDLE
        self.user.SetClipboardData.restype = wintypes.HANDLE
        self.user.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        self.kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
        self.kernel.GlobalLock.restype = ctypes.c_void_p
        self.kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        self.kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        self.kernel.GlobalAlloc.restype = wintypes.HGLOBAL
        self.kernel.GlobalFree.argtypes = [wintypes.HGLOBAL]

    def read(self):
        if not self.user.OpenClipboard(self.hwnd):
            raise RuntimeError('剪贴板正被其他应用使用')
        try:
            revision = self.user.GetClipboardSequenceNumber()
            handle = self.user.GetClipboardData(13)
            if not handle:
                return {'revision': revision, 'text': None}
            ptr = self.kernel.GlobalLock(handle)
            if not ptr:
                raise RuntimeError('无法读取剪贴板')
            try:
                text = self.ctypes.wstring_at(ptr)
            finally:
                self.kernel.GlobalUnlock(handle)
            return {'revision': revision, 'text': text}
        finally:
            self.user.CloseClipboard()

    def write(self, text, expected):
        if not self.user.OpenClipboard(self.hwnd):
            return False
        handle = None
        try:
            if self.user.GetClipboardSequenceNumber() != expected:
                return False
            data = (text + '\0').encode('utf-16-le')
            handle = self.kernel.GlobalAlloc(0x42, len(data))
            if not handle:
                return False
            ptr = self.kernel.GlobalLock(handle)
            if not ptr:
                return False
            self.ctypes.memmove(ptr, data, len(data))
            self.kernel.GlobalUnlock(handle)
            if not self.user.EmptyClipboard():
                return False
            if not self.user.SetClipboardData(13, handle):
                return False
            handle = None  # Clipboard owns the allocated memory after success.
            return True
        finally:
            if handle:
                self.kernel.GlobalFree(handle)
            self.user.CloseClipboard()


class SyncEngine:
    def __init__(self, directory: Path, remote, identity: dict, clipboard=None, history_path=None, wordbook_path=None, clock=time.monotonic):
        self.directory, self.remote, self.identity = directory, remote, identity
        self.clipboard, self.history_path, self.wordbook_path, self.clock = clipboard, history_path, wordbook_path, clock
        self.lock = threading.RLock()
        self.path = directory / 'state.json'
        self.state = read_json(self.path, {'cursor': 0, 'items': {}, 'queue': [], 'usage_queue': {}, 'uploaded_usage': [],
            'enabled': False, 'send_clipboard': False, 'receive_clipboard': False, 'usage_sync': False})
        self.bindings_path = directory.parent.parent / 'history-account-bindings.json'
        self.bindings = read_json(self.bindings_path, {})
        self.status = '已连接；后台剪贴板默认关闭'
        self.local_baseline = None
        self.clip_candidate = None
        self.history_stamp = None
        self.history_seen = set()
        self._saved = json.dumps(self.state, sort_keys=True, ensure_ascii=False)

    def save(self):
        encoded = json.dumps(self.state, sort_keys=True, ensure_ascii=False)
        if encoded != self._saved or not self.path.exists():
            write_json(self.path, self.state)
            self._saved = encoded

    def settings(self):
        return {k: self.state[k] for k in ('enabled', 'send_clipboard', 'receive_clipboard', 'usage_sync')} | {'status': self.status, 'conflicts': [o for o in self.state['queue'] if o.get('conflict')]}

    def set_settings(self, settings):
        with self.lock:
            for k in ('enabled', 'send_clipboard', 'receive_clipboard', 'usage_sync'):
                if k in settings:
                    self.state[k] = bool(settings[k])
            self.history_stamp = None
            self.local_baseline = None
            self.clip_candidate = None
            self.save()

    def pref(self, key, fallback):
        return self.state['items'].get('preference/' + key, {}).get('value', {}).get('value', fallback)

    def queue(self, kind, item_id, value, deleted=False, base=None, source='manual'):
        key = kind + '/' + item_id
        previous = next((o for o in reversed(self.state['queue']) if o['kind'] == kind and o['id'] == item_id), None)
        if previous and previous['value'] == value and previous['deleted'] == deleted:
            return True
        if len(self.state['queue']) >= 1000:
            raise RuntimeError('离线更新已达1000项，请先完成同步；本机历史保持完整')
        op = {'operation_id': str(uuid4()), 'kind': kind, 'id': item_id,
            'base_revision': self.state['items'].get(key, {}).get('revision', 0) if base is None else base,
            'deleted': deleted, 'value': value, '_source': source}
        if previous:
            op['_after'] = previous['operation_id']
        self.state['queue'].append(op)
        self.save()
        return True

    def read_history(self):
        from desktop.history_sources import read_sources, source_characters
        values = read_sources(self.history_path)
        result = []
        for r in values:
            if self.bindings.get(r['id'], self.identity['account_id']) != self.identity['account_id']:
                continue
            created = r.get('created_at', r.get('createdAt'))
            if isinstance(created, (int, float)):
                created = datetime.fromtimestamp(978307200 + created, timezone.utc).isoformat()
            result.append({'id': r['id'], 'created_at': created, 'text': r['text'], 'seconds': float(r['seconds']),
                           'characters': source_characters(r, characters(r['text'])), 'source':r.get('source')})
        return result

    def ingest_history(self):
        if (not self.state['usage_sync'] and not self.pref('sync_dictation_text', True)) or not self.history_path or not self.history_path.exists():
            return
        from desktop.history_sources import revision
        stamp = revision(self.history_path)
        if stamp == self.history_stamp:
            return
        rows = self.read_history()
        first_scan = self.history_stamp is None
        for r in rows:
            rid = r['id']
            self.bindings.setdefault(rid, self.identity['account_id'])
            if self.state['usage_sync'] and rid not in self.state['uploaded_usage']:
                self.state['usage_queue'][rid] = {'session_id': rid, 'created_at': r['created_at'],
                    'characters': r['characters'], 'seconds': r['seconds']}
        # Link existing counts without replacing today's cloud clipboard with old dictation.
        fresh = [r for r in rows if r['id'] not in self.history_seen and r.get('source') != 'shandianshuo']
        if not first_scan and fresh and self.pref('sync_dictation_text', True):
            newest = max(fresh, key=lambda r: r['created_at'])
            self.queue('clipboard', 'current', {'text': newest['text']}, source='dictation')
        self.history_seen = {r['id'] for r in rows}
        self.history_stamp = stamp
        write_json(self.bindings_path, self.bindings)
        self.save()

    def observe_clipboard(self):
        if not self.state['send_clipboard'] or self.clipboard is None:
            return
        now = self.clock()
        value = self.clipboard.read()
        text = value['text']
        if self.local_baseline is None:
            self.local_baseline = value
            return  # Enabling sync never uploads the pre-existing clipboard silently.
        if text == self.local_baseline['text']:
            self.local_baseline = value
            self.clip_candidate = None
            return
        if text is None or len(text) > 100_000:
            self.local_baseline = value
            self.clip_candidate = None
            return
        if self.clip_candidate is None or self.clip_candidate['value'] != value:
            self.clip_candidate = {'value': value, 'since': now, 'base': self.state['items'].get('clipboard/current', {}).get('revision', 0)}
            return
        # Longer than native dictation's temporary clipboard lease (1.5 seconds).
        if now - self.clip_candidate['since'] >= 1.9:
            if self.queue('clipboard', 'current', {'text': text}, base=self.clip_candidate['base'], source='clipboard'):
                self.local_baseline = value
                self.clip_candidate = None

    def export_wordbook(self):
        if self.wordbook_path is None:
            return
        words = [v['value'] for v in self.state['items'].values() if v['kind'] == 'glossary' and not v['deleted']]
        value = {'enabled': self.pref('apply_replacements', True), 'words': words}
        if read_json(self.wordbook_path, None) != value:
            write_json(self.wordbook_path, value)

    def resolve(self, operation_id, choice):
        with self.lock:
            op = next((o for o in self.state['queue'] if o['operation_id'] == operation_id), None)
            if not op or not op.get('conflict'):
                raise ValueError('待处理更新已改变，请刷新')
            current = op['conflict'].get('current')
            if choice == 'cloud':
                if current:
                    self.state['items'][op['kind'] + '/' + op['id']] = current
                self.state['queue'] = [o for o in self.state['queue'] if not (o['kind'] == op['kind'] and o['id'] == op['id'])]
            elif choice == 'local':
                old_id = op['operation_id']
                op['base_revision'] = current['revision'] if current else 0
                op['operation_id'] = str(uuid4())
                for child in self.state['queue']:
                    if child.get('_after') == old_id:
                        child['_after'] = op['operation_id']
                del op['conflict']
            else:
                raise ValueError('处理方式无效')
            self.save()

    def sync_once(self):
        with self.lock:
            if not self.state['enabled']:
                self.status = '后台同步已暂停；没有读取剪贴板或上传本机数据'
                return None
            try:
                self.ingest_history()
                self.observe_clipboard()
                for op in list(self.state['queue']):
                    if (op.get('conflict') or op.get('_after')
                        or (op.get('_source') == 'clipboard' and not self.state['send_clipboard'])
                        or (op.get('_source') == 'dictation' and not self.pref('sync_dictation_text', True))):
                        continue
                    try:
                        ack = self.remote.call('POST', '/api/mutate', {k:v for k,v in op.items() if not k.startswith('_')})
                    except ApiError as e:
                        if e.status == 409:
                            op['conflict'] = e.detail
                            self.save()
                            continue
                        raise
                    self.state['queue'].remove(op)
                    for child in self.state['queue']:
                        if child.get('_after') == op['operation_id']:
                            child['base_revision'] = ack['revision']
                            del child['_after']
                    self.save()
                pending = list(self.state['usage_queue'].values())[:500]
                if pending and self.state['usage_sync']:
                    self.remote.call('POST', '/api/usage', {'events': pending})
                    for event in pending:
                        self.state['usage_queue'].pop(event['session_id'], None)
                        if event['session_id'] not in self.state['uploaded_usage']:
                            self.state['uploaded_usage'].append(event['session_id'])
                    self.save()
                result = self.remote.call('GET', '/api/state?since=' + str(self.state['cursor']))
                if result.get('reset'):
                    self.state['items'] = {}
                for item in result['items']:
                    self.state['items'][item['kind'] + '/' + item['id']] = item
                self.state['cursor'] = result['revision']
                shared = self.state['items'].get('clipboard/current')
                if shared and shared['device_id'] == self.identity['device_id']:
                    self.state['received_clipboard_revision'] = shared['revision']
                can_receive = (shared and shared['revision'] > self.state.get('received_clipboard_revision',0) and shared['device_id'] != self.identity['device_id']
                    and self.state['receive_clipboard'] and self.clipboard and self.clip_candidate is None
                    and not any(o['kind'] == 'clipboard' for o in self.state['queue']))
                if can_receive:
                    current = self.clipboard.read()
                    # Never overwrite a new local copy that has not passed the debounce yet.
                    safe = not self.state['send_clipboard'] or self.local_baseline is None or current == self.local_baseline
                    if safe and self.clipboard.write(shared['value']['text'], current['revision']):
                        self.local_baseline = self.clipboard.read()
                        self.state['received_clipboard_revision'] = shared['revision']
                self.export_wordbook()
                self.save()
                self.status = '有冲突待处理，双方内容均保留' if any(o.get('conflict') for o in self.state['queue']) else '已同步'
                return result
            except ApiError as e:
                self.status = '登录失效，请重新登录' if e.status == 401 else str(e)
                raise
            except (httpx.HTTPError, OSError, RuntimeError, ValueError):
                self.status = '暂时离线；待同步内容保留在本机'
                raise
