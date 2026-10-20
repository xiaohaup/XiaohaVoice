"""Build a clean portable Windows toolkit. No audio, registration or startup changes."""
from pathlib import Path
import argparse,hashlib,importlib.metadata as metadata,json,os,platform,shutil,struct,subprocess,sys,time,zipfile
from prepare_components import prepare,UPSTREAM_SHA256
from vendor_opus import extract
ROOT=Path(__file__).resolve().parent

def run(args):
    # Build tools can inherit unrelated DLL directories (for example Poppler's
    # versioned ICU). Qt uses Windows' ICU shim; never resolve against host tools.
    env=dict(os.environ)
    system=Path(os.environ['SystemRoot'])
    env['PATH']=os.pathsep.join(dict.fromkeys(str(p) for p in
        (Path(sys.executable).parent,Path(sys._base_executable).parent,system/'System32',system)))
    subprocess.run([str(x) for x in args],check=True,cwd=ROOT,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
def hashes(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}
def licenses(target):
    records=[]
    for dist in metadata.distributions():
        name=dist.metadata['Name'];version=dist.version
        # Preserve all installed dependency license notices, even for optional build tools.
        record={'name':name,'version':version,'license':dist.metadata.get('License-Expression') or dist.metadata.get('License','')[:1000],'files':[]}
        for file in dist.files or []:
            lower=str(file).lower()
            if '.dist-info/' not in lower or not any(x in lower for x in ('license','copying','notice')): continue
            source=dist.locate_file(file)
            if not source.is_file() or source.stat().st_size>5_000_000: continue
            relative=Path(*Path(str(file)).parts[1:])
            dest=target/'LICENSES'/name/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest);record['files'].append(dest.relative_to(target).as_posix())
        records.append(record)
    (target/'LICENSES/dependencies.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')

def build(output):
    if sys.platform!='win32' or struct.calcsize('P')!=8 or platform.machine().upper() not in ('AMD64','X86_64'):
        raise SystemExit('请在目标Windows x64电脑用64位Python构建；不能从Mac产出已验证EXE。')
    if not (3,12)<=sys.version_info[:2]<(3,16): raise SystemExit('需要Python 3.12至3.15（64位）')
    expected={'PySide6':'6.12.0','pyinstaller':'6.22.3','pyinstaller-hooks-contrib':'2026.8','zstandard':'0.25.0'}
    for name,version in expected.items():
        if metadata.version(name)!=version: raise SystemExit('请先在独立环境安装锁定依赖：'+name+'=='+version)
    output=Path(output).resolve()
    if output.exists(): raise SystemExit('输出目录已存在，请换一个新目录；未覆盖任何工具包。')
    output.parent.mkdir(parents=True,exist_ok=True)
    work=ROOT/'build'/time.strftime('%Y%m%d-%H%M%S')
    work.mkdir(parents=True,exist_ok=False)
    stage=work/'components';upstream=ROOT/'upstream/source.zip'
    if not upstream.exists(): upstream=ROOT.parent/'windows-handoff-20261020/source.zip'
    prepare(upstream,stage);opus=extract(stage)
    from PySide6.QtWidgets import QApplication
    from xiaoha_windows.qt_ui import make_icon
    app=QApplication.instance() or QApplication([]);icon=work/'voice.ico'
    if not make_icon(stage).pixmap(256,256).save(str(icon),'ICO'): raise RuntimeError('图标生成失败')
    search=[stage/'Components/workbench',stage/'Components/engine',ROOT]
    common=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--noupx','--python-option','X utf8=1','--distpath',work/'dist','--workpath',work/'pyinstaller','--specpath',work]
    for path in search: common += ['--paths',path]
    run(common+['--windowed','--name','xiaoha-voice','--manifest',ROOT/'app.manifest','--icon',icon,ROOT/'main.py'])
    runtime=common+['--console','--name','xiaoha-runtime','--hidden-import','channel_probe','--hidden-import','volcengine_asr','--hidden-import','personalization',
        '--hidden-import','keyring.backends.Windows','--hidden-import','keyring.backends.chainer','--collect-submodules','desktop',
        '--collect-submodules','uvicorn','--collect-submodules','python_socks','--collect-all','jieba','--collect-data','certifi','--collect-data','tzdata',ROOT/'runtime_entry.py']
    run(runtime)
    shutil.copytree(work/'dist/xiaoha-voice',output)
    (output/'xiaoha-voice.exe').rename(output/'小哈语音.exe')
    shutil.copytree(work/'dist/xiaoha-runtime',output/'Runtime/xiaoha-runtime')
    for name in ('Components','Data','LICENSES'): shutil.copytree(stage/name,output/name)
    shutil.copy2(stage/'toolkit.json',output/'toolkit.json')
    for name in ('README.md','dependencies.lock.json','requirements-windows.txt','THIRD-PARTY.md'):
        shutil.copy2(ROOT/name,output/name)
    shutil.copy2(icon,output/'小哈语音.ico');licenses(output)
    # A real runtime check exercises bundled Opus, without network or microphone.
    from xiaoha_windows.services import environment
    checked=subprocess.run([str(output/'Runtime/xiaoha-runtime/xiaoha-runtime.exe'),'selfcheck'],env=environment(output),capture_output=True,check=True,text=True,encoding='utf-8',timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    result=json.loads(checked.stdout.strip())
    if result!={'runtime':True,'opus':True,'network_called':False,'microphone_opened':False}: raise RuntimeError('运行组件自检未通过')
    # Import the real frozen GUI dependencies too. A console runtime/Opus pass
    # cannot detect incompatible Qt DLLs in the GUI package.
    gui_check=work/'gui-selfcheck.json'
    subprocess.run([str(output/'小哈语音.exe'),'--toolkit',str(output),'--selfcheck',str(gui_check)],
                   env=environment(output),check=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    gui_result=json.loads(gui_check.read_text('utf-8'))
    if not all(gui_result.get(k) is True for k in ('qt','webengine','multimedia')): raise RuntimeError('桌面组件自检未通过')
    if list((output/'Data').iterdir()): raise RuntimeError('发布包必须保持空资料目录')
    manifest={'version':'0.4.0-preview.1','platform':'Windows-x64','python':platform.python_version(),'upstream_sha256':UPSTREAM_SHA256,'opus':opus,'selfcheck':result,'gui_selfcheck':gui_result,'files':hashes(output)}
    (output/'distribution-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=output.with_name(output.name+'.zip')
    if archive.exists(): raise ValueError('同名ZIP已存在；原包未覆盖')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=4) as z:
        z.writestr(output.name+'/Data/',b'')
        for p in sorted(output.rglob('*')):
            if p.is_file(): z.write(p,output.name+'/'+p.relative_to(output).as_posix())
    with zipfile.ZipFile(archive) as z:
        for name,digest in manifest['files'].items():
            if hashlib.sha256(z.read(output.name+'/'+name)).hexdigest()!=digest: raise RuntimeError('发布ZIP读回校验失败')
    report={'output':str(output),'archive':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'selfcheck':result,'gui_selfcheck':gui_result,'private_records':0,'target_ui_accepted':False}
    (work/'build-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();build(a.output)
