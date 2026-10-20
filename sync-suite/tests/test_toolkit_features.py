from pathlib import Path
import json, zipfile, hashlib
import pytest
from desktop.corrections import Corrections, DraftConflict
from desktop.runtime_settings import RuntimeSettings
from desktop.runtime_log import append, recent
from desktop.toolkit_archive import create_backup,verify,restore_new,restore_data, safe_name, PREFIX,MANIFEST

def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
def tool(tmp_path):
    root=tmp_path/'tool';root.mkdir();write(root/'toolkit.json',{'format':1});write(root/'Data/history.json',[{'id':'one','text':'合成记录','createdAt':100,'seconds':3}])
    (root/'program').write_bytes(b'program fixture');(root/'program').chmod(0o755);(root/'relative-link').symlink_to('program')
    write(root/'Data/corrections.json',{'enabled':True,'words':[{'term':'Claude','aliases':['Cloud'],'enabled':True,'case_sensitive':False}]})
    return root

def test_partial_draft_survives_reopen_and_valid_rules_apply(tmp_path):
    c=Corrections(tmp_path/'corrections.json');old=c.load();v={'enabled':True,'words':old['words']+[{'term':'还未填完','aliases':[]}]}
    result=c.save_draft(v,None);assert result['incomplete']==1 and result['draft_saved'] and result['applied']
    again=Corrections(c.path);assert again.draft()['value']['words'][-1]['term']=='还未填完'
    assert len(again.load()['words'])==1
    v['words'][-1]['aliases']=['识别错误'];result=again.save_draft(v,result['revision']);assert result['applied'] and len(again.load()['words'])==2

def test_conflicting_rules_still_save_draft_without_changing_effective_rules(tmp_path):
    c=Corrections(tmp_path/'corrections.json');c.save(c.load());before=c.path.read_bytes();v=c.load();v['words'].append({'term':'另一个词','aliases':['Cloud']})
    result=c.save_draft(v,c.draft()['revision']);assert result['draft_saved'] and not result['applied'] and c.path.read_bytes()==before
    assert Corrections(c.path).draft()['value']['words'][-1]['term']=='另一个词'

def test_stale_window_cannot_replace_newer_draft(tmp_path):
    c=Corrections(tmp_path/'corrections.json');v=c.load();r=c.save_draft(v,None)
    with pytest.raises(DraftConflict):c.save_draft({'enabled':False,'words':[]},None)
    assert c.draft()['revision']==r['revision']

@pytest.mark.parametrize('mode,expected',[('system',True),('direct',None),('manual','socks5://127.0.0.1:1080')])
def test_proxy_policy_is_local_and_explicit(tmp_path,mode,expected):
    s=RuntimeSettings(tmp_path);before=dict(__import__('os').environ);s.save({**s.load(),'proxy_mode':mode,'proxy_url':'socks5://127.0.0.1:1080' if mode=='manual' else ''})
    assert s.websocket_proxy()==expected and dict(__import__('os').environ)==before
    assert s.httpx_options()['trust_env']==(mode=='system')

@pytest.mark.parametrize('url',['http://user:secret@127.0.0.1:1','file:///tmp/proxy','http://a:99999','http://a:80/secret?token=x'])
def test_proxy_rejects_credentials_and_invalid_urls(tmp_path,url):
    s=RuntimeSettings(tmp_path)
    with pytest.raises(ValueError):s.save({**s.load(),'proxy_mode':'manual','proxy_url':url})
    assert not s.path.exists()

def test_diagnostic_log_drops_transcripts_and_credentials(tmp_path):
    append(tmp_path,'recognition',phase='done',seconds=2,updates=3,text='PRIVATE_TEXT_FIXTURE',credential='SECRET_FIXTURE',proxy_url='http://secret')
    contents=''.join(p.read_text() for p in (tmp_path/'logs').glob('*'))
    assert 'PRIVATE_TEXT_FIXTURE' not in contents and 'SECRET_FIXTURE' not in contents and 'http' not in contents
    assert recent(tmp_path)[0]['seconds']==2
    s=RuntimeSettings(tmp_path);s.save({**s.load(),'logs_enabled':False});append(tmp_path,'capture',phase='start');assert len(recent(tmp_path))==1

def test_httpx_system_proxy_reads_os_policy_and_respects_bypass(tmp_path,monkeypatch):
    monkeypatch.setattr('desktop.runtime_settings.getproxies',lambda:{'https':'http://127.0.0.1:6152'})
    monkeypatch.setattr('desktop.runtime_settings.proxy_bypass',lambda host:host=='localhost')
    settings=RuntimeSettings(tmp_path)
    assert settings.httpx_options('https://example.com')['proxy']=='http://127.0.0.1:6152'
    assert 'proxy' not in settings.httpx_options('http://localhost:8080')

def test_full_backup_relocates_program_data_and_executable_modes(tmp_path):
    root=tool(tmp_path);archive=tmp_path/'backup.zip';create_backup(root,archive);m=verify(archive);assert m['records']==1
    dest=tmp_path/'moved';restore_new(archive,dest)
    assert (dest/'Data/history.json').read_bytes()==(root/'Data/history.json').read_bytes()
    assert (dest/'relative-link').read_bytes()==b'program fixture' and (dest/'program').stat().st_mode&0o111
    with pytest.raises(ValueError):create_backup(root,root/'recursive.zip')
    with pytest.raises(ValueError):create_backup(root,archive)

def test_restore_merges_history_and_retains_new_records_and_prior_directory(tmp_path):
    root=tool(tmp_path);archive=tmp_path/'backup.zip';create_backup(root,archive)
    dest=tmp_path/'current';write(dest/'history.json',[{'id':'new','text':'新合成记录','createdAt':200,'seconds':4}]);result=restore_data(archive,dest)
    assert {r['id'] for r in json.loads((dest/'history.json').read_text())}=={'new','one'}
    assert Path(result['previous_data_folder']).is_dir()
    restore_data(archive,dest);assert len(json.loads((dest/'history.json').read_text()))==2

def test_restore_conflicts_do_not_overwrite_current_record(tmp_path):
    root=tool(tmp_path);archive=tmp_path/'backup.zip';create_backup(root,archive);dest=tmp_path/'current';write(dest/'history.json',[{'id':'one','text':'当前更新的合成记录','createdAt':200,'seconds':4}])
    r=restore_data(archive,dest);assert r['conflicts']==1
    assert json.loads((dest/'history.json').read_text())[0]['text']=='当前更新的合成记录'
    assert len(list((dest/'restore-preserved').rglob('history-conflicts.json')))==1

@pytest.mark.parametrize('name',['../escape','/absolute','a/../../escape','a\\escape','a//b','./a','C:drive'])
def test_backup_path_validation(name):
    with pytest.raises(ValueError):safe_name(name)

def test_backup_tampering_never_touches_destination(tmp_path):
    root=tool(tmp_path);archive=tmp_path/'backup.zip';create_backup(root,archive)
    damaged=tmp_path/'damaged.zip'
    with zipfile.ZipFile(archive) as old,zipfile.ZipFile(damaged,'w') as new:
        for info in old.infolist():new.writestr(info,b'changed' if info.filename==PREFIX+'program' else old.read(info.filename))
    dest=tmp_path/'current';write(dest/'history.json',[]);before=(dest/'history.json').read_bytes()
    with pytest.raises(ValueError):restore_data(damaged,dest)
    assert (dest/'history.json').read_bytes()==before
