"""Text-only requests to the toolkit's existing local credential owner."""
from __future__ import annotations
import hashlib,http.client,json,socket,threading
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

class LocalEnglishClient:
    def __init__(self,origin,directory):
        u=urlsplit(origin)
        if u.scheme!='http' or u.hostname!='127.0.0.1' or not u.port or u.path not in ('','/') or u.query or u.fragment or u.username:
            raise ValueError('本机翻译服务地址无效')
        self.host=u.hostname;self.port=u.port;self.origin=f'http://127.0.0.1:{u.port}'
        self.directory=Path(directory);self.cancelled=threading.Event();self.lock=threading.Lock();self.connection=None
    def cancel(self):
        self.cancelled.set()
        with self.lock:
            c=self.connection
            if c:
                try:
                    if c.sock:c.sock.shutdown(socket.SHUT_RDWR)
                except OSError:pass
                c.close()
    def request(self,path,body=None,cookie='',csrf=''):
        if self.cancelled.is_set():raise ValueError('翻译已取消，原文已保留')
        headers={};payload=None
        if cookie:headers['Cookie']=cookie
        if body is not None:
            payload=json.dumps(body,ensure_ascii=False).encode('utf-8');headers.update({'Origin':self.origin,'X-CSRF-Token':csrf,'Content-Type':'application/json'})
        c=http.client.HTTPConnection(self.host,self.port,timeout=24 if body is not None else 3)
        with self.lock:
            if self.cancelled.is_set():raise ValueError('翻译已取消，原文已保留')
            self.connection=c
        try:
            c.request('GET' if body is None else 'POST',path,body=payload,headers=headers)
            response=c.getresponse();data=response.read(310001)
            if response.status!=200:raise ValueError('本机翻译服务暂不可用，原文已保留')
            if len(data)>310000:raise ValueError('翻译返回内容过大，原文已保留')
            if self.cancelled.is_set():raise ValueError('翻译已取消，原文已保留')
            return data,dict(response.getheaders())
        finally:
            c.close()
            with self.lock:
                if self.connection is c:self.connection=None
    def translate(self,text,revision):
        if not isinstance(text,str) or not text.strip() or len(text.encode('utf-8'))>50000:raise ValueError('翻译内容为空或过长')
        try:
            health=json.loads(self.request('/api/health')[0])
            expected=hashlib.sha256(str(self.directory.resolve()).encode()).hexdigest()
            if health.get('service')!='xiaoha-voice-companion' or health.get('protocol')!=3 or health.get('instance')!=expected:
                raise ValueError('本机翻译服务身份不匹配，原文已保留')
            _,headers=self.request('/workbench');cookies=SimpleCookie();cookies.load(next((v for k,v in headers.items() if k.lower()=='set-cookie'),''))
            value=cookies.get('xh_workbench')
            if not value:raise ValueError('本机翻译会话未就绪')
            cookie='xh_workbench='+value.value
            status=json.loads(self.request('/workbench/api/status',cookie=cookie)[0]);csrf=status.get('csrf')
            if not isinstance(csrf,str) or not csrf or len(csrf)>200 or any(ord(c)<33 or ord(c)>126 for c in csrf):raise ValueError('本机翻译会话无效')
            result=json.loads(self.request('/workbench/api/translation-run',{'text':text,'revision':revision},cookie,csrf)[0])
            if result.get('ok') is not True:raise ValueError(str(result.get('error') or '英文翻译未完成，原文已保留')[:500])
            translated=result.get('text')
            if not isinstance(translated,str) or not translated.strip() or len(translated.encode('utf-8'))>50000:raise ValueError('翻译没有返回有效文字')
            return {'ok':True,'text':translated,'milliseconds':result.get('milliseconds',0)}
        except ValueError:raise
        except Exception:raise ValueError('本机翻译连接未完成或已取消，原文已保留')
