"""Versioned full-toolkit backup and loss-preserving, transactional data restore."""
from __future__ import annotations
from pathlib import Path, PurePosixPath
import hashlib, json, os, shutil, stat, tempfile, time, zipfile
import unicodedata
from datetime import datetime, timezone
from uuid import uuid4

MAX_TOTAL=4_000_000_000
PREFIX="小哈语音工具包/"
MANIFEST=PREFIX+"备份清单.json"
def digest(data):return hashlib.sha256(data).hexdigest()
def read(path):return json.loads(Path(path).read_bytes())
def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    path.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':')))
    os.chmod(path,0o600)
def safe_name(name):
    p=PurePosixPath(name)
    if not name or str(p)!=name or p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name or '\x00' in name:raise ValueError('备份含不安全路径')
    return p
def summary(data):
    native=read(data/'history.json') if (data/'history.json').exists() else []
    imported=read(data/'imports/shandianshuo/records.json').get('records',[]) if (data/'imports/shandianshuo/records.json').exists() else []
    return {'records':len(native)+len(imported),'native_records':len(native),'imported_records':len(imported)}

def snapshot(root):
    result={}
    for p in root.rglob('*'):
        rel=p.relative_to(root)
        if rel.parts[0].startswith(('Data-before-restore-','.restore-')) or rel.as_posix()=='备份清单.json':continue
        info=p.lstat()
        if stat.S_ISDIR(info.st_mode):continue
        result[rel.as_posix()]=(info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
    return result

def create_backup(root,output):
    root,output=Path(root).resolve(),Path(output).resolve()
    if not (root/'toolkit.json').is_file() or not (root/'Data').is_dir():raise ValueError('请选择完整的小哈语音工具包')
    if output==root or root in output.parents:raise ValueError('备份请保存在工具包外，避免把备份再次装入自身')
    if output.exists():raise ValueError('同名备份已存在，请换一个名字；原备份没有改变')
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_name(output.name+'.partial-'+uuid4().hex)
    initial=snapshot(root)
    manifest={'format':'xiaoha-voice-backup','version':1,'created':datetime.now(timezone.utc).isoformat(),'platform':'macOS-arm64','files':{},**summary(root/'Data')}
    stamps={};total=0
    try:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=4) as z:
            os.chmod(temporary,0o600)
            for p in sorted(root.rglob('*')):
                if p.relative_to(root).parts[0].startswith(('Data-before-restore-','.restore-')) or p.relative_to(root).as_posix()=='备份清单.json':continue
                if p.is_dir() and not p.is_symlink():continue
                rel=p.relative_to(root).as_posix();safe_name(rel)
                before=p.lstat();mode=stat.S_IMODE(before.st_mode)
                if not stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(before.st_mode):raise ValueError('工具包含非普通文件，备份已停止')
                if p.is_symlink():
                    target=os.readlink(p)
                    if Path(target).is_absolute() or not p.resolve().is_relative_to(root):raise ValueError('程序含指向工具包外的链接，备份已停止')
                    payload=target.encode();kind='link';zi=zipfile.ZipInfo(PREFIX+rel);zi.external_attr=(stat.S_IFLNK|mode)<<16;z.writestr(zi,payload)
                else:
                    payload=p.read_bytes();kind='file';zi=zipfile.ZipInfo(PREFIX+rel);zi.external_attr=(stat.S_IFREG|mode)<<16;zi.compress_type=zipfile.ZIP_DEFLATED;z.writestr(zi,payload)
                total+=len(payload)
                if total>MAX_TOTAL:raise ValueError('工具包超过当前备份大小限制')
                after=p.lstat()
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('资料仍在变化，请停止录音并稍后重新备份')
                stamps[rel]=(after.st_size,after.st_mtime_ns)
                manifest['files'][rel]={'sha256':digest(payload),'size':len(payload),'mode':mode,'kind':kind}
            for rel,stamp in stamps.items():
                now=(root/rel).lstat()
                if stamp!=(now.st_size,now.st_mtime_ns):raise ValueError('备份期间资料已更新，原资料未变，请重新备份')
            if snapshot(root)!=initial:raise ValueError('备份期间资料已更新，原资料未变，请重新备份')
            z.writestr(MANIFEST,json.dumps(manifest,ensure_ascii=False))
        verify(temporary)
        os.replace(temporary,output)
        return {k:manifest[k] for k in ('created','records','native_records','imported_records')}
    finally:
        if temporary.exists():temporary.unlink()

def verify(archive):
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist()
        if len(infos)>50000 or sum(i.file_size for i in infos)>MAX_TOTAL:raise ValueError('备份体积或文件数超限')
        if len({i.filename for i in infos})!=len(infos):raise ValueError('备份含重复路径')
        normalized={unicodedata.normalize('NFC',i.filename).casefold() for i in infos}
        if len(normalized)!=len(infos):raise ValueError('备份含大小写或字符形式冲突的路径')
        if any(i.file_size>512_000_000 for i in infos):raise ValueError('备份含过大的单个文件')
        if z.getinfo(MANIFEST).file_size>10_000_000:raise ValueError('备份清单超限')
        m=json.loads(z.read(MANIFEST))
        if m.get('format')!='xiaoha-voice-backup' or m.get('version')!=1 or not isinstance(m.get('files'),dict):raise ValueError('备份格式无法识别')
        if {i.filename for i in infos}!={MANIFEST,*(PREFIX+k for k in m['files'])}:raise ValueError('备份文件与清单不一致')
        for name,meta in m['files'].items():
            p=safe_name(name);payload=z.read(PREFIX+name)
            if len(payload)!=meta['size'] or digest(payload)!=meta['sha256'] or meta['kind'] not in ('file','link'):raise ValueError('备份校验失败，原资料没有改变')
            if meta['kind']=='link':
                target=payload.decode();dest=Path('/safe')/str(p.parent)/target
                if Path(target).is_absolute() or not dest.resolve().is_relative_to('/safe'):raise ValueError('备份链接超出工具包')
            if p.parts[0]=='Data' and meta['kind']!='file':raise ValueError('资料目录不接受符号链接')
        return m

def extract_verified(archive,destination,data_only=False):
    m=verify(archive);destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        for kind in ('file','link'):
            for name,meta in m['files'].items():
                parts=safe_name(name).parts
                if meta['kind']!=kind or data_only and parts[0]!='Data':continue
                p=destination.joinpath(*(parts[1:] if data_only else parts));p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                payload=z.read(PREFIX+name)
                if kind=='link':p.symlink_to(payload.decode())
                else:p.write_bytes(payload);os.chmod(p,meta['mode'] if not data_only else 0o600)
    if not data_only:
        for p in destination.rglob('*'):
            if p.is_symlink() and not p.resolve().is_relative_to(destination.resolve()):raise ValueError('恢复链接校验失败')
    return m

def restore_new(archive,destination):
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('完整工具包恢复需选择一个尚不存在的新文件夹')
    return extract_verified(archive,destination)

def merge_rows(current,incoming):
    if not isinstance(current,list) or not isinstance(incoming,list):raise ValueError('历史格式无效，未执行恢复')
    byid={str(r['id']).lower():r for r in current};result=list(current);conflicts=[];added=0
    for row in incoming:
        rid=str(row['id']).lower()
        if rid not in byid:result.append(row);byid[rid]=row;added+=1
        elif byid[rid]!=row:conflicts.append(row)
    return result,added,conflicts

def restore_data(archive,data):
    m=verify(archive);data=Path(data).resolve();data.parent.mkdir(parents=True,exist_ok=True)
    stage=data.with_name('.restore-stage-'+uuid4().hex);incoming=data.with_name('.restore-input-'+uuid4().hex)
    rollback=data.with_name('Data-before-restore-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:6])
    result={'added':0,'conflicts':0,'originals_preserved':True}
    try:
        extract_verified(archive,incoming,data_only=True)
        if data.exists():shutil.copytree(data,stage)
        else:stage.mkdir(mode=0o700)
        retained=stage/'restore-preserved'/uuid4().hex[:12]
        for p in incoming.rglob('*'):
            if not p.is_file():continue
            rel=p.relative_to(incoming);out=stage/rel
            if not out.exists():out.parent.mkdir(parents=True,exist_ok=True,mode=0o700);shutil.copy2(p,out);os.chmod(out,0o600);continue
            if out.read_bytes()==p.read_bytes():continue
            if rel.as_posix()=='history.json':
                rows,added,conflicts=merge_rows(read(out),read(p));dump(out,rows);result['added']+=added
                if conflicts:dump(retained/'history-conflicts.json',conflicts);result['conflicts']+=len(conflicts)
            elif rel.as_posix()=='imports/shandianshuo/records.json':
                cur,other=read(out),read(p);rows,added,conflicts=merge_rows(cur['records'],other['records']);cur['records']=rows
                cur['summary']['completed_records']=len(rows);cur['summary']['characters']=sum(r.get('source_characters',0) for r in rows);cur['summary']['seconds']=sum(r['seconds'] for r in rows);dump(out,cur);result['added']+=added
                if conflicts:dump(retained/'import-conflicts.json',conflicts);result['conflicts']+=len(conflicts)
            elif rel.name in ('corrections.json','sync-wordbook.json'):
                cur,other=read(out),read(p);known={(w['term'],tuple(w['aliases'])) for w in cur.get('words',[])}
                targets={a.casefold():w['term'] for w in cur.get('words',[]) if w.get('enabled',True) for a in w['aliases']}
                for word in other.get('words',[]):
                    if (word['term'],tuple(word['aliases'])) not in known:
                        if len(cur.get('words',[]))>=500:result['conflicts']+=1;continue
                        if any(a.casefold() in targets and targets[a.casefold()]!=word['term'] for a in word['aliases']):word={**word,'enabled':False};result['conflicts']+=1
                        cur.setdefault('words',[]).append(word);known.add((word['term'],tuple(word['aliases'])))
                dump(out,cur)
                original=retained/rel;original.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,original)
            else:
                # Existing settings, credentials and drafts remain authoritative;
                # every different incoming original is retained for inspection.
                original=retained/rel;original.parent.mkdir(parents=True,exist_ok=True,mode=0o700);shutil.copy2(p,original);result['conflicts']+=1
        for p in stage.rglob('*'):os.chmod(p,0o700 if p.is_dir() else 0o600)
        had_data=data.exists()
        if had_data:os.rename(data,rollback)
        try:os.rename(stage,data)
        except Exception:
            if had_data:os.rename(rollback,data)
            raise
        return {**result,**summary(data),'previous_data_folder':str(rollback) if had_data else None}
    finally:
        if stage.exists():shutil.rmtree(stage)
        if incoming.exists():shutil.rmtree(incoming)
