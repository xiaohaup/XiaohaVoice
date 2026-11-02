"""Verify preview sources without reading installed user data or credentials."""
from pathlib import Path
import argparse,hashlib,json,subprocess

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'versions/voice-0.4.1-preview.1/source-manifest.json'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--write-manifest',action='store_true');args=parser.parse_args()
    names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
    names=sorted(set(n for n in names if n and n!=MANIFEST.relative_to(ROOT).as_posix()))
    private=[n for n in names if any(p in {'Data','private','personal-fixtures','devkit','.venv','__pycache__'} for p in Path(n).parts)
             or Path(n).name in {'translation-settings.json','device.json','asr-settings.json','runtime-settings.json','history.json'}]
    if private:raise ValueError('Private files in source inventory: '+', '.join(private))
    hashes={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names if (ROOT/n).is_file()}
    if args.write_manifest:
        MANIFEST.parent.mkdir(parents=True,exist_ok=True)
        MANIFEST.write_text(json.dumps({'version':'0.4.1-preview.1','files':hashes},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    expected=json.loads(MANIFEST.read_text(encoding='utf-8'))['files']
    wrong=sorted(n for n,h in expected.items() if hashes.get(n)!=h)
    extra=sorted(set(hashes)-set(expected))
    result={'ok':not(wrong or extra),'source_files':len(expected),'mismatches':wrong,'extra_files':extra,'private_files':private,'personal_data_read':False}
    print(json.dumps(result,ensure_ascii=False));return 0 if result['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
