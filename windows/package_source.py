"""Allowlisted, self-contained, data-free Windows source handoff."""
from pathlib import Path
import hashlib,json,zipfile
from prepare_components import ROOT,UPSTREAM_SHA256

TOP=['main.py','runtime_entry.py','prepare_components.py','vendor_opus.py','build_windows.py','verify_shared.py','package_source.py',
     'build.cmd','start-dev.cmd','app.manifest','requirements-windows.txt','dependencies.lock.json','README.md','THIRD-PARTY.md']

def build(destination):
    destination=Path(destination)
    if destination.exists():raise ValueError('同名交接包已存在，未覆盖')
    files=[ROOT/p for p in TOP]
    files += [p for folder in ('xiaoha_windows','tests') for p in (ROOT/folder).glob('*.py')]
    files += [ROOT/'upstream/source.zip',ROOT/'upstream/source-manifest.json',ROOT/'vendor/libopus-1.6.1-h6a83c73_1.conda']
    if hashlib.sha256((ROOT/'upstream/source.zip').read_bytes()).hexdigest()!=UPSTREAM_SHA256:raise ValueError('共同组件包哈希不匹配')
    payload={}
    for path in sorted(files):
        if not path.is_file() or path.is_symlink():raise ValueError('交接成员缺失或含链接')
        name=path.relative_to(ROOT).as_posix()
        if any(p in name.split('/') for p in ('Data','.venv','devkit','private','__pycache__')):raise ValueError('交接成员超出白名单')
        payload[name]=path.read_bytes()
    manifest={name:hashlib.sha256(value).hexdigest() for name,value in payload.items()}
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED) as z:
        for name,value in payload.items():z.writestr(name,value)
        z.writestr('source-manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(destination) as z:
        if set(z.namelist())!=set(manifest)|{'source-manifest.json'}:raise ValueError('交接包成员与清单不符')
        for name,digest in manifest.items():
            if hashlib.sha256(z.read(name)).hexdigest()!=digest:raise ValueError('交接包读回不符')
    report={'name':destination.name,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'bytes':destination.stat().st_size,'source_files':len(manifest),
            'private_data_included':False,'mac_identity_included':False,'windows_exe_built':False,'files':manifest}
    destination.with_suffix('.verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='files'},ensure_ascii=False))
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('destination',type=Path);a=p.parse_args();build(a.destination)
