"""Synthetic sessions and local transport only; no OS input, mic or real vault."""
import hashlib,json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from xiaoha_windows.core import Session,Deliveries,History,EnglishGesture,Shortcut
from xiaoha_windows.translation import LocalEnglishClient


def test_normal_and_english_output_keep_delivery_order():
    a=Session(recording=False,text='原文',complete=True,english_phase='translating')
    b=Session(recording=False,text='下一句',complete=True)
    q=Deliveries();q.append(a.id);q.append(b.id);sessions={a.id:a,b.id:b}
    assert q.begin(sessions) is None
    a.english_text='Original.';a.english_phase='ready'
    assert a.output_text=='Original.' and a.text=='原文'
    assert q.begin(sessions)==a.id
    q.finish(a.id)
    assert q.begin(sessions)==b.id and b.output_text=='下一句'


@pytest.mark.parametrize('phase',['failed','cancelled'])
def test_failed_translation_never_auto_delivers_chinese(phase):
    a=Session(recording=False,complete=True,text='保留原文',english_phase=phase)
    b=Session(recording=False,complete=True,text='正常句')
    q=Deliveries();q.append(a.id);q.append(b.id)
    assert q.begin({a.id:a,b.id:b})==b.id
    assert a.text=='保留原文'


def test_translation_history_association_counts_source_once(tmp_path):
    history=History(tmp_path);s=Session(recording=False,text='与 Claude 开会',complete=True,completed_seconds=3)
    history.add(s,s.text);history.associate_english(s.id,'Meet Claude.');history.associate_english(s.id,'Meet Claude tomorrow.')
    rows=json.loads(history.path.read_text(encoding='utf-8'))
    assert len(rows)==1 and rows[0]['text']==s.text and rows[0]['seconds']==3
    assert rows[0]['english']=='Meet Claude tomorrow.'


def test_short_right_ctrl_is_ending_but_chords_long_press_and_injection_are_not():
    now=[0.0];g=EnglishGesture(Shortcut(163,0,'右 Ctrl'),clock=lambda:now[0])
    assert not g.key(163,True);now[0]=.15;assert g.key(163,False)
    for key in (67,86):
        assert not g.key(163,True);assert not g.key(key,True)
        assert not g.key(key,False);assert not g.key(163,False)
    g.key(163,True);now[0]+=1;assert not g.key(163,False)
    assert not g.key(163,True,True) and not g.key(163,False,True)


def test_custom_function_chord_and_mouse_endings():
    g=EnglishGesture(Shortcut(119,0,'F8'))
    assert not g.key(119,True);assert g.key(119,False)
    g=EnglishGesture(Shortcut(83,2,'Ctrl+S'))
    g.key(162,True);g.key(83,True);assert g.key(83,False);g.key(162,False)
    g=EnglishGesture(Shortcut(0,0,'鼠标侧键 4',4))
    assert not g.mouse(4,True);assert g.mouse(4,False)
    g.mouse(4,True);g.mouse(1,True);assert not g.mouse(4,False)


class Response:
    status=200
    def __init__(self,value,headers=None):self.data=json.dumps(value).encode();self.headers=headers or []
    def read(self,limit):return self.data[:limit]
    def getheaders(self):return self.headers


def local_transport(monkeypatch,tmp_path,wrong_owner=False,redirect=False):
    import xiaoha_windows.translation as module
    calls=[]
    class Connection:
        sock=None
        def __init__(self,host,port,timeout):
            assert host=='127.0.0.1' and port==18877
        def request(self,method,path,body=None,headers=None):
            calls.append((method,path,json.loads(body) if body else None,headers))
        def close(self):pass
        def getresponse(self):
            path=calls[-1][1]
            if path=='/api/health':
                value={'service':'bad' if wrong_owner else 'xiaoha-voice-companion','protocol':3,'instance':hashlib.sha256(str(tmp_path.resolve()).encode()).hexdigest()}
                r=Response(value)
                if redirect:r.status=302
                return r
            if path=='/workbench':return Response({},[('Set-Cookie','xh_workbench=local-only; HttpOnly; SameSite=Strict')])
            if path=='/workbench/api/status':return Response({'csrf':'local-csrf'})
            if path=='/workbench/api/translation-run':return Response({'ok':True,'text':'Meet Claude.','milliseconds':15})
            raise AssertionError(path)
    monkeypatch.setattr(module.http.client,'HTTPConnection',Connection)
    return LocalEnglishClient('http://127.0.0.1:18877',tmp_path),calls


def test_local_owner_transport_passes_final_text_without_api_key(monkeypatch,tmp_path):
    client,calls=local_transport(monkeypatch,tmp_path)
    assert client.translate('最终纠正的 Claude。','saved-r1')['text']=='Meet Claude.'
    assert [c[1] for c in calls]==['/api/health','/workbench','/workbench/api/status','/workbench/api/translation-run']
    assert calls[-1][2]=={'text':'最终纠正的 Claude。','revision':'saved-r1'}
    assert calls[-1][3]['Cookie']=='xh_workbench=local-only'
    assert calls[-1][3]['X-CSRF-Token']=='local-csrf'
    assert all('Authorization' not in c[3] for c in calls)


@pytest.mark.parametrize('mode',['wrong_owner','redirect'])
def test_other_local_service_is_rejected_before_text_submission(monkeypatch,tmp_path,mode):
    client,calls=local_transport(monkeypatch,tmp_path,**{mode:True})
    with pytest.raises(ValueError):client.translate('未发送原文','r1')
    assert len(calls)==1 and calls[0][2] is None


def test_cancel_before_start_never_connects(monkeypatch,tmp_path):
    client,calls=local_transport(monkeypatch,tmp_path);client.cancel()
    with pytest.raises(ValueError):client.translate('不发送','r1')
    assert calls==[]


@pytest.mark.parametrize('origin',['https://127.0.0.1:18766','http://example.com:18766','http://127.0.0.1:18766/other','http://user:secret@127.0.0.1:18766'])
def test_client_only_connects_to_own_loopback_origin(tmp_path,origin):
    with pytest.raises(ValueError):LocalEnglishClient(origin,tmp_path)


def test_silent_or_escaped_english_session_does_not_remain_busy():
    s=Session(english_phase='waiting');s.cancel()
    assert s.cancelled and not s.english_pending and s.english_generation==1
