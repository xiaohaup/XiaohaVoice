from datetime import datetime
import importlib.util
import json
from pathlib import Path
import pytest
from desktop.workbench import LocalWorkbench, ZONE
from desktop.corrections import Corrections, validate
from desktop.asr_settings import ASRSettings
ROOT=Path(__file__).resolve().parents[2]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
P=load('personal',ROOT/'ime-channel-test/personalization.py' if (ROOT/'ime-channel-test/personalization.py').exists() else Path(__file__).resolve().parents[1]/'integration/personalization.py')

def test_local_case_rules_disable_boundaries(tmp_path):
    cloud=tmp_path/'cloud.json';cloud.write_text('{}')
    local=tmp_path/'local.json';c=Corrections(local)
    c.save({'enabled':True,'words':[{'term':'Claude','aliases':['Cloud'],'case_sensitive':False}]})
    p=P.Personalizer(cloud,local)
    assert p.apply('Cloud cloud CLOUD cloudflare 不能10点')=='Claude Claude Claude cloudflare 不能10点'
    c.save({'enabled':False,'words':[{'term':'Claude','aliases':['Cloud']}]})
    assert P.Personalizer(cloud,local).apply('Cloud')=='Cloud'
    with pytest.raises(ValueError):validate({'enabled':True,'words':[{'term':'甲','aliases':['Cloud']},{'term':'乙','aliases':['cloud']}]})

def test_correction_persistence_default_and_disabled(tmp_path):
    path=tmp_path/'local.json';store=Corrections(path)
    assert store.load()['words'][0]['term']=='Claude'
    store.save({'enabled':True,'words':[{'term':'Claude','aliases':['Cloud'],'enabled':False}]})
    assert P.Personalizer(path).apply('Cloud')=='Cloud'
    assert Corrections(path).load()['words'][0]['enabled'] is False

def test_history_revision_and_application_stats(tmp_path):
    path=tmp_path/'history.json'
    rows=[{'id':'a','created_at':'2026-10-18T10:00:00+08:00','text':'Claude Claude 工作台','seconds':40,'application':'Codex'},
          {'id':'b','created_at':'2026-10-18T11:00:00+08:00','text':'Claude 工作台','seconds':20}]
    path.write_text(json.dumps(rows));s=LocalWorkbench(tmp_path/'data',path,lambda:datetime(2026,10,18,tzinfo=ZONE))
    before=s.revision();v=s.summary('all')
    assert v['average_seconds']==30
    assert v['applications']==[{'name':'Codex','count':1,'percent':50.0}, {'name':'未记录应用','count':1,'percent':50.0}]
    assert v['unknown_application_sessions']==1
    assert next(w for w in v['words'] if w['name']=='Claude')['count']==3
    assert len(v['days'])==365
    rows.append({'id':'c','created_at':'2026-10-18T12:00:00+08:00','text':'更新','seconds':5,'application':'微信'})
    path.write_text(json.dumps(rows));assert s.revision()!=before
    assert s.summary('all')['sessions']==3

class Vault:
    def __init__(self):self.values={}
    def set_password(self,s,a,v):self.values[s,a]=v

def test_api_secrets_not_written_or_returned(tmp_path):
    v=Vault();path=tmp_path/'asr.json';s=ASRSettings(path,v)
    cfg={**s.public(),'provider':'volcengine'}
    with pytest.raises(ValueError):s.save(cfg)
    cfg['credential']='synthetic-secret-only';result=s.save(cfg)
    assert result['credential_saved'] is True and result['provider']=='volcengine'
    assert 'synthetic-secret' not in path.read_text() and 'credential' not in result
    assert list(v.values.values())==['synthetic-secret-only']
    assert s.save({**result,'provider':'ime','credential':''})['provider']=='ime'
