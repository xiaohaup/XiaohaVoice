"""Clipboard ownership logic with an in-memory Win32 adapter, no OS clipboard."""
from types import SimpleNamespace as NS
from xiaoha_windows.win32 import Clipboard

def fixture():
    state={'sequence':10,'opens':0,'closes':0,'writes':[]}
    def opened(owner):state['opens']+=1;return True
    def closed():state['closes']+=1
    user=NS(GetClipboardSequenceNumber=lambda:state['sequence'],GetClipboardOwner=lambda:123,OpenClipboard=opened,CloseClipboard=closed)
    c=Clipboard(NS(user=user),123);c.original=[(13,b'old')];c.owned=10;c.generation=1
    c._write_open=lambda rows:state['writes'].append(rows)
    return c,state

def test_new_user_copy_is_never_overwritten_by_restore():
    c,s=fixture();s['sequence']=11
    assert c.restore((1,10)) is False and not s['writes'] and c.original is None

def test_new_transcription_invalidates_previous_restore():
    c,s=fixture();c.generation=2
    assert c.restore((1,10)) is False and not s['writes'] and c.original

def test_partial_format_failure_retains_snapshot_for_bounded_retry():
    c,s=fixture();attempts=[]
    def write(rows):
        attempts.append(rows);s['sequence']+=1
        if len(attempts)==1:raise OSError('synthetic format failure')
    c._write_open=write
    assert not c.restore((1,10)) and c.original and c.owned==11
    assert c.restore((1,10)) and c.original is None and len(attempts)==2
    assert s['opens']==s['closes']==2

def test_user_copy_between_retry_attempts_is_preserved():
    c,s=fixture()
    def failed(rows):s['sequence']+=1;raise OSError()
    c._write_open=failed;assert not c.restore((1,10))
    s['sequence']+=1
    c._write_open=lambda rows:s['writes'].append(rows)
    assert not c.restore((1,10)) and not s['writes'] and c.original is None

def test_stage_claims_version_after_windows_synthesizes_formats_on_close():
    c,s=fixture()
    c.windows.user.CloseClipboard=lambda:s.update(sequence=s['sequence']+3)
    token=c.stage('synthetic',False)
    assert token==(2,13) and c.owned==s['sequence'] and c.original==[(13,b'old')]
    assert c.restore(token)

def test_other_owner_after_stage_keeps_the_new_copy():
    import pytest
    c,s=fixture()
    c.windows.user.GetClipboardOwner=lambda:456
    with pytest.raises(ValueError,match='已被其他应用更新'):c.stage('synthetic',False)
    assert c.original is None and c.owned is None and len(s['writes'])==1

def test_partial_restore_claims_the_post_close_version_for_retry():
    c,s=fixture();attempts=[]
    c.windows.user.CloseClipboard=lambda:s.update(sequence=s['sequence']+3)
    def write(rows):
        attempts.append(rows);s['sequence']+=1
        if len(attempts)==1:raise OSError('synthetic partial write')
    c._write_open=write
    assert not c.restore((1,10)) and c.owned==14 and c.original
    assert c.restore((1,10)) and c.original is None

def test_owner_is_resolved_again_after_qt_recreates_its_window():
    c,s=fixture();current=[123];opened=[]
    c._owner=lambda:current[0]
    c.windows.user.OpenClipboard=lambda owner:opened.append(owner) or True
    c.windows.user.GetClipboardOwner=lambda:current[0]
    c.stage('first',True)
    current[0]=456
    c.stage('second',True)
    assert opened==[123,456] and c.owner==456
