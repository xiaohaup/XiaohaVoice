"""Resource lifetime tests with synthetic children; no capture or network."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'devkit/Components/workbench'))

import pytest
from PySide6.QtWidgets import QApplication
from xiaoha_windows import app,services
from xiaoha_windows.core import Session,Deliveries


@pytest.fixture(scope='module')
def qt():
    application=QApplication.instance() or QApplication([])
    yield application


def child(monkeypatch,tmp_path,script):
    # Use the interpreter itself: a Windows venv redirector is an extra parent
    # retaining pipe handles, unlike the shipped native runtime executable.
    interpreter=getattr(sys,'_base_executable',sys.executable)
    monkeypatch.setattr(services,'runtime_command',lambda *args:[interpreter,'-u','-c',script])
    return services.Speech(tmp_path,Session(recording=False))


def test_repeated_completed_children_release_pipes_and_workers(monkeypatch,tmp_path,qt):
    exits=[]
    for _ in range(20):
        bridge=child(monkeypatch,tmp_path,"print('{\"event\":\"done\",\"text\":\"synthetic\"}',flush=True)")
        process=bridge.process
        events=[]
        bridge.event.connect(lambda sid,generation,event:events.append(event))
        bridge.exited.connect(lambda sid,generation,code:exits.append(code))
        bridge.start()
        assert bridge.wait_finished(4)
        qt.processEvents()
        assert process.returncode==0 and process.stdin.closed and process.stdout.closed
        assert bridge.process is None and bridge.queue.empty()
        assert events==[{'event':'done','text':'synthetic'}]
        bridge.deleteLater()
    assert exits==[0]*20


def test_cancel_reaps_owned_child_and_pending_audio(monkeypatch,tmp_path,qt):
    bridge=child(monkeypatch,tmp_path,'import time; time.sleep(60)')
    process=bridge.process
    bridge.audio(b'\x00\x00'*1600)
    bridge.start(); bridge.cancel()
    assert bridge.wait_finished(4)
    assert process.poll() is not None and process.stdin.closed and process.stdout.closed
    assert bridge.queue.empty() and not bridge.audio(b'\x00\x00') and not bridge.finish()
    bridge.deleteLater()


def test_stdout_eof_does_not_leave_a_waiting_child(monkeypatch,tmp_path,qt):
    # Windows can retain its inherited standard handle after closing CRT fd 1.
    script="""import os,time,sys
sys.stdout.close()
if os.name=='nt':
 import ctypes
 kernel=ctypes.WinDLL('kernel32',use_last_error=True)
 kernel.GetStdHandle.restype=ctypes.c_void_p
 kernel.CloseHandle.argtypes=[ctypes.c_void_p]
 kernel.CloseHandle(kernel.GetStdHandle(-11))
else:
 try: os.close(1)
 except OSError: pass
time.sleep(60)
"""
    bridge=child(monkeypatch,tmp_path,script)
    process=bridge.process
    bridge.start()
    try:
        assert bridge.wait_finished(5)
        assert process.poll() is not None and process.stdin.closed and process.stdout.closed
    finally:
        bridge.cancel(); bridge.wait_finished(4); bridge.deleteLater()


class Bridge:
    def __init__(self,sid,generation,finished=False):
        self.sid=sid; self.generation=generation; self.finished=finished; self.deleted=0
    def deleteLater(self): self.deleted+=1
    def cancel(self): self.cancelled=True


def controller():
    return NS(sessions={},bridges={},retired_bridges=set(),active=None,displayed=None,
              deliveries=Deliveries(),resolve_failure=lambda *args:None)


def test_late_old_exit_cannot_retire_a_retry_or_change_its_state():
    h=controller(); session=Session(recording=False,generation=1,retrying=True)
    current=Bridge(session.id,1); old=Bridge(session.id,0)
    h.sessions[session.id]=session; h.bridges[session.id]=current; h.retired_bridges.add(old)
    app.Controller.bridge_exited(h,session.id,0,1)
    assert h.bridges[session.id] is current and current not in h.retired_bridges
    assert session.failure is None and session.retrying


def test_completed_exit_retires_bridge_before_session_early_return():
    h=controller(); session=Session(recording=False,complete=True,text='saved',delivery='copied')
    bridge=Bridge(session.id,session.generation)
    h.sessions[session.id]=session; h.bridges[session.id]=bridge
    app.Controller.bridge_exited(h,session.id,session.generation,0)
    assert not h.bridges and bridge in h.retired_bridges
    app.Controller.reap_bridges(h)
    assert bridge.deleted==0
    bridge.finished=True
    app.Controller.reap_bridges(h)
    assert bridge.deleted==1 and not h.retired_bridges
    assert session.complete and session.failure is None


def test_discarded_synthetic_recovery_keeps_bridge_until_threads_end():
    h=controller(); session=Session(recording=False,failure='synthetic')
    bridge=Bridge(session.id,session.generation)
    h.sessions[session.id]=session; h.bridges[session.id]=bridge
    h.windows=NS(trash=lambda path:None)
    h.recovery=NS(save=lambda session:None,discard=lambda sid,trash:None)
    assert app.Controller.dispatch(h,'discardRecovery',{'id':session.id,'confirmed':True})=={'ok':True}
    assert not h.sessions and not h.bridges and bridge in h.retired_bridges and bridge.cancelled
    app.Controller.reap_bridges(h)
    assert not bridge.deleted


def test_many_deliveries_are_bounded_without_losing_recoverable_or_live_sessions():
    h=controller()
    active=Session(); displayed=Session(recording=False,complete=True,text='display',delivery='copied')
    failed=Session(recording=False,failure='retained',pcm=bytearray(b'\x00\x00'))
    restored=Session(recording=False,restored=True,pcm=bytearray(b'\x00\x00'))
    waiting=Session(recording=False,complete=True,text='not delivered yet')
    queued=Session(recording=False,complete=True,text='delivering',delivery='retained')
    retiring=Session(recording=False,complete=True,text='child still closing',delivery='copied')
    protected=[active,displayed,failed,restored,waiting,queued,retiring]
    h.sessions.update((session.id,session) for session in protected)
    h.active=active; h.displayed=displayed; h.deliveries.append(queued.id); h.deliveries.busy=True
    h.retired_bridges.add(Bridge(retiring.id,0))
    completed=[]
    for number in range(200):
        session=Session(recording=False,complete=True,text=f'saved {number}',delivery='copied')
        h.sessions[session.id]=session; completed.append(session.id)
        app.Controller.prune_sessions(h)
    assert all(h.sessions[session.id] is session for session in protected)
    assert [sid for sid in completed if sid in h.sessions]==completed[-32:]
    assert len(h.sessions)==len(protected)+32
    assert failed.pcm and restored.pcm and h.deliveries.busy
