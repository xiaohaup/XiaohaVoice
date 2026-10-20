from pathlib import Path
import importlib.util,json,pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('vendor_opus',ROOT/'vendor_opus.py');vendor=importlib.util.module_from_spec(spec);spec.loader.exec_module(vendor)

def test_official_opus_is_pinned_x64_and_never_loaded(tmp_path):
    report=vendor.extract(tmp_path)
    assert report['architecture']=='AMD64' and report['loaded'] is False
    assert report['dll_sha256']=='39b603e3d9594748f9d08ebd3f5b5afb2b4976181f9162497487aafa26d54805'
    assert (tmp_path/'LICENSES/Opus-COPYING.txt').read_text().strip()

def test_tampered_opus_is_rejected_before_writing(tmp_path):
    bad=tmp_path/'bad.conda';bad.write_bytes(b'no')
    with pytest.raises(ValueError): vendor.extract(tmp_path/'out',bad)
    assert not (tmp_path/'out').exists()

def test_builder_isolates_external_dll_search_without_changing_parent(monkeypatch):
    import os,sys,subprocess
    if os.name!='nt':pytest.skip('Windows build environment')
    import build_windows
    original=os.environ['PATH']
    polluted=original+os.pathsep+r'C:\unrelated-pdf-tool\bin'
    monkeypatch.setenv('PATH',polluted)
    calls=[]
    monkeypatch.setattr(subprocess,'run',lambda args,**kwargs:calls.append((args,kwargs)))
    build_windows.run([sys.executable,'-m','PyInstaller','--version'])
    child_path=calls[0][1]['env']['PATH']
    assert 'unrelated-pdf-tool' not in child_path
    assert str(Path(os.environ['SystemRoot'])/'System32') in child_path
    assert os.environ['PATH']==polluted and calls[0][1]['creationflags']==subprocess.CREATE_NO_WINDOW

