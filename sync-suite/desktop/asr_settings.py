"""ASR configuration; credentials live in the OS credential vault, never JSON."""
from desktop.client import read_json, write_json
from datetime import datetime, timezone
import threading
import uuid

SERVICE = 'com.xiaoha.voice.asr'
ACCOUNT = 'volcengine-streaming'
DEFAULT = {'provider': 'ime', 'auth': 'api_key', 'app_id': '', 'resource': 'volc.seedasr.sauc.duration', 'second_pass': True, 'diagnostics': False}
RESOURCES = ('volc.seedasr.sauc.duration', 'volc.seedasr.sauc.concurrent')

class ASRSettings:
    def __init__(self, path, vault=None):
        self.path = path
        if vault is None:
            import keyring
            vault = keyring
        self.vault = vault
        self.lock = threading.RLock()
    def config(self): return {**DEFAULT, **read_json(self.path, {})}
    @staticmethod
    def test_results(value):
        tests={p:dict(v) for p,v in value.get('test_results',{}).items() if p in ('ime','volcengine') and isinstance(v,dict)}
        # Older versions stored only the current provider's results at the top level.
        for kind in ('connection_test','speed_test'):
            result=value.get(kind)
            if isinstance(result,dict):
                provider=result.get('provider') or ('volcengine' if result.get('backend')=='volcengine_2' or result.get('check')=='websocket_handshake' else value.get('provider','ime'))
                tests.setdefault(provider,{})[kind]=result
        return tests
    def public(self):
        value = self.config()
        tests=self.test_results(value)
        for kind in ('connection_test','speed_test'): value.pop(kind,None)
        value['test_results']=tests
        value.update(tests.get(value['provider'],{}))
        # Reading the config page must not itself prompt for Keychain access.
        value['credential_saved'] = bool(value.pop('credential_saved', False))
        return value
    def save(self, value):
        with self.lock:
            return self._save(value)
    def _save(self, value):
        current = self.config()
        if value.get('provider') not in ('ime', 'volcengine') or value.get('auth') not in ('api_key', 'legacy') or value.get('resource') not in RESOURCES:
            raise ValueError('请检查识别通道与2.0资源类型')
        if any(type(value.get(k)) is not bool for k in ('second_pass','diagnostics')): raise ValueError('开关格式无效')
        app = value.get('app_id', '')
        if not isinstance(app,str): raise ValueError('App ID格式无效')
        app = app.strip(); credential = value.get('credential', '')
        if len(app)>100 or not isinstance(credential,str) or len(credential)>4096 or '\n' in credential or '\r' in credential:
            raise ValueError('凭证格式无效')
        saved = current.get('credential_saved', False)
        if value['auth']=='legacy' and not app and (value['provider']=='volcengine' or credential):
            raise ValueError('旧版认证需要 App ID，当前配置与凭证没有改变')
        if value['provider']=='volcengine' and not (saved or credential):
            raise ValueError('正式API尚未配置完整，当前通道没有切换')
        if credential:
            try: self.vault.set_password(SERVICE, ACCOUNT, credential)
            except Exception: raise ValueError('系统安全存储未能保存，请完成系统验证后重试')
            saved = True
        result = {k: value[k] for k in ('provider','auth','resource','second_pass','diagnostics')}
        result.update(app_id=app, credential_saved=saved)
        result['saved_at'] = datetime.now(timezone.utc).isoformat()
        result['revision'] = uuid.uuid4().hex
        tests=self.test_results(current)
        if credential or any(result[k]!=current.get(k) for k in ('auth','app_id','resource','second_pass')):
            tests.pop('volcengine',None)
        result['test_results']=tests
        write_json(self.path, result)
        return self.public()
    def test_config(self):
        with self.lock:
            value = self.config()
            # API credentials are independent of the active recording provider.
            # Callers only use this for an explicit API test or credential reveal.
        # A system permission dialog can wait; it must not lock configuration saves.
        try: credential = self.vault.get_password(SERVICE, ACCOUNT)
        except Exception: raise ValueError('未能读取系统钥匙串，请完成系统验证后再测试')
        if not credential: raise ValueError('未找到已保存凭证，请重新填写并保存')
        return value, credential
    def record_test(self, revision, result, kind='connection_test', provider=None):
        if kind not in ('connection_test', 'speed_test'): raise ValueError('测试类型无效')
        with self.lock:
            value = self.config()
            if value.get('revision') != revision: return False
            provider=provider or value['provider']
            if provider not in ('ime','volcengine'): raise ValueError('测试通道无效')
            tests=self.test_results(value)
            tests.setdefault(provider,{})[kind] = {**result, 'provider':provider, 'checked_at':datetime.now(timezone.utc).isoformat()}
            for key in ('connection_test','speed_test'):value.pop(key,None)
            value['test_results']=tests
            write_json(self.path, value)
            return True
