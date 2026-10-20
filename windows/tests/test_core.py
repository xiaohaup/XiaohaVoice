from pathlib import Path
from array import array
import math,json,pytest
from xiaoha_windows.core import Session,Activity,Deliveries,History,Recovery,Shortcut,Gesture,PCM16Converter


def pcm(value=0,frames=320): return array('h',[value]*frames).tobytes()

def test_short_accidental_tap_is_not_recovery():
    session=Session(); session.append(pcm(0,1600)); session.recording=False
    assert session.disposition('failed')=='quiet'

def test_long_failed_connection_is_not_proof_of_silence():
    session=Session(); session.append(pcm(0,32000)); session.recording=False
    assert session.disposition('failed')=='retain'
    assert session.disposition('empty')=='quiet'

def test_sustained_quiet_speech_is_preserved():
    session=Session(); session.append(pcm(100,1600)); session.recording=False
    assert session.disposition('empty')=='retain'

def test_two_strong_frames_preserve_a_quick_word():
    session=Session(); session.append(pcm(300,640)); session.recording=False
    assert session.disposition('failed')=='retain'

def test_existing_text_and_restored_audio_are_preserved():
    session=Session(text='嗯'); session.append(pcm()); session.recording=False
    assert session.disposition('empty')=='retain'
    session.text=''; session.restored=True
    assert session.disposition('empty')=='retain'

def test_no_policy_stops_an_active_recording():
    session=Session(); session.append(pcm()); assert session.disposition('empty')=='wait'

def test_cancel_drops_only_current_memory():
    session=Session(text='不要保存'); session.append(pcm(300)); old=session.generation; session.cancel()
    assert session.cancelled and session.complete and not session.pcm and not session.text and session.generation>old

def test_delivery_follows_stop_order_even_when_second_finishes_first():
    a,b=Session(),Session(); a.recording=b.recording=False
    queue=Deliveries(); queue.append(a.id); queue.append(b.id); b.finish('第二句')
    sessions={a.id:a,b.id:b}; assert queue.begin(sessions) is None
    a.finish('第一句'); assert queue.begin(sessions)==a.id
    assert queue.begin(sessions) is None
    queue.finish(a.id); assert queue.begin(sessions)==b.id

def test_new_capture_does_not_invalidate_previous_result():
    old=Session(); old.recording=False; old.finish('完成'); new=Session()
    queue=Deliveries(); queue.append(old.id)
    assert queue.begin({old.id:old,new.id:new})==old.id

def test_cancelled_or_failed_head_does_not_block_later_result():
    a,b=Session(),Session(); a.cancel(); b.finish('后续')
    queue=Deliveries(); queue.append(a.id); queue.append(b.id)
    assert queue.begin({a.id:a,b.id:b})==b.id

def test_local_field_callback_is_required_before_delivery():
    session=Session(); session.finish('文字'); session.target_ready=False
    queue=Deliveries(); queue.append(session.id)
    assert queue.begin({session.id:session}) is None
    session.target_ready=True; assert queue.begin({session.id:session})==session.id

def test_history_is_durable_and_uuid_deduplicated(tmp_path):
    h=History(tmp_path); s=Session(); s.append(pcm(300,16000)); s.recording=False
    assert h.add(s,'Claude','Cloud'); assert not h.add(s,'Claude')
    row=json.loads(h.path.read_text())[0]
    assert row['seconds']==1 and row['original_text']=='Cloud' and row['text']=='Claude'

def test_corrupt_history_is_not_overwritten(tmp_path):
    h=History(tmp_path); h.path.write_text('{broken')
    with pytest.raises(ValueError): h.add(Session(),'hello')
    assert h.path.read_text()=='{broken'

def test_recovery_roundtrip_and_completed_exclusion(tmp_path):
    r=Recovery(tmp_path); s=Session(text='草稿'); s.append(pcm(300)); s.recording=False; r.save(s)
    restored,issues=r.load([]); assert not issues and restored[0].pcm==s.pcm and restored[0].restored
    assert r.load([s.id])[0]==[]

def test_recovery_traversal_and_mismatched_identity_rejected(tmp_path):
    r=Recovery(tmp_path)
    with pytest.raises(ValueError): r.folder('../../other')
    s=Session(); s.append(pcm()); r.save(s); info=r.folder(s.id)/'record.json'
    data=json.loads(info.read_text()); data['id']=Session().id; info.write_text(json.dumps(data))
    assert r.load([])[0]==[] and len(r.load([])[1])==1

def test_recycle_adapter_receives_exact_uuid_folder(tmp_path):
    r=Recovery(tmp_path); s=Session(); s.append(pcm()); r.save(s); captured=[]
    r.discard(s.id,captured.append)
    assert captured==[r.folder(s.id)] and r.folder(s.id).exists()

def test_recycle_failure_retains_original(tmp_path):
    r=Recovery(tmp_path); s=Session(); s.append(pcm()); r.save(s)
    def fail(_): raise OSError()
    with pytest.raises(OSError): r.discard(s.id,fail)
    assert (r.folder(s.id)/'audio.pcm').exists()

@pytest.mark.parametrize('key,mods,valid',[(165,0,True),(0x78,0,True),(65,0,False),(65,2,True),(27,2,False),(165,2,False),(65,32,False)])
def test_shortcut_validation(key,mods,valid): assert Shortcut(key,mods).validate()==valid

def test_modifier_gesture_triggers_on_release_once():
    g=Gesture(); assert not g.key(165,True); assert not g.key(165,True); assert g.key(165,False); assert not g.key(165,False)

def test_normal_chord_using_dedicated_modifier_does_not_toggle():
    g=Gesture(); g.key(165,True); g.key(65,True); g.key(65,False); assert not g.key(165,False)

def test_other_key_held_before_modifier_does_not_toggle():
    g=Gesture(); g.key(65,True); g.key(165,True); assert not g.key(165,False)

def test_injected_paste_never_triggers_voice():
    g=Gesture(Shortcut(0x56,2)); g.key(0xA2,True,True); g.key(0x56,True,True); assert not g.key(0x56,False,True)

def test_combination_and_mouse_rules():
    g=Gesture(Shortcut(65,2)); g.key(0xA2,True); g.key(65,True); assert g.key(65,False)
    assert Shortcut(0,0,'鼠标',4).validate(); assert not Shortcut(0,0,'鼠标',1).validate()

def test_wasapi_resampling_is_independent_of_callback_boundaries():
    raw=array('f',[.3*math.sin(i/48000*2*math.pi*440) for i in range(48000) for _ in range(2)]).tobytes()
    one=PCM16Converter(48000,2,'float'); expected=one.feed(raw)+one.finish()
    stream=PCM16Converter(48000,2,'float'); actual=b''.join(stream.feed(raw[i:i+773]) for i in range(0,len(raw),773))+stream.finish()
    assert actual==expected and len(actual)==32000
    assert max(array('h',actual))>9000

def test_16khz_native_int16_is_not_modified():
    raw=pcm(1234,16000); converter=PCM16Converter(16000,1,'int16')
    output=b''.join(converter.feed(raw[i:i+617]) for i in range(0,len(raw),617))+converter.finish()
    assert output==raw

def test_bad_device_format_rejected():
    with pytest.raises(ValueError): PCM16Converter(0,2,'float')
