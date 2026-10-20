"""Offline source-integrity check. Does not contact ASR or read installed user data."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'versions/macos-0.3.8-build12/source-manifest.json'


def main():
    expected = json.loads(MANIFEST.read_text())['files']
    wrong = []
    for name, sha in expected.items():
        path = ROOT / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            wrong.append(name)
    private = [str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file()
               and not set(p.relative_to(ROOT).parts).intersection(('.git', '.venv', 'build', 'builds', 'dist', 'diagnostics', '__pycache__')) and any(x in p.relative_to(ROOT).parts
               for x in ('Data', 'private', 'personal-fixtures'))]
    print(json.dumps({'source_files': len(expected), 'mismatches': wrong,
                      'private_files': private, 'ok': not wrong and not private}, ensure_ascii=False))
    return 1 if wrong or private else 0


if __name__ == '__main__':
    sys.exit(main())
