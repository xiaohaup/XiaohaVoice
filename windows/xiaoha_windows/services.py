"""Qt audio capture and bounded subprocess bridge. No capture on import."""
from __future__ import annotations
import base64,json,os,queue,subprocess,sys,threading,time
from pathlib import Path
from PySide6.QtCore import QObject,Signal
from PySide6.QtMultimedia import QAudioFormat,QAudioSource,QMediaDevices,QAudio
from .core import PCM16Converter


NO_WINDOW = 0x08000000 if os.name == 'nt' else 0

def environment(root):
    root = Path(root); result = dict(os.environ)
    result.update(XH_VOICE_DATA=str(root/'Data'),XH_VOICE_ENGINE=str(root/'Components/engine'),
                  XH_VOICE_IDENTITY=str(root/'Data/recognition'),XH_VOICE_WORKBENCH=str(root/'Components/workbench'),
                  XH_VOICE_OPUS=str(root/'Components/engine/opus.dll'),PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    return result

def runtime_command(root, *args):
    exe = Path(root)/'Runtime/xiaoha-runtime/xiaoha-runtime.exe'
    if exe.is_file(): return [str(exe),*args]
    entry = Path(__file__).resolve().parents[1]/'runtime_entry.py'
    return [sys.executable,str(entry),*args]

class Speech(QObject):
    event = Signal(str,int,dict)
    exited = Signal(str,int,int)
    def __init__(self, root, session):
        super().__init__(); self.sid = session.id; self.generation = session.generation
        self.queue = queue.Queue(maxsize=128); self.process = None; self.closed = threading.Event()
        self.reader = self.writer = None; self.returncode = None
        self.process = subprocess.Popen(runtime_command(root,'bridge'),stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,env=environment(root),creationflags=NO_WINDOW,bufsize=0)
    def start(self):
        self.reader = threading.Thread(target=self._read,daemon=True,name='ASRRead')
        self.writer = threading.Thread(target=self._write,daemon=True,name='ASRWrite')
        # The reader joins the writer during cleanup, including very fast exits.
        self.writer.start(); self.reader.start()
    @property
    def finished(self):
        return (self.process is None and self.returncode is not None
                and all(thread is not None and not thread.is_alive() for thread in (self.reader,self.writer)))
    def wait_finished(self,timeout=3):
        deadline = time.monotonic()+timeout
        for thread in (self.reader,self.writer):
            if thread is not None and thread is not threading.current_thread():
                thread.join(max(0,deadline-time.monotonic()))
        return self.finished
    def _read(self):
        process = self.process
        try:
            while not self.closed.is_set():
                line = process.stdout.readline(4_194_305)
                if not line: break
                if len(line)>4_194_304:
                    process.terminate(); break
                try:
                    value = json.loads(line)
                    if isinstance(value,dict): self.event.emit(self.sid,self.generation,value)
                except (ValueError,UnicodeError): pass
        except (OSError,ValueError):
            pass
        finally:
            self.closed.set()
            # EOF is not itself proof of process exit. Reap this owned child
            # before closing its pipes or announcing exit to the controller.
            try: code = process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try: code = process.wait(timeout=2)
                except subprocess.TimeoutExpired: process.kill(); code = process.wait()
            self.writer.join()
            process.stdin.close(); process.stdout.close()
            while True:
                try: self.queue.get_nowait()
                except queue.Empty: break
            self.returncode = code; self.process = None
            self.exited.emit(self.sid,self.generation,code)
    def _write(self):
        process = self.process
        try:
            while not self.closed.is_set():
                try: value = self.queue.get(timeout=.25)
                except queue.Empty: continue
                if value is None: break
                data = (json.dumps(value,separators=(',',':'))+'\n').encode()
                view = memoryview(data)
                while view:
                    written = process.stdin.write(view)
                    if not written: raise OSError()
                    view = view[written:]
                process.stdin.flush()
        except (OSError,ValueError):
            if process.poll() is None: process.terminate()
    def audio(self, data, replay=False):
        if self.closed.is_set(): return False
        try: self.queue.put_nowait({'event':'audio','pcm':base64.b64encode(data).decode(),'replay':replay}); return True
        except queue.Full: return False
    def finish(self):
        if self.closed.is_set(): return False
        try: self.queue.put_nowait({'event':'stop'}); return True
        except queue.Full: return False
    def cancel(self):
        self.closed.set()
        process = self.process
        if process and process.poll() is None: process.terminate()

class Capture(QObject):
    audio = Signal(bytes)
    failed = Signal(str)
    def __init__(self): super().__init__(); self.source = self.device = None; self.converter = None
    def start(self):
        inputs = QMediaDevices.audioInputs()
        if not inputs: raise ValueError('未发现麦克风，请检查Windows声音设置')
        device = QMediaDevices.defaultAudioInput()
        fmt = QAudioFormat(); fmt.setSampleRate(16000); fmt.setChannelCount(1); fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(fmt): fmt = device.preferredFormat()
        formats = {QAudioFormat.SampleFormat.Int16:'int16',QAudioFormat.SampleFormat.Int32:'int32',
                   QAudioFormat.SampleFormat.UInt8:'uint8',QAudioFormat.SampleFormat.Float:'float'}
        self.converter = PCM16Converter(fmt.sampleRate(),fmt.channelCount(),formats.get(fmt.sampleFormat(),''))
        self.source = QAudioSource(device,fmt,self); self.source.setBufferSize(max(fmt.bytesForDuration(80_000),4096))
        self.source.stateChanged.connect(self._state)
        self.device = self.source.start()
        if self.device is None: self.stop(); raise ValueError('麦克风无法启动，请检查系统麦克风权限')
        self.device.readyRead.connect(self._read)
        return device.description()
    def _read(self):
        if self.device:
            data = self.converter.feed(bytes(self.device.readAll()))
            if data: self.audio.emit(data)
    def _state(self, state):
        if self.source and state == QAudio.State.StoppedState and self.source.error() != QAudio.Error.NoError:
            self.failed.emit('麦克风收音中断，请检查设备或系统麦克风权限，再按启停键结束。')
    def stop(self):
        if self.device:
            self._read()
            if self.converter:
                final = self.converter.finish()
                if final: self.audio.emit(final)
            self.device = None
        source,self.source = self.source,None
        if source: source.stop(); source.deleteLater()
