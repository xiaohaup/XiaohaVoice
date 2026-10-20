"""Run frozen common regressions against the Windows component copies, offline."""
from pathlib import Path
import hashlib,os,shutil,subprocess,sys,tempfile,zipfile
from prepare_components import ROOT,UPSTREAM_SHA256

def main():
    source=ROOT/'upstream/source.zip'
    if not source.exists():source=ROOT.parent/'windows-handoff-20261020/source.zip'
    if hashlib.sha256(source.read_bytes()).hexdigest()!=UPSTREAM_SHA256:raise ValueError('上游测试包校验失败')
    chosen=['test_workbench.py','test_personalization.py','test_official_asr.py','test_service_setup.py','test_voice_improvements.py']
    with tempfile.TemporaryDirectory(prefix='xhvoice-regression-') as temporary:
        base=Path(temporary);tests=base/'tests';tests.mkdir();integration=base/'integration';integration.mkdir()
        with zipfile.ZipFile(source) as z:
            for name in chosen:(tests/name).write_bytes(z.read('sync-suite/tests/'+name))
        for name in ('personalization.py','volcengine_asr.py'):shutil.copy2(ROOT/'devkit/Components/engine'/name,integration/name)
        env=dict(os.environ,PYTHONPATH=os.pathsep.join([str(ROOT/'devkit/Components/workbench'),str(ROOT/'devkit/Components/engine')]),PYTHONUTF8='1')
        return subprocess.run([sys.executable,'-X','utf8','-m','pytest','--import-mode=importlib','-q',str(tests)],env=env,cwd=base).returncode
if __name__=='__main__':raise SystemExit(main())
