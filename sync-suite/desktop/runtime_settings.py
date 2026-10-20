"""Local delivery, proxy and diagnostic settings. No system proxy mutation."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import getproxies, proxy_bypass
from desktop.client import read_json, write_json

DEFAULT = {'auto_paste':True, 'keep_transcription':True, 'proxy_mode':'system', 'proxy_url':'', 'logs_enabled':True}
def data_directory():
    return Path(os.environ.get('XH_VOICE_DATA') or Path(__file__).resolve().parents[2]/'mac-prototype/private')
class RuntimeSettings:
    def __init__(self, directory): self.directory=Path(directory);self.path=self.directory/'runtime-settings.json'
    def load(self): return {**DEFAULT, **read_json(self.path,{})}
    def save(self, value):
        if not isinstance(value,dict) or set(value)!=set(DEFAULT) or any(type(value[k]) is not bool for k in ('auto_paste','keep_transcription','logs_enabled')) or value['proxy_mode'] not in ('system','direct','manual'):
            raise ValueError('请检查粘贴、网络和日志设置')
        proxy=value['proxy_url']
        if not isinstance(proxy,str) or len(proxy)>2048: raise ValueError('代理地址格式无效')
        proxy=proxy.strip()
        if proxy:
            try:
                u=urlsplit(proxy)
                if u.scheme not in ('http','https','socks5','socks5h') or not u.hostname or not u.port or u.username or u.password or u.path not in ('','/') or u.query or u.fragment: raise ValueError()
            except ValueError: raise ValueError('代理需为 http(s)://主机:端口 或 socks5://主机:端口；此版本不保存代理密码')
        if value['proxy_mode']=='manual' and not proxy: raise ValueError('请填写手动代理地址')
        result={**value,'proxy_url':proxy};write_json(self.path,result);return result
    def websocket_proxy(self):
        v=self.load();return True if v['proxy_mode']=='system' else None if v['proxy_mode']=='direct' else v['proxy_url']
    def httpx_options(self, url='https://frontier-audio-ime-ws.doubao.com/'):
        v=self.load();result={'trust_env':v['proxy_mode']=='system'}
        if v['proxy_mode']=='manual':result['proxy']=v['proxy_url']
        elif v['proxy_mode']=='system':
            target=urlsplit(url);proxies=getproxies()
            if target.hostname and not proxy_bypass(target.hostname):
                proxy=proxies.get(target.scheme) or proxies.get('all')
                if proxy:result['proxy']=proxy
        return result
    def requests_options(self):
        v=self.load();return v['proxy_mode']=='system',({'http':v['proxy_url'],'https':v['proxy_url']} if v['proxy_mode']=='manual' else {})
