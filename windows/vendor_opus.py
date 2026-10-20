"""Extract only the pinned Windows x64 Opus DLL and its upstream license."""
from pathlib import Path
import hashlib,io,json,struct,tarfile,zipfile
import zstandard
ROOT=Path(__file__).resolve().parent

def extract(toolkit,package=None):
    lock=json.loads((ROOT/'dependencies.lock.json').read_text(encoding='utf-8'))['opus']
    package=Path(package or ROOT/'vendor'/lock['package']);raw=package.read_bytes()
    if len(raw)!=lock['bytes'] or hashlib.sha256(raw).hexdigest()!=lock['sha256']: raise ValueError('Opus依赖包校验失败')
    found={}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for name in archive.namelist():
            if not name.endswith('.tar.zst'): continue
            with archive.open(name) as compressed, zstandard.ZstdDecompressor().stream_reader(compressed) as stream, tarfile.open(fileobj=stream,mode='r|') as tar:
                for member in tar:
                    if member.name not in ('Library/bin/opus.dll','info/licenses/COPYING'): continue
                    if not member.isfile() or member.size>2_000_000 or member.name in found: raise ValueError('Opus成员无效')
                    found[member.name]=tar.extractfile(member).read()
    if set(found)!= {'Library/bin/opus.dll','info/licenses/COPYING'}: raise ValueError('Opus依赖成员缺失')
    dll=found['Library/bin/opus.dll']
    offset=struct.unpack_from('<I',dll,0x3c)[0] if len(dll)>64 and dll[:2]==b'MZ' else -1
    if offset<0 or dll[offset:offset+4]!=b'PE\0\0' or struct.unpack_from('<H',dll,offset+4)[0]!=0x8664: raise ValueError('Opus不是Windows x64 DLL')
    toolkit=Path(toolkit)
    for name,payload in [('Components/engine/opus.dll',dll),('LICENSES/Opus-COPYING.txt',found['info/licenses/COPYING'])]:
        dest=toolkit/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(payload)
    return {'package_sha256':lock['sha256'],'dll_sha256':hashlib.sha256(dll).hexdigest(),'architecture':'AMD64','loaded':False}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('toolkit',type=Path);a=p.parse_args();print(json.dumps(extract(a.toolkit)))
