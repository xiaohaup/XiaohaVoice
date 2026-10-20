import json
from pathlib import Path
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from tests.test_service import service, connect, change, PASSWORD
from desktop.client import ApiError, Remote, SyncEngine, characters
from desktop.control import Companion, create_control


class FakeClipboard:
    def __init__(self, text='Original clipboard fixture'):
        self.text, self.rev, self.reads, self.writes = text, 1, 0, []
    def read(self):
        self.reads += 1
        return {'text': self.text, 'revision': self.rev}
    def user_copy(self, text):
        self.text = text; self.rev += 1
    def write(self, text, expected):
        if expected != self.rev: return False
        self.user_copy(text); self.writes.append(text); return True


class TestRemote:
    __test__ = False
    def __init__(self, client):
        self.client, self.offline, self.ambiguous_once, self.calls = client, False, False, []
    def call(self, method, path, body=None):
        if self.offline: raise httpx.ConnectError('synthetic offline')
        self.calls.append((path, body))
        r = self.client.request(method,path,json=body)
        if r.status_code >= 400: raise ApiError(r.status_code,r.json()['detail'])
        if self.ambiguous_once and path=='/api/mutate':
            self.ambiguous_once=False;raise httpx.ReadError('synthetic response lost after commit')
        return r.json()


def engine(tmp_path, service, name='fixture_a', register=True, clipboard=None, history=None, clock=lambda:0):
    c, identity=connect(service,name,register)
    remote=TestRemote(c)
    result=SyncEngine(tmp_path/name/identity['device_id'],remote,identity,clipboard,history,tmp_path/'wordbook.json',clock)
    return result,c


def test_disabled_component_never_reads_clipboard_or_network(tmp_path,service):
    clip=FakeClipboard();e,c=engine(tmp_path,service,clipboard=clip)
    e.sync_once()
    assert clip.reads==0 and not e.remote.calls


def test_temporary_voice_clipboard_and_restore_do_not_echo_to_cloud(tmp_path,service):
    clock=[0];clip=FakeClipboard();e,c=engine(tmp_path,service,clipboard=clip,clock=lambda:clock[0])
    e.set_settings({'enabled':True,'send_clipboard':True});e.sync_once()
    clip.user_copy('Temporary dictation fixture');clock[0]=.3;e.sync_once()
    clip.user_copy('Original clipboard fixture');clock[0]=1.6;e.sync_once()
    clock[0]=4;e.sync_once()
    assert c.get('/api/state').json()['items']==[]


def test_new_user_copy_is_uploaded_after_quiet_period(tmp_path,service):
    clock=[0];clip=FakeClipboard();e,c=engine(tmp_path,service,clipboard=clip,clock=lambda:clock[0])
    e.set_settings({'enabled':True,'send_clipboard':True});e.sync_once()
    clip.user_copy('Intentional copied fixture');e.sync_once()
    clock[0]=2;e.sync_once()
    assert c.get('/api/state').json()['items'][0]['value']['text']=='Intentional copied fixture'


def test_offline_outbox_survives_reopen_and_ambiguous_commit(tmp_path,service):
    e,c=engine(tmp_path,service);e.set_settings({'enabled':True})
    e.queue('clipboard','current',{'text':'Offline fixture'})
    e.remote.offline=True
    with pytest.raises(httpx.HTTPError): e.sync_once()
    second=SyncEngine(e.directory,e.remote,e.identity)
    assert len(second.state['queue'])==1
    second.remote.offline=False;second.remote.ambiguous_once=True
    with pytest.raises(httpx.HTTPError):second.sync_once()
    assert len(second.state['queue'])==1
    second.sync_once()
    assert not second.state['queue']
    assert c.get('/api/state').json()['revision']==1


def test_clipboard_conflict_keeps_local_copy_until_user_resolves(tmp_path,service):
    e,c=engine(tmp_path,service);e.set_settings({'enabled':True})
    other,_=connect(service,register=False)
    e.queue('clipboard','current',{'text':'Offline local'})
    change(other,value={'text':'Other device'})
    e.sync_once()
    assert e.state['queue'][0]['conflict']['current']['value']['text']=='Other device'
    assert e.state['queue'][0]['value']['text']=='Offline local'
    e.resolve(e.state['queue'][0]['operation_id'],'local');e.sync_once()
    assert c.get('/api/state').json()['items'][0]['value']['text']=='Offline local'


def test_copy_debounce_keeps_original_revision_during_remote_race(tmp_path,service):
    clock=[0];clip=FakeClipboard();e,c=engine(tmp_path,service,clipboard=clip,clock=lambda:clock[0])
    e.set_settings({'enabled':True,'send_clipboard':True,'receive_clipboard':True});e.sync_once()
    clip.user_copy('Local draft at old revision')
    other,_=connect(service,register=False);change(other,value={'text':'Concurrent remote copy'})
    e.sync_once();assert clip.text=='Local draft at old revision'
    clock[0]=2;e.sync_once()
    assert e.state['queue'][0].get('conflict')
    assert not clip.writes


def test_sequential_offline_copies_rebase_only_after_own_ack(tmp_path,service):
    e,c=engine(tmp_path,service);e.set_settings({'enabled':True})
    e.queue('clipboard','current',{'text':'First local'})
    e.queue('clipboard','current',{'text':'Second local'})
    e.sync_once()
    assert not e.state['queue']
    assert c.get('/api/state').json()['items'][0]['value']['text']=='Second local'


def test_receive_does_not_echo_and_ignores_new_local_copy(tmp_path,service):
    clip=FakeClipboard();e,c=engine(tmp_path,service,clipboard=clip)
    e.set_settings({'enabled':True,'receive_clipboard':True});other,_=connect(service,register=False)
    change(other,value={'text':'Remote fixture'});e.sync_once()
    assert clip.text=='Remote fixture'
    e.set_settings({'send_clipboard':True});e.sync_once();e.sync_once()
    assert c.get('/api/state').json()['revision']==1


def test_deferred_receive_is_not_lost_when_temporary_clipboard_restores(tmp_path,service):
    clip=FakeClipboard();e,c=engine(tmp_path,service,clipboard=clip)
    e.set_settings({'enabled':True,'receive_clipboard':True,'send_clipboard':True});e.sync_once()
    clip.user_copy('Temporary voice clipboard')
    other,_=connect(service,register=False);change(other,value={'text':'Remote waiting fixture'})
    e.sync_once();assert not clip.writes
    clip.user_copy('Original clipboard fixture');e.sync_once()
    assert clip.text=='Remote waiting fixture'


def test_history_upload_contains_counts_only_and_restart_dedupes(tmp_path,service):
    path=tmp_path/'history.json';rid=str(uuid4())
    path.write_text(json.dumps([{'id':rid,'createdAt':813000000,'text':'不能上传整段历史 fixture','seconds':7}]))
    e,c=engine(tmp_path,service,history=path);e.set_settings({'enabled':True,'usage_sync':True});e.sync_once()
    second=SyncEngine(e.directory,e.remote,e.identity,history_path=path);second.sync_once()
    assert c.get('/api/state').json()['usage_total']['sessions']==1
    uploads=[body for route,body in e.remote.calls if route=='/api/usage']
    assert len(uploads)==1 and set(uploads[0]['events'][0])=={'session_id','created_at','characters','seconds'}
    assert c.get('/api/state').json()['items']==[]


def test_new_dictation_publishes_current_text_but_old_history_does_not(tmp_path,service):
    path=tmp_path/'history.json';path.write_text('[]')
    e,c=engine(tmp_path,service,history=path);e.set_settings({'enabled':True});e.sync_once()
    path.write_text(json.dumps([{'id':str(uuid4()),'createdAt':813000000,'text':'Only this fresh dictation','seconds':7}]))
    e.sync_once();state=c.get('/api/state').json()
    assert state['items'][0]['value']['text']=='Only this fresh dictation'
    assert state['usage_total']['sessions']==0


def test_logout_account_isolation_local_tokens_and_csrf(tmp_path,service):
    creator,ident=connect(service)
    class MemoryVault:
        def __init__(self):self.rows={}
        def save(self,s,a,t):self.rows[(s,a)]=t
        def load(self,s,a):return self.rows.get((s,a))
        def remove(self,s,a):self.rows.pop((s,a),None)
    def factory(server,token=''):
        remote=TestRemote(TestClient(service));remote.token=token
        if token: remote.client.headers['Authorization']='Bearer '+token
        original=remote.call
        def call(method,path,body=None):
            remote.client.headers['x-xiaoha-native']='1'
            if remote.token:remote.client.headers['Authorization']='Bearer '+remote.token
            return original(method,path,body)
        remote.call=call;return remote
    companion=Companion(tmp_path/'companion',FakeClipboard(),MemoryVault(),factory)
    local=TestClient(create_control(companion,'http://testserver'))
    local.headers['origin']='http://testserver'
    assert local.post('/local/connect',json={'server':'http://testserver'}).status_code==200
    body={'username':'fixture_a','password':PASSWORD,'device_id':str(uuid4()),'device_name':'Desktop fixture','platform':'Mac','invite':''}
    response=local.post('/api/login',json=body);assert response.status_code==200,response.text
    assert 'token' not in response.json()
    assert local.get('/local/settings').status_code==200
    assert local.post('/local/settings',json={'enabled':True}).status_code==403
    local.headers['x-csrf-token']=response.json()['csrf']
    assert local.post('/local/settings',json={'enabled':True}).status_code==200
    assert local.post('/api/logout',json={}).status_code==200
    assert local.get('/local/history').status_code==401
    assert not companion.vault.rows
    assert 'password' not in companion.config


def test_remote_refuses_http_and_never_follows_token_redirects():
    with pytest.raises(ValueError):Remote('http://untrusted.example','secret-fixture')
    seen=[]
    def route(request):
        seen.append(request.url.host)
        return httpx.Response(302,headers={'location':'https://other.example/api/state'})
    remote=Remote('https://trusted.example','secret-fixture',httpx.MockTransport(route))
    with pytest.raises(ApiError):remote.call('GET','/api/state')
    assert seen==['trusted.example']


def test_character_count_contract():
    assert characters('你好，Mac 123')==8
    assert characters('e\u0301🙂')==2
