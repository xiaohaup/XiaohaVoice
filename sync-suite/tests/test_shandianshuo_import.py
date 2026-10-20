from datetime import datetime, timezone
from uuid import UUID, uuid4
import json
import stat
import pytest
from fastapi.testclient import TestClient
from desktop.import_shandianshuo import run
from desktop.history_sources import import_path, migration_status, archive_path, read_sources
from desktop.workbench import LocalWorkbench, ZONE
from desktop.control import Companion, create_control
from desktop.client import SyncEngine


def fixture(tmp_path):
    history=tmp_path/'native/history.json';history.parent.mkdir()
    history.write_text(json.dumps([{'id':str(uuid4()),'createdAt':datetime(2026,2,28,tzinfo=timezone.utc).timestamp()-978307200,'text':'原有123','seconds':4}]))
    def row(rid,text,status='success',kind='voice_input',day=26):
        return {'id':rid,'status':status,'record_type':kind,'timestamp':int(datetime(2026,2,day,16,tzinfo=timezone.utc).timestamp()),
                'duration_ms':2500,'text':text,'focus_info':{'app_name':'FixtureApp','window_title':'SYNTHETIC TITLE'},'audio_file':'synthetic.wav'}
    source=tmp_path/'source.json';source.write_text(json.dumps({'version':'1.0','records':[
        row('one','中文 Claude 123!'),row('two','你好 AI','success','voice_assistant',27),
        row('quiet','empty placeholder','empty'),row('failed','error placeholder','error')]}))
    return source,history


def store(history):return LocalWorkbench(history.parent/'desktop',history,lambda:datetime(2026,3,1,tzinfo=ZONE))


def test_preview_has_no_writes(tmp_path):
    source,history=fixture(tmp_path);before=history.read_bytes();value=run(source,history)
    assert value['added']==2 and value['characters']==6 and value['seconds']==5
    assert not import_path(history).exists() and history.read_bytes()==before


def test_apply_preserves_native_and_exact_archive(tmp_path):
    source,history=fixture(tmp_path);native=history.read_bytes();raw=source.read_bytes();run(source,history,True)
    assert history.read_bytes()==native and source.read_bytes()==raw and archive_path(history).read_bytes()==raw
    assert migration_status(history)['empty_records']==1 and migration_status(history)['error_records']==1
    imported=[r for r in read_sources(history) if r.get('source')=='shandianshuo']
    assert len(imported)==2 and all(UUID(r['id']) for r in imported) and imported[0]['application']=='FixtureApp'
    assert all('window_title' not in r and 'audio_file' not in r for r in imported)
    assert stat.S_IMODE(import_path(history).stat().st_mode)==0o600
    assert stat.S_IMODE(import_path(history).parent.stat().st_mode)==0o700


def test_repeat_is_idempotent_and_revision_unchanged(tmp_path):
    source,history=fixture(tmp_path);run(source,history,True);p=import_path(history);before=p.read_bytes();mtime=p.stat().st_mtime_ns
    result=run(source,history,True)
    assert result['added']==0 and result['updated']==0 and result['unchanged']
    assert p.read_bytes()==before and p.stat().st_mtime_ns==mtime


def test_summary_dates_ranges_apps_and_source_counts(tmp_path):
    source,history=fixture(tmp_path);s=store(history);before=s.revision();assert s.summary('all')['sessions']==1
    run(source,history,True);assert s.revision()!=before;value=s.summary('all')
    assert value['sessions']==3 and value['characters']==11 and value['seconds']==9
    assert value['migration']['characters']==6 and value['active_days']==2 and value['longest_streak']==2
    assert s.records(day='2026-02-27')[0]['source']=='shandianshuo' and len(s.records('claude'))==1
    assert value['unknown_application_sessions']==1 and value['applications'][0]['count']==2
    assert value['average_seconds']==3 and value['average_characters']==3.7 and s.summary('month')['sessions']==0


def test_native_append_cannot_erase_imports(tmp_path):
    source,history=fixture(tmp_path);run(source,history,True);s=store(history);assert len(s.records())==3
    rows=json.loads(history.read_text());rows.append({'id':str(uuid4()),'created_at':'2026-02-28T12:00:00+08:00','text':'新增','seconds':2});history.write_text(json.dumps(rows))
    assert len(s.records())==4 and s.summary('all')['migration']['completed_records']==2


def test_source_update_preserves_same_id(tmp_path):
    source,history=fixture(tmp_path);run(source,history,True);raw=json.loads(source.read_text());raw['records'][0]['text']='中文 Claude 更正';source.write_text(json.dumps(raw))
    result=run(source,history,True)
    assert result['added']==0 and result['updated']==1 and store(history).summary('all')['sessions']==3
    assert len(list((import_path(history).parent/'backups').glob('*.json')))==1


@pytest.mark.parametrize('change',[
    lambda v:v.update(version='unknown'),lambda v:v['records'].append(v['records'][0]),
    lambda v:v['records'][0].update(duration_ms=-1),lambda v:v['records'][0].update(duration_ms=True),
    lambda v:v['records'][0].update(status='unknown'),lambda v:v['records'][0].update(timestamp=99999999999)])
def test_invalid_source_never_commits(tmp_path,change):
    source,history=fixture(tmp_path);before=history.read_bytes();v=json.loads(source.read_text());change(v);source.write_text(json.dumps(v))
    with pytest.raises(ValueError):run(source,history,True)
    assert not import_path(history).exists() and history.read_bytes()==before


def test_archive_requires_local_session(tmp_path):
    source,history=fixture(tmp_path);run(source,history,True)
    client=TestClient(create_control(Companion(tmp_path/'control',history_path=history)));path='/workbench/api/imports/shandianshuo/archive'
    assert client.get(path).status_code==401
    client.get('/workbench');r=client.get(path);assert r.status_code==200 and r.content==source.read_bytes()
    assert client.get(path,headers={'Sec-Fetch-Site':'cross-site'}).status_code==403


def test_import_is_usage_only_never_new_cloud_clipboard(tmp_path):
    source,history=fixture(tmp_path);identity={'account_id':'synthetic-account','device_id':str(uuid4())}
    engine=SyncEngine(tmp_path/'engine',None,identity,history_path=history);engine.state['usage_sync']=True
    engine.ingest_history();old_ids=set(engine.state['usage_queue']);run(source,history,True);engine.ingest_history()
    assert len(engine.state['usage_queue'])==3 and not engine.state['queue']
    imported=[v for k,v in engine.state['usage_queue'].items() if k not in old_ids]
    assert sum(v['characters'] for v in imported)==6
    assert all(set(v)=={'session_id','created_at','characters','seconds'} for v in imported)
    engine.ingest_history();assert len(engine.state['usage_queue'])==3


def test_source_trim_keeps_previously_imported_records_and_statistics(tmp_path):
    source,history=fixture(tmp_path);run(source,history,True)
    value=json.loads(source.read_text());value['records']=value['records'][:1];source.write_text(json.dumps(value))
    result=run(source,history,True)
    assert result['added']==0 and result['retained_from_previous_import']==1
    assert migration_status(history)['completed_records']==2 and migration_status(history)['characters']==6
    assert store(history).summary('all')['sessions']==3


def test_application_denominator_includes_missing_information(tmp_path):
    source,history=fixture(tmp_path);run(source,history,True);s=store(history).summary('all')
    assert s['applications']==[{'name':'FixtureApp','count':2,'percent':66.7},{'name':'未记录应用','count':1,'percent':33.3}]
    assert s['unknown_application_sessions']==1
