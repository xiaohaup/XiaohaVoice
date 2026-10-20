"""Build Windows-only component copies from the frozen, hash-verified Mac source.
Never reads or copies Mac Data, credentials, identity, histories or recordings.
"""
from pathlib import Path
import argparse,hashlib,json,re,zipfile
UPSTREAM_SHA256='7d28087d8d0f6b37c5b36ad722eeca63c6db38dda2ecd65ff4a9597c83bde7f7'
ROOT=Path(__file__).resolve().parent

def prepare(source, output):
    source,output=Path(source),Path(output)
    if hashlib.sha256(source.read_bytes()).hexdigest()!=UPSTREAM_SHA256: raise ValueError('上游源码包哈希不匹配')
    output.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        manifest=json.loads(archive.read('source-manifest.json'))
        if set(archive.namelist())!=set(manifest)|{'source-manifest.json'}: raise ValueError('源码清单不一致')
        for name,digest in manifest.items():
            payload=archive.read(name)
            if hashlib.sha256(payload).hexdigest()!=digest: raise ValueError('源码成员校验失败')
            destination=None
            if name.startswith(('sync-suite/web/','sync-suite/desktop/','sync-suite/server/')):
                destination=output/'Components/workbench'/name.removeprefix('sync-suite/')
            elif name.startswith('ime-channel-test/'):
                destination=output/'Components/engine'/name.removeprefix('ime-channel-test/')
            if destination:
                if not destination.resolve().is_relative_to(output.resolve()): raise ValueError('源码路径无效')
                destination.parent.mkdir(parents=True,exist_ok=True); destination.write_bytes(payload)
    engine=output/'Components/engine/channel_probe.py'
    text=engine.read_text(encoding='utf-8').replace('os.fchmod(f.fileno(),0o600)',"\n        if hasattr(os,'fchmod'): os.fchmod(f.fileno(),0o600)")
    engine.write_text(text,encoding='utf-8')
    backup=output/'Components/workbench/desktop/toolkit_archive.py'
    text=backup.read_text(encoding='utf-8').replace("'platform':'macOS-arm64'","'platform':read(root/'toolkit.json').get('platform','Windows-x64')")
    text=text.replace('    return p\n', '''    reserved={'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
    if any(part.rstrip(' .')!=part or part.split('.')[0].upper() in reserved or any(c in part for c in '<>"|?*') for part in p.parts):raise ValueError('备份含Windows不安全路径')
    return p
''',1)
    text=text.replace("target=payload.decode();dest=Path('/safe')/str(p.parent)/target", "target=payload.decode();safe_root=Path('/safe').resolve();dest=safe_root/str(p.parent)/target").replace("dest.resolve().is_relative_to('/safe')","dest.resolve().is_relative_to(safe_root)")
    text=text.replace("rel=p.relative_to(root).as_posix();safe_name(rel)","rel=p.relative_to(root).as_posix();safe_name(rel)\n                if getattr(p,'is_junction',lambda:False)():raise ValueError('工具包不接受目录联接')\n                if not p.is_symlink() and not p.resolve().is_relative_to(root):raise ValueError('工具包文件超出目录')")
    text=text.replace('def restore_data(archive,data):', '''def validate_data_tree(data):
    data=Path(data)
    for p in (data,*data.rglob('*')):
        if p.is_symlink() or getattr(p,'is_junction',lambda:False)():raise ValueError('现有资料含链接，未执行恢复')
def restore_data(archive,data):
    validate_data_tree(data)''')
    text=text.replace('                if p.is_dir() and not p.is_symlink():continue', "                if getattr(p,'is_junction',lambda:False)():raise ValueError('工具包含目录联接，未执行备份')\n                if p.is_dir() and not p.is_symlink():continue")
    backup.write_text(text,encoding='utf-8')
    importer=output/'Components/workbench/desktop/import_shandianshuo.py'
    text=importer.read_text(encoding='utf-8')
    text=text.replace('        os.fchmod(fd, 0o600)',"        if hasattr(os,'fchmod'): os.fchmod(fd, 0o600)")
    text=text.replace('old_path.read_text()',"old_path.read_text(encoding='utf-8')")
    text=text.replace('ledger_path.read_text()',"ledger_path.read_text(encoding='utf-8')")
    importer.write_text(text,encoding='utf-8')
    web=output/'Components/workbench/web';script=web/'workbench.js';text=script.read_text(encoding='utf-8')
    keys={'AltRight':165,'AltLeft':164,'MetaLeft':91,'MetaRight':92,'ShiftLeft':160,'ShiftRight':161,'ControlLeft':162,'ControlRight':163,'Space':32,'Enter':13,'Tab':9,'Backquote':192,'Slash':191}
    keys.update({f'F{i}':111+i for i in range(1,13)});keys.update({f'Key{x}':ord(x) for x in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'})
    text,count=re.subn(r'const keyMap=\{[^\n]+\};','const keyMap='+json.dumps(keys)+';',text,count=1)
    if count!=1: raise ValueError('快捷键平台化锚点不匹配')
    for old,new in [('0x20000','4'),('0x40000','2'),('0x80000','1'),('0x100000','8')]: text=text.replace(old,new)
    text=text.replace("keyCode:61,modifiers:0,label:'右 Option'","keyCode:165,modifiers:0,label:'右 Alt'")
    text=text.replace(' Option',' Alt').replace(' Command',' Win').replace("'Option'","'Alt'").replace("'Command'","'Win'")
    text=text.replace('废纸篓','回收站').replace('钥匙串','Windows凭据管理器')
    # This copy runs only in the Windows host. Do not present macOS TCC grants as Windows permissions.
    text=text.replace("(s[key]?'已允许':'待允许')","(key==='microphone'?(s[key]?'检测到输入设备':'未发现输入设备'):key==='input_monitoring'?(s[key]?'已启用':'未启用'):'适用于普通权限窗口')")
    text=text.replace("row.append(make('span',name+' · '","if(key==='microphone')b.textContent='系统设置';else b.hidden=true;row.append(make('span',name+' · '")
    script.write_text(text,encoding='utf-8')
    html=web/'workbench.html';text=html.read_text(encoding='utf-8').replace('右 Option','右 Alt').replace('Option / Command / Shift','Alt / Win / Shift').replace('在 Dock 中显示','在任务栏显示').replace('菜单栏','系统托盘')
    text=text.replace('Control 留给原输入法；请避开其他软件已绑定的键。','右 Alt 可能与 AltGr 冲突，可换用功能键或鼠标侧键。').replace('系统权限','系统与输入状态').replace('只在这里管理系统授权。','自动粘贴受 Windows 窗口权限限制。')
    text=text.replace('废纸篓','回收站').replace('钥匙串','Windows凭据管理器')
    html.write_text(text,encoding='utf-8')
    (output/'Data').mkdir(exist_ok=True)
    (output/'toolkit.json').write_text(json.dumps({'format':1,'name':'小哈语音','version':'0.4.0-preview.1','platform':'Windows-x64','data':'Data','cloud_deployed':False},ensure_ascii=False,indent=2),encoding='utf-8')
    return output

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path);p.add_argument('--output',type=Path,default=ROOT/'devkit');a=p.parse_args()
    source=a.source or (ROOT/'upstream/source.zip' if (ROOT/'upstream/source.zip').exists() else ROOT.parent/'windows-handoff-20261020/source.zip')
    prepare(source,a.output);print(json.dumps({'components_prepared':True,'source_sha256':UPSTREAM_SHA256,'private_data_copied':False}))
if __name__=='__main__':main()
