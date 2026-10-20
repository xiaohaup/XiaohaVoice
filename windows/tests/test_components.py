from pathlib import Path
import importlib.util,json,sys,pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('prepare_components',ROOT/'prepare_components.py');prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)
UPSTREAM=ROOT/'upstream/source.zip' if (ROOT/'upstream/source.zip').exists() else ROOT.parent/'windows-handoff-20261020/source.zip'
@pytest.fixture(scope='module')
def components(tmp_path_factory):
    target=tmp_path_factory.mktemp('components');prepare.prepare(UPSTREAM,target);return target

def test_platform_ui_keeps_browser_option_apis(components):
    text=(components/'Components/workbench/web/workbench.js').read_text()
    assert 'selectedOptions' in text and 'selectedAlts' not in text
    assert '"AltRight": 165' in text and "keyCode:165,modifiers:0,label:'右 Alt'" in text

def test_platform_labels_are_windows_specific(components):
    text=(components/'Components/workbench/web/workbench.html').read_text()
    assert '在任务栏显示' in text and '系统托盘' in text and '在 Dock 中显示' not in text

def test_no_upstream_data_or_identity(components):
    assert not list((components/'Data').iterdir())
    assert not (components/'Components/engine/private').exists()
    assert json.loads((components/'toolkit.json').read_text())['platform']=='Windows-x64'

def test_fchmod_is_optional_for_windows(components):
    assert "if hasattr(os,'fchmod')" in (components/'Components/engine/channel_probe.py').read_text()

def test_backup_rejects_windows_devices_and_aliases(components):
    path=components/'Components/workbench/desktop/toolkit_archive.py'
    spec=importlib.util.spec_from_file_location('win_backup',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for name in ('Data/CON','Data/aux.json','Data/COM1','Data/name.','Data/name ','Data/path:stream','../escape','Data/foo\\bar'):
        with pytest.raises(ValueError): module.safe_name(name)
    assert str(module.safe_name('Data/词库.json'))=='Data/词库.json'

def test_backup_platform_and_loss_preserving_restore(components,tmp_path):
    path=components/'Components/workbench/desktop/toolkit_archive.py';spec=importlib.util.spec_from_file_location('win_backup2',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    data=components/'Data';(data/'history.json').write_text('[{"id":"a","text":"old","seconds":1}]')
    archive=tmp_path/'backup.zip';module.create_backup(components,archive);assert module.verify(archive)['platform']=='Windows-x64'
    current=tmp_path/'current';current.mkdir();(current/'history.json').write_text('[{"id":"a","text":"new","seconds":2},{"id":"b","text":"keep","seconds":3}]')
    module.restore_data(archive,current)
    assert json.loads((current/'history.json').read_text())[0]['text']=='new'
    assert len(json.loads((current/'history.json').read_text()))==2
    assert list((current/'restore-preserved').rglob('history-conflicts.json'))

def test_upstream_tampering_is_rejected(tmp_path):
    p=tmp_path/'bad.zip';p.write_bytes(b'no');
    with pytest.raises(ValueError): prepare.prepare(p,tmp_path/'out')

def test_windows_history_import_preserves_native_and_is_idempotent(components,tmp_path):
    import subprocess,hashlib
    native=tmp_path/'Data/history.json';native.parent.mkdir();native.write_text('[{"id":"native","text":"保留"}]',encoding='utf-8')
    original=native.read_bytes()
    source=tmp_path/'source.json'
    source.write_text(json.dumps({'version':'1.0','records':[{'id':'one','status':'success','record_type':'voice_input','text':'迁入文字','duration_ms':1000,'timestamp':1700000000}]},ensure_ascii=False),encoding='utf-8')
    command=[sys.executable,'-X','utf8','-m','desktop.import_shandianshuo','--source',str(source),'--history',str(native),'--apply']
    first=json.loads(subprocess.check_output(command,cwd=components/'Components/workbench',encoding='utf-8'))
    ledger=native.parent/'imports/shandianshuo/records.json';digest=hashlib.sha256(ledger.read_bytes()).hexdigest()
    second=json.loads(subprocess.check_output(command,cwd=components/'Components/workbench',encoding='utf-8'))
    assert first['added']==1 and second['unchanged'] and second['added']==second['updated']==0
    assert hashlib.sha256(ledger.read_bytes()).hexdigest()==digest and native.read_bytes()==original
    assert json.loads(ledger.read_text(encoding='utf-8'))['records'][0]['text']=='迁入文字'

def test_restore_rejects_existing_link_without_mutating(components,tmp_path):
    path=components/'Components/workbench/desktop/toolkit_archive.py';spec=importlib.util.spec_from_file_location('win_backup3',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    data=tmp_path/'current';data.mkdir();outside=tmp_path/'outside';outside.write_text('keep')
    try: (data/'linked').symlink_to(outside)
    except OSError: pytest.skip('This target does not permit test symlinks')
    with pytest.raises(ValueError): module.restore_data(tmp_path/'irrelevant.zip',data)
    assert outside.read_text()=='keep' and (data/'linked').is_symlink()
