"""Platform independent capture, recovery and ordered-delivery rules.
No microphones, networking, OS input or user data are accessed on import.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
from array import array
import json, math, os, sys


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(',', ':'))
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != 'nt': path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def load_json(path, fallback):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError: return fallback


@dataclass
class Activity:
    """Energy evidence only; never interrupts capture or claims to detect speech."""
    tail: bytes = b''
    run: int = 0
    active_frames: int = 0
    longest: int = 0
    strong_run: int = 0
    longest_strong: int = 0
    last_rms: float = 0

    def append(self, pcm):
        frames = self.tail + pcm
        end = len(frames)//640*640
        for offset in range(0, end, 640):
            samples = array('h', frames[offset:offset+640])
            if sys.byteorder != 'little': samples.byteswap()
            self.last_rms = math.sqrt(sum((x/32768)**2 for x in samples)/320)
            self.run = self.run+1 if self.last_rms >= .002 else 0
            self.strong_run = self.strong_run+1 if self.last_rms >= .006 else 0
            self.active_frames += self.last_rms >= .002
            self.longest = max(self.longest, self.run)
            self.longest_strong = max(self.longest_strong, self.strong_run)
        self.tail = frames[end:]

    @property
    def sustained(self):
        return self.longest >= 5 or self.active_frames >= 12 or self.longest_strong >= 2


@dataclass
class Session:
    id: str = field(default_factory=lambda: str(uuid4()).upper())
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    pcm: bytearray = field(default_factory=bytearray)
    activity: Activity = field(default_factory=Activity)
    text: str = ''
    original_text: str = ''
    recording: bool = True
    complete: bool = False
    cancelled: bool = False
    restored: bool = False
    retrying: bool = False
    failure: str | None = None
    target: object = None
    local_token: str | None = None
    target_ready: bool = True
    application: str | None = None
    generation: int = 0
    sent: int = 0
    ready: bool = False
    stop_sent: bool = False
    completed_seconds: float = 0
    delivery: str = ''

    @property
    def seconds(self): return len(self.pcm)/32000 if self.pcm else self.completed_seconds
    @property
    def has_text(self): return bool(self.text.strip())

    def append(self, pcm):
        if not self.recording: return
        if not isinstance(pcm, bytes) or len(pcm)%2: raise ValueError('录音格式无效')
        self.pcm.extend(pcm); self.activity.append(pcm)

    def disposition(self, ending):
        if self.recording: return 'wait'
        if self.complete or self.restored or self.has_text or self.activity.sustained: return 'retain'
        return 'quiet' if ending == 'empty' or self.seconds <= 1 else 'retain'

    def cancel(self):
        self.generation += 1; self.completed_seconds = self.seconds
        self.cancelled = self.complete = True; self.recording = self.retrying = self.ready = False
        self.pcm.clear(); self.text = ''; self.failure = None; self.target = None

    def finish(self, text):
        self.completed_seconds = self.seconds; self.text = text
        self.complete = True; self.recording = self.retrying = self.ready = False; self.failure = None
        self.pcm.clear()

    def retry(self):
        self.generation += 1; self.ready = self.stop_sent = False; self.sent = 0
        self.failure = None; self.retrying = True


class Deliveries:
    def __init__(self): self.ids = deque(); self.busy = False
    def append(self, sid):
        if sid not in self.ids: self.ids.append(sid)
    def begin(self, sessions):
        if self.busy: return None
        while self.ids:
            sid = self.ids[0]; session = sessions.get(sid)
            if not session or session.cancelled or session.failure:
                self.ids.popleft(); continue
            if not session.complete or not session.target_ready: return None
            self.busy = True; return sid
        return None
    def finish(self, sid):
        try: self.ids.remove(sid)
        except ValueError: pass
        self.busy = False


class History:
    def __init__(self, directory): self.path = Path(directory)/'history.json'
    def add(self, session, text, original=''):
        rows = load_json(self.path, [])
        if not isinstance(rows, list): raise ValueError('历史格式异常，原文件未覆盖')
        if any(str(row.get('id','')).casefold() == session.id.casefold() for row in rows): return False
        row = {'id':session.id,'created_at':session.created_at,'text':text,
               'seconds':session.seconds,'application':session.application}
        if original and original != text: row['original_text'] = original
        rows.append(row); atomic_json(self.path, rows); return True


class Recovery:
    def __init__(self, directory): self.root = Path(directory)/'recovery'
    def folder(self, sid):
        folder=self.root/str(UUID(sid)).upper()
        for p in (self.root,folder):
            if p.is_symlink() or getattr(p,'is_junction',lambda:False)(): raise OSError('录音路径含链接，原资料未修改')
        if not folder.resolve().is_relative_to(self.root.resolve()): raise OSError('录音路径无效')
        return folder
    def save(self, session):
        if session.complete or not session.pcm: return
        folder = self.folder(session.id); folder.mkdir(parents=True, exist_ok=True)
        pcm = folder/'audio.pcm'; temporary = folder/'audio.pending'
        if any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in (pcm,temporary,folder/'record.json')): raise OSError('录音文件含链接，原资料未修改')
        with temporary.open('wb') as stream:
            stream.write(session.pcm); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, pcm)
        if os.name != 'nt': pcm.chmod(0o600)
        atomic_json(folder/'record.json', {'id':session.id,'created_at':session.created_at,
                    'text':session.text,'seconds':session.seconds,'application':session.application})
    def load(self, completed):
        result, issues = [], []
        if not self.root.exists(): return result, issues
        if self.root.is_symlink() or getattr(self.root,'is_junction',lambda:False)(): return [],['recovery:linked-directory']
        completed = {str(x).casefold() for x in completed}
        for folder in self.root.iterdir():
            if not folder.is_dir() or folder.is_symlink(): continue
            try:
                sid = str(UUID(folder.name)).upper(); self.folder(sid)
                if sid.casefold() in completed: continue
                value = load_json(folder/'record.json', {})
                if str(UUID(value['id'])).upper() != sid: raise ValueError()
                audio = folder/'audio.pcm'
                if audio.is_symlink() or (folder/'record.json').is_symlink(): raise ValueError()
                if not 0 < audio.stat().st_size <= 512_000_000 or audio.stat().st_size%2: raise ValueError()
                stamp = value.get('created_at', value.get('createdAt'))
                if isinstance(stamp, (int,float)):
                    stamp = datetime.fromtimestamp(978307200+stamp, timezone.utc).isoformat()
                datetime.fromisoformat(stamp.replace('Z','+00:00'))
                if not isinstance(value.get('text',''),str) or len(value.get('text',''))>1_000_000: raise ValueError()
                s = Session(id=sid, created_at=stamp, text=value.get('text',''),
                            recording=False, restored=True, failure='上次识别未完成，可手动重试。')
                s.pcm = bytearray(audio.read_bytes()); s.application = value.get('application')
                result.append(s)
            except (ValueError, KeyError, TypeError, OSError): issues.append(folder.name)
        return sorted(result, key=lambda s:s.created_at), issues
    def discard(self, sid, trash):
        folder = self.folder(sid)
        if folder.is_symlink() or not folder.is_relative_to(self.root): raise ValueError('录音路径无效')
        if folder.exists(): trash(folder)


# Pure matcher; hook callbacks do not do I/O, recognition or clipboard work.
MODIFIER_KEYS = {0xA0:4,0xA1:4,0xA2:2,0xA3:2,0xA4:1,0xA5:1,0x5B:8,0x5C:8}
@dataclass(frozen=True)
class Shortcut:
    key: int = 0xA5
    modifiers: int = 0
    label: str = '右 Alt'
    mouse: int = 0
    def validate(self):
        if self.mouse: return self.mouse in (4,5) and self.key == 0 and self.modifiers == 0
        if self.modifiers & ~15 or not 0 <= self.key <= 255: return False
        if self.modifiers: return self.key not in MODIFIER_KEYS and self.key != 27
        return self.key in MODIFIER_KEYS or 0x70 <= self.key <= 0x87

class Gesture:
    def __init__(self, shortcut=None):
        self.shortcut = shortcut or Shortcut(); self.pressed = set(); self.armed = False; self.interrupted = False
    def key(self, vk, down, injected=False):
        if injected: return False
        if down and vk in self.pressed: return False
        if down:
            self.pressed.add(vk)
            if vk == self.shortcut.key:
                mask = 0
                for k in self.pressed-{vk}: mask |= MODIFIER_KEYS.get(k,0)
                self.armed = mask == self.shortcut.modifiers and all(k in MODIFIER_KEYS for k in self.pressed-{vk}); self.interrupted = False
            elif self.armed: self.interrupted = True
            return False
        self.pressed.discard(vk)
        trigger = vk == self.shortcut.key and self.armed and not self.interrupted
        if vk == self.shortcut.key: self.armed = False
        return trigger


class PCM16Converter:
    """Streaming mono conversion for WASAPI devices which only offer 48kHz/stereo.
    Keeps phase and partial sample frames between callbacks; audioop is not required.
    """
    def __init__(self, rate, channels, sample_format):
        if not 8000 <= rate <= 384000 or not 1 <= channels <= 32 or sample_format not in ('int16','int32','uint8','float'):
            raise ValueError('设备音频格式不支持')
        self.rate, self.channels, self.format = rate, channels, sample_format
        self.width = {'int16':2,'int32':4,'uint8':1,'float':4}[sample_format]
        self.tail = b''; self.mono = []; self.position = 0.0
    def feed(self, data):
        raw = self.tail+data; size = self.width*self.channels
        end = len(raw)//size*size; self.tail = raw[end:]; raw = raw[:end]
        if self.rate == 16000 and self.channels == 1 and self.format == 'int16': return raw
        if self.format == 'uint8': values = [(x-128)/128 for x in raw]
        else:
            values = array({'int16':'h','int32':'i','float':'f'}[self.format], raw)
            if sys.byteorder != 'little': values.byteswap()
            scale = {'int16':32768,'int32':2147483648,'float':1}[self.format]
            values = [float(x)/scale if math.isfinite(x) else 0 for x in values]
        self.mono.extend(sum(values[i:i+self.channels])/self.channels for i in range(0,len(values),self.channels))
        result = array('h'); step = self.rate/16000
        while self.position+1 < len(self.mono):
            index = int(self.position); frac = self.position-index
            value = self.mono[index]*(1-frac)+self.mono[index+1]*frac
            result.append(round(max(-1,min(32767/32768,value))*32768)); self.position += step
        remove = min(int(self.position), max(0,len(self.mono)-1))
        if remove: del self.mono[:remove]; self.position -= remove
        if sys.byteorder != 'little': result.byteswap()
        return result.tobytes()
    def finish(self):
        if self.rate == 16000 and self.channels == 1 and self.format == 'int16': return b''
        result = array('h')
        while self.position < len(self.mono):
            value = self.mono[min(int(self.position),len(self.mono)-1)]
            result.append(round(max(-1,min(32767/32768,value))*32768)); self.position += self.rate/16000
        self.mono.clear()
        if sys.byteorder != 'little': result.byteswap()
        return result.tobytes()
