import asyncio
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from desktop.asr_settings import ASRSettings
from desktop.control import Companion,create_control
from desktop.analytics import app_counts

class Vault:
    def __init__(self):self.value=''
    def set_password(self,*args):self.value=args[-1]
    def get_password(self,*args):return self.value

def test_saved_summary_timestamp_no_secret_and_stale_test(tmp_path):
    s=ASRSettings(tmp_path/'asr.json',Vault())
    value=s.save({**s.public(),'provider':'volcengine','credential':'test-secret-only'})
    assert value['saved_at'] and value['credential_saved']
    assert 'test-secret' not in json.dumps(value) and 'test-secret' not in s.path.read_text()
    assert s.record_test(value['revision'],{'ok':True,'milliseconds':24,'detail':'passed'})
    assert s.public()['connection_test']['ok']
    later=s.save({**value,'credential':'','second_pass':False})
    assert 'connection_test' not in later
    assert not s.record_test(value['revision'],{'ok':True})
    assert s.public()['revision']==later['revision']

def test_rank_distinguishes_missing_and_small_known():
    rows=[{'application':chr(65+i)} for i in range(7) for _ in range(10-i)]+[{} for _ in range(20)]
    ranks,known=app_counts(rows)
    assert ranks[-1]['name']=='未记录应用' and ranks[-1]['count']==20
    assert ranks[-2]['name']=='其他已知应用' and ranks[-2]['count']==9
    assert sum(r['count'] for r in ranks)==len(rows)
    all_ranks,_=app_counts(rows,None)
    assert all_ranks[5]['name']=='F' and all_ranks[6]['name']=='G'

def test_test_endpoint_saved_config_redacts_raw_errors_and_persists(tmp_path,monkeypatch):
    import keyring,sys
    monkeypatch.setattr(keyring,'get_password',lambda *a:'synthetic-key')
    monkeypatch.setattr(keyring,'set_password',lambda *a:None)
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ime-channel-test'))
    import volcengine_asr
    client=TestClient(create_control(Companion(tmp_path/'companion')));client.get('/workbench')
    headers={'Origin':'http://127.0.0.1:8766','X-CSRF-Token':client.get('/workbench/api/status').json()['csrf']}
    path='/workbench/api/asr';value=client.get(path).json()
    value=client.post(path,json={**value,'provider':'volcengine','credential':'synthetic-key'},headers=headers).json()['value']
    async def fail(*a):raise RuntimeError('synthetic-key must never escape')
    monkeypatch.setattr(volcengine_asr,'probe',fail)
    r=client.post(path+'-test',json={'revision':value['revision']},headers=headers)
    assert r.status_code==200 and not r.json()['ok'] and r.json()['current']
    assert 'synthetic-key' not in r.text and 'synthetic-key' not in client.get(path).text
    async def passed(*a):return {'ok':True,'milliseconds':123,'detail':'passed'}
    monkeypatch.setattr(volcengine_asr,'probe',passed)
    r=client.post(path+'-test',json={'revision':value['revision']},headers=headers)
    assert r.json()['ok'] and client.get(path).json()['connection_test']['milliseconds']==123
    assert client.post(path+'-test',json={'revision':'stale'},headers=headers).status_code==409
    assert client.post(path+'-test',json={},headers={}).status_code==403

def test_rejected_legacy_configuration_does_not_replace_existing_key(tmp_path):
    vault=Vault();s=ASRSettings(tmp_path/'asr.json',vault)
    initial=s.save({**s.public(),'provider':'volcengine','credential':'original-api-key'})
    with pytest.raises(ValueError,match='App ID'):
        s.save({**initial,'auth':'legacy','app_id':'','credential':'new-access-token'})
    assert vault.value=='original-api-key'
    assert s.public()==initial

def test_credential_requires_explicit_protected_post_and_does_not_leak_to_settings(tmp_path,monkeypatch):
    import keyring
    calls=[]
    monkeypatch.setattr(keyring,'get_password',lambda *a:calls.append(a) or 'fixture-vault-secret')
    monkeypatch.setattr(keyring,'set_password',lambda *a:None)
    client=TestClient(create_control(Companion(tmp_path/'companion')));client.get('/workbench')
    headers={'Origin':'http://127.0.0.1:8766','X-CSRF-Token':client.get('/workbench/api/status').json()['csrf']}
    path='/workbench/api/asr';value=client.get(path).json()
    saved=client.post(path,json={**value,'provider':'volcengine','credential':'fixture-vault-secret'},headers=headers).json()['value']
    assert not calls and 'fixture-vault-secret' not in client.get(path).text
    assert client.get(path+'-credential').status_code==405
    assert client.post(path+'-credential',json={'revision':saved['revision']},headers=headers).status_code==422
    assert client.post(path+'-credential',json={'reveal':True,'revision':'old'},headers=headers).status_code==409
    assert client.post(path+'-credential',json={'reveal':True,'revision':saved['revision']}).status_code==403
    assert not calls
    r=client.post(path+'-credential',json={'reveal':True,'revision':saved['revision']},headers=headers)
    assert r.json()=={'credential':'fixture-vault-secret'} and r.headers['cache-control']=='no-store'
    assert len(calls)==1 and 'fixture-vault-secret' not in client.get(path).text
    assert 'fixture-vault-secret' not in (tmp_path/'companion/asr-settings.json').read_text()

def test_manual_speed_test_uses_bundled_audio_and_preserves_connection_result(tmp_path,monkeypatch):
    import keyring,sys
    monkeypatch.setattr(keyring,'get_password',lambda *a:'fixture-key')
    monkeypatch.setattr(keyring,'set_password',lambda *a:None)
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ime-channel-test'))
    import volcengine_asr
    client=TestClient(create_control(Companion(tmp_path/'companion')));client.get('/workbench')
    headers={'Origin':'http://127.0.0.1:8766','X-CSRF-Token':client.get('/workbench/api/status').json()['csrf']}
    path='/workbench/api/asr';value=client.get(path).json()
    value=client.post(path,json={**value,'provider':'volcengine','credential':'fixture-key'},headers=headers).json()['value']
    async def probe(*a):return {'ok':True,'milliseconds':100,'detail':'connected'}
    async def speed(config,key,pcm):
        assert key=='fixture-key' and len(pcm)==32000
        return {'ok':True,'first_text_ms':900,'finish_wait_ms':300,'updates':7,'text':'内置合成语音','detail':'passed'}
    monkeypatch.setattr(volcengine_asr,'probe',probe);monkeypatch.setattr(volcengine_asr,'benchmark',speed)
    client.post(path+'-test',json={'revision':value['revision']},headers=headers)
    assert client.post(path+'-speed-test',json={'revision':value['revision']},headers=headers).status_code==422
    r=client.post(path+'-speed-test',json={'revision':value['revision'],'confirmed':True},headers=headers)
    assert r.json()['ok'] and r.json()['current']
    saved=client.get(path).json()
    assert saved['connection_test']['milliseconds']==100 and saved['speed_test']['updates']==7
    async def failed(*a):raise RuntimeError('fixture-key must not escape')
    monkeypatch.setattr(volcengine_asr,'benchmark',failed)
    r=client.post(path+'-speed-test',json={'revision':value['revision'],'confirmed':True},headers=headers)
    assert not r.json()['ok'] and 'fixture-key' not in r.text

def test_test_results_remain_with_their_provider_when_switching(tmp_path):
    s=ASRSettings(tmp_path/'asr.json',Vault())
    api=s.save({**s.public(),'provider':'volcengine','credential':'fixture-key'})
    s.record_test(api['revision'],{'ok':True,'text':'API result'},'speed_test')
    ime=s.save({**s.public(),'provider':'ime','credential':''})
    assert 'speed_test' not in ime
    assert ime['test_results']['volcengine']['speed_test']['text']=='API result'
    assert s.record_test(ime['revision'],{'ok':True,'text':'API result'},'speed_test','volcengine')
    assert s.config()['provider']=='ime'
    s.record_test(ime['revision'],{'ok':True,'text':'IME result'},'speed_test','ime')
    api=s.save({**s.public(),'provider':'volcengine','credential':''})
    assert api['speed_test']['text']=='API result'
    assert api['test_results']['ime']['speed_test']['text']=='IME result'
    changed=s.save({**api,'credential':'replacement-fixture'})
    assert 'speed_test' not in changed and 'volcengine' not in changed['test_results']
    assert changed['test_results']['ime']['speed_test']['text']=='IME result'

def test_ime_speed_test_never_reads_api_key_or_calls_api(tmp_path,monkeypatch):
    import keyring,sys
    def forbidden(*a,**kw):raise AssertionError('API credential or recognition must not run')
    monkeypatch.setattr(keyring,'get_password',forbidden)
    monkeypatch.setattr(keyring,'set_password',lambda *a:None)
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ime-channel-test'))
    import channel_probe,volcengine_asr
    monkeypatch.setattr(volcengine_asr,'benchmark',forbidden)
    async def ime(pcm):
        assert len(pcm)==32000
        return {'ok':True,'first_text_ms':700,'finish_wait_ms':200,'updates':8,'text':'IME result','backend':'doubao_input_method'}
    monkeypatch.setattr(channel_probe,'benchmark',ime)
    client=TestClient(create_control(Companion(tmp_path/'companion')));client.get('/workbench')
    headers={'Origin':'http://127.0.0.1:8766','X-CSRF-Token':client.get('/workbench/api/status').json()['csrf']}
    path='/workbench/api/asr';value=client.get(path).json()
    saved=client.post(path,json={**value,'provider':'volcengine','credential':'fixture-key'},headers=headers).json()['value']
    body={'revision':saved['revision'],'provider':'ime','confirmed':True}
    r=client.post(path+'-speed-test',json=body,headers=headers)
    assert r.json()['ok'] and r.json()['provider']=='ime'
    current=client.get(path).json()
    assert current['test_results']['ime']['speed_test']['text']=='IME result'
    assert current['provider']=='volcengine' and current['revision']==saved['revision']
    assert client.post(path+'-speed-test',json={**body,'provider':'invalid'},headers=headers).status_code==422
    async def denied(*a):raise RuntimeError('private-device-identifier')
    monkeypatch.setattr(channel_probe,'benchmark',denied)
    r=client.post(path+'-speed-test',json=body,headers=headers)
    assert not r.json()['ok'] and 'private-device-identifier' not in r.text

def test_manual_api_connection_while_ime_active_does_not_switch_mode(tmp_path,monkeypatch):
    import keyring,sys
    monkeypatch.setattr(keyring,'get_password',lambda *a:'fixture-key')
    monkeypatch.setattr(keyring,'set_password',lambda *a:None)
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ime-channel-test'))
    import volcengine_asr
    async def probe(config,key):
        assert key=='fixture-key'
        return {'ok':True,'milliseconds':100,'detail':'fixture connected'}
    monkeypatch.setattr(volcengine_asr,'probe',probe)
    client=TestClient(create_control(Companion(tmp_path/'companion')));client.get('/workbench')
    headers={'Origin':'http://127.0.0.1:8766','X-CSRF-Token':client.get('/workbench/api/status').json()['csrf']}
    path='/workbench/api/asr';value=client.get(path).json()
    saved=client.post(path,json={**value,'provider':'ime','credential':'fixture-key'},headers=headers).json()['value']
    r=client.post(path+'-test',json={'provider':'volcengine','revision':saved['revision']},headers=headers)
    assert r.json()['ok'] and r.json()['provider']=='volcengine'
    current=client.get(path).json()
    assert current['provider']=='ime' and current['revision']==saved['revision']
    assert current['test_results']['volcengine']['connection_test']['milliseconds']==100

def test_manual_ime_connection_is_audio_free_and_independent_of_active_api(tmp_path,monkeypatch):
    import keyring,sys
    def forbidden(*a):raise AssertionError('IME connection test must not use API credentials or audio')
    monkeypatch.setattr(keyring,'get_password',forbidden)
    monkeypatch.setattr(keyring,'set_password',lambda *a:None)
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ime-channel-test'))
    import channel_probe,volcengine_asr
    async def probe():return {'ok':True,'check':'ime_session','milliseconds':100,'detail':'fixture session ready'}
    monkeypatch.setattr(channel_probe,'probe',probe);monkeypatch.setattr(channel_probe,'benchmark',forbidden)
    monkeypatch.setattr(volcengine_asr,'probe',forbidden)
    client=TestClient(create_control(Companion(tmp_path/'companion')));client.get('/workbench')
    headers={'Origin':'http://127.0.0.1:8766','X-CSRF-Token':client.get('/workbench/api/status').json()['csrf']}
    path='/workbench/api/asr';value=client.get(path).json()
    saved=client.post(path,json={**value,'provider':'volcengine','credential':'fixture-key'},headers=headers).json()['value']
    r=client.post(path+'-test',json={'provider':'ime','revision':saved['revision']},headers=headers)
    assert r.json()['ok'] and r.json()['provider']=='ime' and r.json()['total_ms']>=0
    current=client.get(path).json()
    assert current['provider']=='volcengine' and current['revision']==saved['revision']
    assert current['test_results']['ime']['connection_test']['check']=='ime_session'
