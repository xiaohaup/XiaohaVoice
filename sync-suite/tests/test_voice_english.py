"""Synthetic text + injected transport/vault only; never reads personal keys."""
import json, threading
from pathlib import Path
import httpx,pytest
from desktop.voice_translation import TranslationSettings,DEFAULT_SHORTCUT,SERVICE,ACCOUNT,account_for,endpoint_url,shortcut_value,translate,TEST_TEXT,MAX_RESPONSE

@pytest.fixture(autouse=True)
def forbid_real_connections(monkeypatch):
    import socket
    def deny(*args,**kwargs):raise AssertionError('Unit fixture attempted a real connection')
    monkeypatch.setattr(socket,'create_connection',deny)

class Vault:
    def __init__(self):self.values={};self.reads=[]
    def set_password(self,s,a,v):self.values[(s,a)]=v
    def get_password(self,s,a):self.reads.append((s,a));return self.values.get((s,a))

@pytest.fixture
def configured(tmp_path):
    vault=Vault();s=TranslationSettings(tmp_path,vault);v=s.save({'enabled':True,'endpoint':'https://api.example.invalid/v1','model':'test-translation','shortcut':DEFAULT_SHORTCUT,'credential':'synthetic-translation-key'})
    return s,vault,v

def factory(handler):
    def create(**kwargs):
        assert kwargs['follow_redirects'] is False
        kwargs.pop('proxy',None);kwargs['trust_env']=False
        return httpx.Client(transport=httpx.MockTransport(handler),**kwargs)
    return create

def test_default_and_secure_persistence(configured):
    s,vault,v=configured
    assert not TranslationSettings(s.directory/'fresh',vault).public()['enabled']
    assert vault.reads==[] and set(vault.values)=={(SERVICE,account_for(v['endpoint']))}
    assert 'synthetic-translation-key' not in s.path.read_text() and 'credential' not in s.public()
    next=s.save({**v,'model':'next-model','credential':''})
    assert next['credential_saved'] and next['revision']!=v['revision'] and vault.reads==[]
    with pytest.raises(ValueError,match='地址已改变'):s.save({**next,'endpoint':'https://different.example.invalid','credential':''})
    assert s.public()==next
    fresh=TranslationSettings(s.directory/'fresh',vault)
    with pytest.raises(ValueError,match='服务地址'):fresh.save({**fresh.public(),'credential':'synthetic-unbound-key'})
    assert not fresh.public()['credential_saved']

def test_new_service_secret_cannot_replace_old_profile_on_disk_failure(configured,monkeypatch):
    import desktop.voice_translation as module
    s,vault,v=configured
    def failed_write(*args):raise OSError('synthetic full disk')
    monkeypatch.setattr(module,'write_json',failed_write)
    with pytest.raises(ValueError,match='未能写入'):s.save({**v,'endpoint':'https://other.example.invalid/v1','credential':'synthetic-other-service-key'})
    assert s.public()==v
    _,secret=s.credentials(v['revision']);assert secret=='synthetic-translation-key'
    assert vault.values[SERVICE,account_for('https://other.example.invalid/v1')]=='synthetic-other-service-key'

@pytest.mark.parametrize('base,expected',[
 ('https://api.example.invalid','https://api.example.invalid/v1/chat/completions'),
 ('https://ark.cn-beijing.volces.com/api/v3/','https://ark.cn-beijing.volces.com/api/v3/chat/completions'),
 ('http://127.0.0.1:8192/v1','http://127.0.0.1:8192/v1/chat/completions'),
 ('http://[::1]:8192/chat/completions','http://[::1]:8192/chat/completions'),
 ('https://api.example.invalid/chat/completions','https://api.example.invalid/chat/completions')])
def test_endpoint_normalizes(base,expected):assert endpoint_url(base)==expected

@pytest.mark.parametrize('url',['http://api.example.invalid','file:///tmp/key','https://user:key@api.example.invalid','https://api.example.invalid?key=x','https://api.example.invalid/#x','https://api.example.invalid/\nkey','https://api.example.invalid:bad','https:///bad'])
def test_endpoint_rejects(url):
    with pytest.raises(ValueError):endpoint_url(url)

def test_corrected_source_is_only_input(configured):
    s,vault,v=configured;seen=[]
    def handler(req):
        body=json.loads(req.content);seen.append(body)
        assert body['messages'][1]['content']=='明天和 Claude 开会。'
        assert req.headers['Authorization']=='Bearer synthetic-translation-key'
        assert body['stream'] is False and 'audio' not in body
        return httpx.Response(200,json={'choices':[{'message':{'content':'Meet Claude tomorrow.'}}]})
    result=translate('明天和 Claude 开会。',v['revision'],s,factory(handler))
    assert result['text']=='Meet Claude tomorrow.' and result['target']=='en' and result['milliseconds']>=0
    assert len(seen)==1 and vault.reads==[] and s.session_info()=={'ready':True,'vault_reads':0,'cache_hits':1}

@pytest.mark.parametrize('endpoint,model,disable',[
 ('https://ark.cn-beijing.volces.com/api/v3','doubao-seed-2-1-lite-260915',True),
 ('https://ark.cn-beijing.volces.com/api/v3','doubao-seed-2-1-turbo-260628',True),
 ('https://ark.cn-beijing.volces.com:443/api/v3','doubao-seed-2-1-pro-260915',True),
 ('https://api.example.invalid/v1','doubao-seed-2-1-lite-260915',False),
 ('https://ark.cn-beijing.volces.com.evil.invalid/api/v3','doubao-seed-2-1-lite-260915',False),
 ('https://ark.cn-beijing.volces.com:444/api/v3','doubao-seed-2-1-lite-260915',False),
 ('https://ark.cn-beijing.volces.com/custom','doubao-seed-2-1-lite-260915',False),
 ('https://ark.cn-beijing.volces.com/api/v3','ep-custom-model',False),
 ('https://ark.cn-beijing.volces.com/api/v3','another-model',False)])
def test_ark_direct_translation_disables_thinking_only_for_known_models(configured,endpoint,model,disable):
    s,vault,v=configured
    v=s.save({**v,'endpoint':endpoint,'model':model,'credential':'synthetic-translation-key'})
    requests=[]
    def handler(req):
        requests.append(req);body=json.loads(req.content)
        assert body['messages'][1]['content']==TEST_TEXT
        assert body['model']==model and body['stream'] is False
        assert ('thinking' in body)==disable
        if disable:assert body['thinking']=={'type':'disabled'}
        return httpx.Response(200,json={'choices':[{'message':{'content':'Meet tomorrow at ten.'}}]})
    assert translate(TEST_TEXT,v['revision'],s,factory(handler))['text']=='Meet tomorrow at ten.'
    assert len(requests)==1

@pytest.mark.parametrize('suffix',['/responses','/responses/chat/completions'])
def test_responses_url_rejected_before_changing_config_or_key(configured,suffix):
    s,vault,v=configured;before=dict(vault.values)
    with pytest.raises(ValueError,match='不要填写 /responses'):
        s.save({**v,'endpoint':'https://ark.cn-beijing.volces.com/api/v3'+suffix,'credential':'synthetic-new-key'})
    assert s.public()==v and vault.values==before and vault.reads==[]

@pytest.mark.parametrize('error,message',[(httpx.ConnectTimeout,'连接超时'),(httpx.ReadTimeout,'等待翻译结果超时'),(httpx.WriteTimeout,'传输超时')])
def test_timeout_phase_is_distinguished_without_echoing_private_data(configured,error,message):
    s,vault,v=configured;calls=[]
    def handler(req):
        calls.append(req)
        assert req.extensions['timeout']['connect']==4
        assert 0<req.extensions['timeout']['read']<=18
        raise error('synthetic-translation-key private-source',request=req)
    with pytest.raises(ValueError) as exc:translate(TEST_TEXT,v['revision'],s,factory(handler))
    assert message in str(exc.value) and '原文已保留' in str(exc.value)
    assert 'synthetic-translation-key' not in str(exc.value) and 'private-source' not in str(exc.value)
    assert len(calls)==1

@pytest.mark.parametrize('status,message',[(301,'跳转'),(307,'跳转'),(401,'凭证'),(403,'凭证'),(429,'受限'),(500,'500')])
def test_error_redaction_no_retry_or_redirect(configured,status,message):
    s,vault,v=configured;requests=[]
    def handler(req):
        requests.append(req)
        return httpx.Response(status,headers={'Location':'https://elsewhere.invalid'},text='echo synthetic-translation-key private-source')
    with pytest.raises(ValueError) as exc:translate(TEST_TEXT,v['revision'],s,factory(handler))
    assert message in str(exc.value) and 'synthetic-translation-key' not in str(exc.value) and 'private-source' not in str(exc.value)
    assert len(requests)==1

@pytest.mark.parametrize('body',[b'bad-json',b'{}',b'{"choices":[]}',b'{"choices":[{"message":{"content":""}}]}',b'x'*(MAX_RESPONSE+1)],ids=['bad-json','empty-object','empty-choices','empty-content','oversized-response'])
def test_bad_or_empty_response_retains_source(configured,body):
    s,vault,v=configured
    with pytest.raises(ValueError):translate(TEST_TEXT,v['revision'],s,factory(lambda r:httpx.Response(200,content=body)))

def test_version_and_cancel_before_network(configured):
    s,vault,v=configured
    def unexpected(**kwargs):raise AssertionError('network should not be created')
    with pytest.raises(ValueError,match='改变'):translate(TEST_TEXT,'old-version',s,unexpected)
    assert vault.reads==[]
    cancelled=threading.Event();cancelled.set()
    with pytest.raises(ValueError,match='取消'):translate(TEST_TEXT,v['revision'],s,unexpected,cancelled)
    assert not s.record_test('old-version',{'ok':True}) and 'last_test' not in s.public()

def test_no_speech_keys_and_text_blocks(configured):
    s,vault,v=configured
    vault.values[('com.xiaoha.voice.asr','volcengine-streaming')]='synthetic-asr-key'
    r=translate(TEST_TEXT,v['revision'],s,factory(lambda r:httpx.Response(200,json={'choices':[{'message':{'content':[{'type':'text','text':'Hello '},{'type':'text','text':'world.'}]}}]})))
    assert r['text']=='Hello world.' and vault.reads==[] and s.session_info()['cache_hits']==1

def test_current_session_reuses_saved_key_without_vault_reads(configured):
    s,vault,v=configured
    for _ in range(5):assert s.credentials(v['revision'])[1]=='synthetic-translation-key'
    assert vault.reads==[] and s.session_info()=={'ready':True,'vault_reads':0,'cache_hits':5}
    changed=s.save({**v,'model':'different-model','credential':''})
    assert s.credentials(changed['revision'])[1]=='synthetic-translation-key' and vault.reads==[]
    fresh=TranslationSettings(s.directory,vault)
    assert fresh.session_info()=={'ready':False,'vault_reads':0,'cache_hits':0}
    for _ in range(3):assert fresh.credentials(changed['revision'])[1]=='synthetic-translation-key'
    assert len(vault.reads)==1 and fresh.session_info()=={'ready':True,'vault_reads':1,'cache_hits':2}
    assert 'synthetic-translation-key' not in json.dumps(fresh.public())+s.path.read_text()

def test_concurrent_first_use_reads_vault_once(configured):
    from concurrent.futures import ThreadPoolExecutor
    s,vault,v=configured;fresh=TranslationSettings(s.directory,vault)
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(lambda _:fresh.credentials(v['revision'])[1],range(8)))
    assert results==['synthetic-translation-key']*8 and len(vault.reads)==1
    assert fresh.session_info()=={'ready':True,'vault_reads':1,'cache_hits':7}

def test_key_change_and_external_revision_cannot_reuse_stale_cache(configured):
    s,vault,v=configured
    changed=s.save({**v,'credential':'synthetic-new-key'})
    with pytest.raises(ValueError,match='改变'):s.credentials(v['revision'])
    assert s.credentials(changed['revision'])[1]=='synthetic-new-key'
    on_disk=json.loads(s.path.read_text());on_disk['revision']='external-change';s.path.write_text(json.dumps(on_disk))
    assert not s.session_info()['ready']
    assert s.credentials('external-change')[1]=='synthetic-new-key' and len(vault.reads)==1

def test_translation_run_and_benchmark_share_owner_and_enforce_auth(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from desktop.control import Companion,create_control
    import keyring,desktop.voice_translation as module
    vault=Vault();monkeypatch.setattr(keyring,'set_password',vault.set_password);monkeypatch.setattr(keyring,'get_password',vault.get_password)
    owners=[]
    def translated(text,revision,settings,**kwargs):
        owners.append(id(settings));settings.credentials(revision)
        return {'text':'Fixture English.','milliseconds':8,'target':'en'}
    monkeypatch.setattr(module,'translate',translated)
    client=TestClient(create_control(Companion(tmp_path/'companion',vault=vault)))
    payload={'text':'纠正后的 Claude。','revision':'none'}
    assert client.post('/workbench/api/translation-run',json=payload).status_code==401
    assert client.get('/workbench/api/translation-session').status_code==401
    client.get('/workbench');csrf=client.get('/workbench/api/status').json()['csrf'];headers={'Origin':'http://127.0.0.1:8766','X-CSRF-Token':csrf}
    saved=client.post('/workbench/api/translation',json={'enabled':True,'endpoint':'https://api.example.invalid/v1','model':'fixture','credential':'synthetic-translation-key'},headers=headers).json()
    payload['revision']=saved['revision']
    assert client.post('/workbench/api/translation-run',json=payload).status_code==403
    for _ in range(3):assert client.post('/workbench/api/translation-run',json=payload,headers=headers).json()['text']=='Fixture English.'
    assert client.post('/workbench/api/translation-test',json={'revision':saved['revision']},headers=headers).json()['ok']
    assert len(set(owners))==1 and len(owners)==4 and vault.reads==[]
    info=client.get('/workbench/api/translation-session').json();assert info=={'ready':True,'vault_reads':0,'cache_hits':4}
    for bad in [[],{}, {'text':'','revision':saved['revision']},{'text':'x'*50001,'revision':saved['revision']}]:
        assert client.post('/workbench/api/translation-run',json=bad,headers=headers).status_code==422
    assert client.post('/workbench/api/translation-run',json={'text':'x'*310000,'revision':saved['revision']},headers=headers).status_code==413
    stale=client.post('/workbench/api/translation-run',json={**payload,'revision':'stale'},headers=headers).json();assert not stale['ok'] and '改变' in stale['error']
    assert 'synthetic-translation-key' not in json.dumps(info) and 'credential' not in info

@pytest.mark.parametrize('c',[{'keyCode':0,'modifiers':0,'label':'a'},{'keyCode':59,'modifiers':0,'label':'左 Control'},{'keyCode':54,'modifiers':0x100000,'label':'bad'},{'keyCode':-1,'modifiers':0,'label':'bad','mouseButton':2}])
def test_bad_shortcut(c):
    import desktop.voice_translation as module
    # This parametrization is explicitly the macOS virtual-key layout.
    saved=module.WINDOWS;module.WINDOWS=False
    try:
        with pytest.raises(ValueError):shortcut_value(c)
    finally:module.WINDOWS=saved

def test_history_translation_does_not_double_statistics(tmp_path):
    from desktop.workbench import LocalWorkbench,ZONE
    from datetime import datetime
    p=tmp_path/'history.json';row={'id':'1','created_at':datetime.now(ZONE).isoformat(),'text':'明天和 Claude 开会','seconds':3.5,'english':'Meet Claude tomorrow.'};p.write_text(json.dumps([row]))
    store=LocalWorkbench(tmp_path,p);summary=store.summary('all')
    assert summary['sessions']==1 and summary['seconds']==3.5 and store.records()[0]['english']==row['english']
    assert len(store.records(query='Meet Claude'))==1

def test_routes_cookie_csrf_save_reopen_eye_and_test(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from desktop.control import Companion,create_control
    import keyring
    import desktop.voice_translation as module
    vault=Vault();monkeypatch.setattr(keyring,'set_password',vault.set_password);monkeypatch.setattr(keyring,'get_password',vault.get_password)
    calls=[]
    def translated(text,revision,settings,**kwargs):
        calls.append((text,revision));return {'text':'Meet tomorrow at ten.','milliseconds':123,'target':'en'}
    monkeypatch.setattr(module,'translate',translated)
    app=create_control(Companion(tmp_path/'companion',vault=vault));client=TestClient(app)
    assert client.get('/workbench/api/translation').status_code==401
    client.get('/workbench');csrf=client.get('/workbench/api/status').json()['csrf'];headers={'Origin':'http://127.0.0.1:8766','X-CSRF-Token':csrf}
    initial=client.get('/workbench/api/translation').json();assert not initial['enabled'] and vault.reads==[]
    payload={**initial,'enabled':True,'endpoint':'https://api.example.invalid/v1','model':'fixture','credential':'synthetic-translation-key'}
    assert client.post('/workbench/api/translation',json=payload).status_code==403
    saved=client.post('/workbench/api/translation',json=payload,headers=headers).json()
    assert saved['credential_saved'] and 'credential' not in saved and vault.reads==[]
    assert client.get('/workbench/api/translation').json()==saved and vault.reads==[]
    assert client.post('/workbench/api/translation-credential',json={'revision':saved['revision']},headers=headers).status_code==422
    revealed=client.post('/workbench/api/translation-credential',json={'revision':saved['revision'],'reveal':True},headers=headers)
    assert revealed.json()['credential']=='synthetic-translation-key'
    result=client.post('/workbench/api/translation-test',json={'revision':saved['revision']},headers=headers).json()
    assert result['ok'] and result['current'] and calls==[(TEST_TEXT,saved['revision'])]
    assert client.get('/workbench/api/translation').json()['last_test']['milliseconds']==123
    assert not any('synthetic-translation-key' in p.read_text() for p in tmp_path.rglob('*.json'))

def test_real_cli_with_owned_loopback_api_and_fake_vault(tmp_path):
    """One self-owned local TCP listener, no external service or personal key."""
    import os,subprocess,sys
    from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
    from desktop.runtime_settings import DEFAULT as NETWORK_DEFAULT
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            assert self.path=='/v1/chat/completions'
            assert self.headers['Authorization']=='Bearer synthetic-cli-key'
            seen.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            body=json.dumps({'choices':[{'message':{'content':'Meet Claude tomorrow.'}}]}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        data=tmp_path/'data';data.mkdir()
        (data/'translation-settings.json').write_text(json.dumps({**__import__('desktop.voice_translation',fromlist=['DEFAULT']).DEFAULT,'enabled':True,'endpoint':f'http://127.0.0.1:{server.server_port}/v1/chat/completions','model':'cli-fixture','credential_saved':True,'revision':'cli-r1'}))
        (data/'runtime-settings.json').write_text(json.dumps({**NETWORK_DEFAULT,'proxy_mode':'direct'}))
        (tmp_path/'fixture_vault.py').write_text("from keyring.backend import KeyringBackend\nclass Backend(KeyringBackend):\n priority=1\n def get_password(self,s,a):\n  assert s=='com.xiaoha.voice.standalone.translation' and a.startswith('english-output-')\n  return 'synthetic-cli-key'\n def set_password(self,*a):raise AssertionError()\n def delete_password(self,*a):raise AssertionError()\n")
        root=Path(__file__).resolve().parents[2];env={**os.environ,'PYTHONPATH':str(root/'sync-suite')+os.pathsep+str(tmp_path),'XH_VOICE_DATA':str(data),'PYTHON_KEYRING_BACKEND':'fixture_vault.Backend','PYTHONDONTWRITEBYTECODE':'1'}
        for revision in ['cli-r1','stale-r0']:
            proc=subprocess.run([sys.executable,'-B','-c','from desktop.voice_translation import run_cli; run_cli()'],input=json.dumps({'text':'明天和 Claude 开会。','revision':revision}),text=True,capture_output=True,env=env,timeout=10)
            result=json.loads(proc.stdout)
            assert result['ok']==(revision=='cli-r1') and 'synthetic-cli-key' not in proc.stdout+proc.stderr
            if result['ok']:assert result['text']=='Meet Claude tomorrow.'
        assert len(seen)==1 and seen[0]['messages'][1]['content']=='明天和 Claude 开会。' and seen[0]['model']=='cli-fixture'
    finally:server.shutdown();server.server_close();thread.join(2)
