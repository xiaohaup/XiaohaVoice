"""Bounded diagnostic metadata only. Never accept transcript/credential fields."""
from datetime import datetime, timezone, timedelta
import json, os, re, threading
from pathlib import Path
from desktop.runtime_settings import RuntimeSettings
LOCK=threading.RLock()
FIELDS={'time','event','provider','phase','seconds','updates','connection_ms','finish_wait_ms','status','error_kind','characters'}
EVENTS={'capture','recognition','delivery','settings','backup','restore','initialize','network'}
def clean(value):
    result={}
    for k,v in value.items():
        if k not in FIELDS: continue
        if k in ('seconds','updates','connection_ms','finish_wait_ms','status','characters'):
            if type(v) in (int,float) and __import__('math').isfinite(v) and v>=0: result[k]=v
        elif isinstance(v,str) and len(v)<=60 and re.fullmatch(r'[A-Za-z0-9_:T.\-+ Z]+',v):result[k]=v
    return result
def append(directory,event,**fields):
    if event not in EVENTS or not RuntimeSettings(directory).load()['logs_enabled']:return
    folder=Path(directory)/'logs';folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    row=clean({'time':datetime.now(timezone.utc).isoformat(),'event':event,**fields})
    path=folder/f'runtime-{os.getpid()}.jsonl'
    with LOCK:
        if path.exists() and path.stat().st_size>262144:path=folder/f'runtime-{os.getpid()}-{int(__import__("time").time())}.jsonl'
        fd=os.open(path,os.O_CREAT|os.O_WRONLY|os.O_APPEND,0o600)
        with os.fdopen(fd,'a') as f:f.write(json.dumps(row,separators=(',',':'))+'\n')
        files=sorted(folder.glob('runtime-*.jsonl'),key=lambda p:p.stat().st_mtime,reverse=True)
        cutoff=datetime.now().timestamp()-7*86400
        for old in files:
            if old==path:continue
            if old.stat().st_mtime<cutoff or files.index(old)>=40:old.unlink()
def recent(directory,limit=200):
    folder=Path(directory)/'logs';rows=[]
    for p in sorted(folder.glob('runtime-*.jsonl'),key=lambda p:p.stat().st_mtime,reverse=True)[:40]:
        if p.stat().st_size>1048576:continue
        for line in p.read_text(errors='replace').splitlines()[-limit:]:
            try:
                row=clean(json.loads(line))
                if row.get('event') in EVENTS:rows.append(row)
            except (ValueError,TypeError,AttributeError):continue
    return sorted(rows,key=lambda r:r.get('time',''),reverse=True)[:limit]
