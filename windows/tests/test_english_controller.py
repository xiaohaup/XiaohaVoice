"""Controller methods with fake desktop adapters; never constructs a live host."""
import os,time
from types import SimpleNamespace as NS
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from xiaoha_windows.app import Controller
from xiaoha_windows.core import Session,Deliveries,History


def controller(tmp_path,session):
    calls=[]
    h=NS(data=tmp_path,closed=False,sessions={session.id:session},english_clients={},
         history=History(tmp_path),window=NS(announce_history=lambda:calls.append('history')),
         deliveries=Deliveries(),toolkit_status='',drain=lambda:calls.append('drain'),tick=lambda:calls.append('tick'))
    return h,calls


def test_ready_keeps_source_and_rejects_duplicate_or_old_generation(tmp_path):
    s=Session(recording=False,complete=True,text='保留原文',english_phase='translating',english_generation=2)
    h,calls=controller(tmp_path,s);h.history.add(s)
    Controller.english_done(h,s.id,1,{'ok':True,'text':'Stale.'});assert not calls
    Controller.english_done(h,s.id,2,{'ok':True,'text':'Retained source.'})
    assert s.text=='保留原文' and s.output_text=='Retained source.' and calls==['history','drain','tick']
    calls.clear();Controller.english_done(h,s.id,2,{'ok':True,'text':'Duplicate.'});assert not calls


def test_cancel_blocks_late_result_and_keeps_history(tmp_path):
    s=Session(recording=False,complete=True,text='原文',english_phase='translating',english_generation=1)
    h,calls=controller(tmp_path,s);h.history.add(s,s.text);h.english_clients[s.id]=NS(cancel=lambda:calls.append('cancel'))
    Controller.cancel_english(h,s)
    assert s.english_phase=='cancelled' and s.text=='原文' and calls==['cancel','drain']
    calls.clear();Controller.english_done(h,s.id,1,{'ok':True,'text':'Too late.'});assert not calls


def test_failure_releases_delivery_without_pasting_source(tmp_path):
    s=Session(recording=False,complete=True,text='原文',english_phase='translating',english_generation=1)
    h,calls=controller(tmp_path,s);h.history.add(s)
    Controller.english_done(h,s.id,1,{'ok':False,'error':'合成连接失败，原文已保留'})
    assert s.english_phase=='failed' and s.english_text=='' and s.text=='原文'
    h.deliveries.append(s.id);assert h.deliveries.begin(h.sessions) is None


def test_worker_translates_only_final_source_and_pins_config_revision(tmp_path,monkeypatch):
    import xiaoha_windows.translation as module
    s=Session(recording=False,complete=True,text='纠正后 Claude',english_configuration={'revision':'saved-r1'},english_phase='waiting')
    h,calls=controller(tmp_path,s);h.origin='http://127.0.0.1:18877'
    class Client:
        def __init__(self,origin,directory):assert origin==h.origin and directory==tmp_path/'desktop'
        def translate(self,text,revision):calls.append((text,revision));return {'ok':True,'text':'Claude.'}
    monkeypatch.setattr(module,'LocalEnglishClient',Client)
    h.english_workers=NS(submit=lambda fn:fn());h.english_finished=NS(emit=lambda *args:calls.append(args))
    Controller.translate_english(h,s)
    assert s.english_pending and calls[0]==('纠正后 Claude','saved-r1')
    assert calls[1]==(s.id,1,{'ok':True,'text':'Claude.'})


def test_retry_translates_existing_text_and_copies_only(tmp_path):
    s=Session(recording=False,complete=True,text='保留原文',english_phase='failed')
    h,calls=controller(tmp_path,s);h.active=None;h.english_config=lambda:{'revision':'new'}
    h.translate_english=lambda value:calls.append(value.id);h.capsule=NS(present=lambda:calls.append('present'))
    Controller.retry(h,s.id)
    assert s.english_retry_copies_only and s.english_configuration=={'revision':'new'} and list(h.deliveries.ids)==[s.id]
    assert calls==[s.id,'present']
