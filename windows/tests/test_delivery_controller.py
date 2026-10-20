"""Controller-level delivery with fake OS adapters: never sends OS input."""
import os,sys,json,time
from pathlib import Path
from types import SimpleNamespace as NS
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'devkit/Components/workbench'))
from xiaoha_windows.app import Controller
from xiaoha_windows.core import Session,Deliveries

def host(tmp_path,settings=None,match=True,insert=True):
    # Load exactly the runtime preference file used by the controller.
    (tmp_path/'runtime-settings.json').write_text(json.dumps(settings or {}),encoding='utf-8')
    calls=[];s=Session(recording=False,complete=True,text='第一句');s.target=NS(pid=500)
    deliveries=Deliveries();deliveries.append(s.id);deliveries.begin({s.id:s})
    h=NS(data=tmp_path,deliveries=deliveries,displayed=s,paste_test_status='',
         clipboard=NS(stage=lambda text,keep:calls.append(('stage',text,keep)) or (1,2)),
         windows=NS(modifiers_down=lambda:False,matches=lambda target:match,paste_keys=lambda:calls.append(('paste',)) or True),
         capsule=NS(line=NS(setText=lambda message:None)),diagnostic=lambda *a,**kw:None,
         hide_if_current=lambda *a:None,drain=lambda:None,restore_clipboard=lambda *a:calls.append(('restore',)),
         window=NS(insert=lambda token,text,done:done(insert)))
    return h,s,calls

def test_normal_delivery_leaves_transcript_on_clipboard(tmp_path):
    h,s,calls=host(tmp_path,{'auto_paste':True,'keep_transcription':True})
    Controller.deliver(h,s,time.monotonic())
    assert calls==[('stage','第一句',True),('paste',)] and not h.deliveries.ids

def test_restore_requested_only_after_actual_paste(tmp_path):
    h,s,calls=host(tmp_path,{'auto_paste':True,'keep_transcription':False})
    Controller.deliver(h,s,time.monotonic())
    assert calls==[('stage','第一句',False),('paste',),('restore',)]

def test_changed_target_copies_without_sending_keys(tmp_path):
    h,s,calls=host(tmp_path,{'auto_paste':True,'keep_transcription':False},match=False)
    Controller.deliver(h,s,time.monotonic())
    assert calls==[('stage','第一句',False)] and '目标已改变' in s.delivery

def test_copy_only_never_sends_keys_or_restores(tmp_path):
    h,s,calls=host(tmp_path,{'auto_paste':False,'keep_transcription':False})
    Controller.deliver(h,s,time.monotonic())
    assert calls==[('stage','第一句',True)] and s.delivery=='已复制到剪贴板'

def test_failed_own_field_insertion_copies_fallback(tmp_path):
    h,s,calls=host(tmp_path,{'auto_paste':True,'keep_transcription':False},insert=False);s.local_token='field'
    Controller.deliver(h,s,time.monotonic())
    assert calls==[('stage','第一句',True)] and '文字已复制' in s.delivery
