"""Exercise a packaged owner against an owned loopback translator + null vault.
Does not launch the GUI, open a mic, send OS keys, read installed Data or use a Key.
"""
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import argparse,hashlib,http.cookiejar,json,os,socket,subprocess,tempfile,threading,time,urllib.request


def main():
    p=argparse.ArgumentParser();p.add_argument('toolkit',type=Path);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    root=a.toolkit.resolve();a.report.parent.mkdir(parents=True,exist_ok=True);requests=[]
    class API(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            assert self.path=='/v1/chat/completions' and self.headers['Authorization']=='Bearer synthetic-preview-key'
            value=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(value)
            assert set(value)=={'model','messages','stream'} and value['model']=='fixture-model'
            body=json.dumps({'choices':[{'message':{'content':'Meet Claude tomorrow.'}}]}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),API);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='packaged-translation-',dir=a.report.parent) as temporary:
            temp=Path(temporary);data=temp/'Data';data.mkdir();desktop=data/'desktop';desktop.mkdir();history=data/'history.json';history.write_text('[]')
            with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            origin=f'http://127.0.0.1:{port}'
            runtime=root/('Runtime/xiaoha-runtime/xiaoha-runtime.exe' if os.name=='nt' else 'Runtime/xiaoha-runtime/xiaoha-runtime')
            env={**os.environ,'XH_VOICE_DATA':str(data),'XH_VOICE_IDENTITY':str(data/'recognition'),'XH_VOICE_ENGINE':str(root/'Components/engine'),
                 'XH_VOICE_WORKBENCH':str(root/'Components/workbench'),'PYTHON_KEYRING_BACKEND':'keyring.backends.null.Keyring'}
            log=temp/'runtime.log'
            with log.open('w') as output:
                process=subprocess.Popen([str(runtime),'control','--no-browser','--port',str(port),'--data',str(desktop),'--history',str(history)],env=env,stdout=output,stderr=output)
                try:
                    jar=http.cookiejar.CookieJar();client=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(jar))
                    def call(path,body=None,csrf=None):
                        headers={}
                        if body is not None:headers={'Origin':origin,'X-CSRF-Token':csrf or '', 'Content-Type':'application/json'}
                        req=urllib.request.Request(origin+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
                        with client.open(req,timeout=5) as response:return response.read()
                    deadline=time.monotonic()+30
                    while True:
                        try:health=json.loads(call('/api/health'));break
                        except Exception:
                            if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Packaged owner failed to start; inspect isolated runtime log')
                            time.sleep(.1)
                    assert health['protocol']==3 and health['instance']==hashlib.sha256(str(desktop.resolve()).encode()).hexdigest()
                    html=call('/workbench').decode();assert 'id="voice-english-form"' in html
                    csrf=json.loads(call('/workbench/api/status'))['csrf']
                    saved=json.loads(call('/workbench/api/translation',{'enabled':True,'endpoint':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture-model','credential':'synthetic-preview-key'},csrf))
                    assert saved['credential_saved'] and 'credential' not in saved
                    tested=json.loads(call('/workbench/api/translation-test',{'revision':saved['revision']},csrf));assert tested['ok']
                    for _ in range(2):
                        translated=json.loads(call('/workbench/api/translation-run',{'text':'明天与 Claude 开会。','revision':saved['revision']},csrf));assert translated['ok'] and translated['text']=='Meet Claude tomorrow.'
                    info=json.loads(call('/workbench/api/translation-session'));assert info=={'ready':True,'vault_reads':0,'cache_hits':3}
                    assert 'synthetic-preview-key' not in (data/'translation-settings.json').read_text()
                    assert len(requests)==3 and all(r['stream'] is False for r in requests)
                    result={'passed':True,'packaged_owner':True,'translation_requests':3,'credential_session':info,'personal_key_used':False,'external_service_called':False,'gui_launched':False,'microphone_opened':False,'os_keys_posted':False}
                finally:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            assert 'synthetic-preview-key' not in log.read_text(encoding='utf-8')
            a.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(result))
    finally:server.shutdown();server.server_close();thread.join(2)


if __name__=='__main__':main()
