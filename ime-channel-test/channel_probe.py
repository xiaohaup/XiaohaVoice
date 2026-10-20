#!/usr/bin/env python3
"""Small IME-channel evaluation adapter; no microphone or existing account access.

Protocol reference: missuo/koe, MIT, Vincent Yang (2026).
See UPSTREAM-LICENSE-MIT.txt and the frozen source manifest.
"""
from __future__ import annotations
import argparse, asyncio, base64, ctypes, hashlib, json, math, os
from pathlib import Path
import re, secrets, ssl, sys, time, unicodedata, uuid
from array import array
import certifi, requests, websockets

ROOT = Path(os.environ.get('XH_VOICE_ENGINE') or Path(__file__).resolve().parent)
REFERENCE = ROOT.parent / 'ime-protocol-review/koe/source/koe-asr/src/doubaoime.rs'
PRIVATE = Path(os.environ.get('XH_VOICE_IDENTITY') or ROOT / 'private')
DATA = Path(os.environ.get('XH_VOICE_DATA') or ROOT.parent/'mac-prototype/private')
sys.path.insert(0,os.environ.get('XH_VOICE_WORKBENCH') or str(ROOT.parent/'sync-suite'))
from desktop.runtime_settings import RuntimeSettings
from desktop.runtime_log import append as diagnostic
NETWORK = RuntimeSettings(DATA)
PERSONALIZER = None

def constants():
    bundled=ROOT/'protocol-constants.json'
    if bundled.exists(): return json.loads(bundled.read_text())
    source = REFERENCE.read_text()
    names = ('WEBSOCKET_URL','REGISTER_URL','ASR_APP_KEY','APP_VERSION_CODE','APP_VERSION_NAME','USER_AGENT')
    result = {n: re.search(r'const '+n+r': &str = "([^"\n]+)";',source).group(1) for n in names}
    assert result['WEBSOCKET_URL'] == 'wss://frontier-audio-ime-ws.doubao.com/ocean/api/v1/ws'
    assert result['REGISTER_URL'] == 'https://log-klink.zijieapi.com/service/2/device_register/'
    return result

def private_write(path, value):
    PRIVATE.mkdir(exist_ok=True, mode=0o700)
    os.chmod(PRIVATE,0o700)
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600),'w') as f:
        os.fchmod(f.fileno(),0o600)
        json.dump(value,f)

def credentials(c, allow_register=False):
    dest = PRIVATE/'device.json'
    if dest.exists():
        os.chmod(dest,0o600)
        d=json.loads(dest.read_text())
        if str(d.get('device_id','0')) not in ('','0'): return d
        raise RuntimeError('Saved device registration is invalid; automatic replacement disabled')
    if not allow_register: raise RuntimeError('No test identity; explicit initial registration required')
    pending=PRIVATE/'registration-attempt.json'
    if pending.exists(): raise RuntimeError('Registration was already attempted; no identity rotation or automatic retry')
    cdid,openudid,clientudid=str(uuid.uuid4()),secrets.token_hex(8),str(uuid.uuid4())
    version=int(c['APP_VERSION_CODE'])
    header=dict(device_id=0,install_id=0,aid=401734,app_name='oime',version_code=version,
        version_name=c['APP_VERSION_NAME'],manifest_version_code=version,update_version_code=version,
        channel='official',package='com.bytedance.android.doubaoime',device_platform='android',os='android',
        os_api='34',os_version='16',device_type='Pixel 7 Pro',device_brand='google',device_model='Pixel 7 Pro',
        resolution='1080*2400',dpi='420',language='zh',timezone=8,access='wifi',rom='UP1A.231005.007',
        rom_version='UP1A.231005.007',region='CN',tz_name='Asia/Shanghai',tz_offset=28800,sim_region='cn',
        carrier_region='cn',cpu_abi='arm64-v8a',build_serial='unknown',not_request_sender=0,sig_hash='',
        google_aid='',mc='',serial_number='',openudid=openudid,clientudid=clientudid,cdid=cdid)
    keys=('device_platform','os','channel','aid','app_name','version_code','version_name',
          'manifest_version_code','update_version_code','resolution','dpi','device_type',
          'device_brand','language','os_api','os_version')
    params={k:str(header[k]) for k in keys}
    now=int(time.time()*1000)
    params.update(ssmix='a',_rticket=str(now),cdid=cdid,ac='wifi')
    PRIVATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    with os.fdopen(os.open(pending,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as attempt:
        json.dump(dict(cdid=cdid,openudid=openudid,clientudid=clientudid,attempted_at_ms=now),attempt)
    session=requests.Session();session.trust_env,session.proxies=NETWORK.requests_options()
    response=session.post(c['REGISTER_URL'],params=params,
        json={'magic_tag':'ss_app_log','header':header,'_gen_time':now},
        headers={'User-Agent':c['USER_AGENT']},timeout=(8,12),allow_redirects=False)
    if response.status_code != 200: raise RuntimeError('Device registration HTTP '+str(response.status_code))
    data=response.json()
    did=str(data.get('device_id') or data.get('device_id_str') or '0')
    if did in ('','0'):raise RuntimeError('Registration returned no usable identity; stopped')
    d=dict(device_id=did,install_id=str(data.get('install_id','')),cdid=cdid,
           openudid=openudid,clientudid=clientudid)
    private_write(dest,d)
    return d

def varint(n):
    b=bytearray()
    while n>127:b.append((n&127)|128);n>>=7
    b.append(n);return bytes(b)

def field(n,v):
    if isinstance(v,int):return varint(n<<3)+varint(v)
    if isinstance(v,str):v=v.encode()
    return varint((n<<3)|2)+varint(len(v))+v if v else b''

def decode(data):
    if not isinstance(data,bytes):raise ValueError('Expected a binary protobuf response')
    offset=0;result={}
    def integer():
        nonlocal offset
        n=0
        for shift in range(0,70,7):
            if offset>=len(data):raise ValueError('Truncated protobuf integer')
            b=data[offset];offset+=1;n|=(b&127)<<shift
            if b<128:return n
        raise ValueError('Oversized protobuf integer')
    while offset<len(data):
        tag=integer();n,wire=tag>>3,tag&7
        if wire==0:result[n]=integer()
        elif wire==2:
            size=integer()
            if offset+size>len(data):raise ValueError('Truncated protobuf field')
            result[n]=data[offset:offset+size];offset+=size
        elif wire in (1,5):
            offset+=8 if wire==1 else 4
            if offset>len(data):raise ValueError('Truncated protobuf fixed field')
        else:raise ValueError('Unsupported protobuf wire type')
    return result

def utf(d,n):return d.get(n,b'').decode('utf-8',errors='replace')

class Opus:
    def __init__(self):
        library=os.environ.get('XH_VOICE_OPUS') or (str(ROOT/'libopus.0.dylib') if (ROOT/'libopus.0.dylib').exists() else '/opt/homebrew/opt/opus/lib/libopus.0.dylib')
        self.lib=ctypes.CDLL(library)
        self.lib.opus_encoder_create.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_int)]
        self.lib.opus_encoder_create.restype=ctypes.c_void_p
        self.lib.opus_encode.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_int16),ctypes.c_int,ctypes.POINTER(ctypes.c_ubyte),ctypes.c_int]
        self.lib.opus_encode.restype=ctypes.c_int
        self.lib.opus_encoder_destroy.argtypes=[ctypes.c_void_p]
        err=ctypes.c_int();self.ptr=self.lib.opus_encoder_create(16000,1,2049,ctypes.byref(err))
        if err.value or not self.ptr:raise RuntimeError('Opus encoder unavailable')
    def encode(self,pcm):
        assert len(pcm)==640
        audio=(ctypes.c_int16*320).from_buffer_copy(pcm);out=(ctypes.c_ubyte*4000)()
        n=self.lib.opus_encode(self.ptr,audio,320,out,4000)
        if n<0:raise RuntimeError('Opus encoding failed')
        return bytes(out[:n])
    def close(self):
        if self.ptr:self.lib.opus_encoder_destroy(self.ptr);self.ptr=None

def emit(value):
    if value.get('event') in ('done','empty','error'):
        diagnostic(DATA,'recognition',phase=value['event'],**{k:value[k] for k in ('updates','connection_ms','finish_wait_ms','error_kind') if k in value})
    if PERSONALIZER is not None and isinstance(value.get('text'),str):
        value={**value,'text':PERSONALIZER.apply(value['text'])}
    print(json.dumps(value,ensure_ascii=False),flush=True)

async def transcribe(source, c, creds, publish=emit):
    begin=time.perf_counter();first_audio=None;audio_end=None;first_text=None
    first_loud_frame=None;first_loud_sent=None;chunks=0;largest_chunk=0
    events=[];latest='';final='';bytes_sent=0;count=0;seq=0;send_done=asyncio.Event()
    request_id=str(uuid.uuid4());encoder=Opus();base_ms=int(time.time()*1000)
    def request(method,payload='',audio=b'',state=None):
        return b''.join(field(n,v) for n,v in [(2,c['ASR_APP_KEY'] if method!='TaskRequest' else ''),
            (3,'ASR'),(5,method),(6,payload),(7,audio),(8,request_id)] if v)+ (field(9,state) if state is not None else b'')
    uri=c['WEBSOCKET_URL']+'?aid=401734&device_id='+creds['device_id']
    ctx=ssl.create_default_context(cafile=certifi.where())
    sender=None
    try:
        async with websockets.connect(uri,ssl=ctx,open_timeout=10,close_timeout=2,ping_interval=None,
            user_agent_header=c['USER_AGENT'],additional_headers={'proto-version':'v2','x-custom-keepalive':'true'},
            max_size=4*1024*1024,proxy=NETWORK.websocket_proxy()) as ws:
            connected=time.perf_counter()
            async def control(method,payload,expected):
                await ws.send(request(method,payload))
                d=decode(await asyncio.wait_for(ws.recv(),10))
                name=utf(d,4)
                if name!=expected:raise RuntimeError(f'{method} rejected: {name}, status={d.get(5,0)}')
            await control('StartTask','','TaskStarted')
            config={'audio_info':{'channel':1,'format':'speech_opus','sample_rate':16000},
                'enable_punctuation':True,'enable_speech_rejection':False,
                'extra':{'app_name':'com.android.chrome','cell_compress_rate':8,'did':creds['device_id'],
                    'enable_asr_threepass':True,'enable_asr_twopass':True,'input_mode':'tool'}}
            await control('StartSession',json.dumps(config,separators=(',',':')),'SessionStarted')
            ready=time.perf_counter();publish({'event':'ready','connection_ms':round((connected-begin)*1000),
                                              'session_ready_ms':round((ready-begin)*1000)})
            async def send():
                nonlocal first_audio,audio_end,bytes_sent,seq,chunks,largest_chunk
                pending=b''
                async def frame(pcm,state):
                    nonlocal seq,first_loud_frame,first_loud_sent
                    if first_loud_frame is None and state != 9:
                        samples=array('h',pcm)
                        if sys.byteorder != 'little':samples.byteswap()
                        # A level threshold is only a rough onset marker, not a speech detector.
                        rms=math.sqrt(sum(float(x)*x for x in samples)/len(samples))/32768
                        if rms>=0.01:
                            first_loud_frame=seq*20
                            first_loud_sent=time.perf_counter()
                    payload=json.dumps({'extra':{},'timestamp_ms':base_ms+seq*20},separators=(',',':'))
                    await ws.send(request('TaskRequest',payload,encoder.encode(pcm),state));seq+=1
                async for chunk in source:
                    if first_audio is None:first_audio=time.perf_counter()
                    chunks+=1;largest_chunk=max(largest_chunk,len(chunk))
                    bytes_sent+=len(chunk);pending+=chunk
                    while len(pending)>=640:
                        await frame(pending[:640],1 if seq==0 else 3);pending=pending[640:]
                if pending:
                    await frame(pending.ljust(640,b'\0'),1 if seq==0 else 3)
                if seq:
                    await frame(bytes(640),9)
                audio_end=time.perf_counter()
                await ws.send(request('FinishSession'))
                send_done.set()
                publish({'event':'input_finished','audio_seconds':round(bytes_sent/32000,3)})
            sender=asyncio.create_task(send())
            while True:
                if sender.done():sender.result()
                if audio_end and time.perf_counter()-audio_end>8:raise TimeoutError('Final response exceeded 8 seconds')
                try:raw=await asyncio.wait_for(ws.recv(),0.5)
                except asyncio.TimeoutError:continue
                stamp=time.perf_counter();d=decode(raw);name=utf(d,4)
                if name in ('TaskFailed','SessionFailed'):raise RuntimeError(f'{name}, status={d.get(5,0)}')
                if name=='SessionFinished':break
                content=utf(d,7)
                if not content:continue
                obj=json.loads(content);results=obj.get('results') or []
                if not results:continue
                item=results[0];text=item.get('text','')
                if not text:continue
                if first_text is None:first_text=stamp
                is_final=item.get('is_interim') is False and bool(item.get('is_vad_finished'))
                settled=item.get('is_interim') is False or bool(item.get('extra',{}).get('nonstream_result'))
                kind='final' if is_final else 'definite' if settled else 'interim'
                if is_final:final=text
                if text!=latest or is_final:
                    count+=1;event={'event':kind,'text':text,'elapsed_ms':round((stamp-begin)*1000),
                        'from_audio_ms':round((stamp-first_audio)*1000) if first_audio else None,
                        'before_input_finished':not send_done.is_set(),'result_entries':len(results)}
                    events.append(event);publish(event);latest=text
            if not sender.done():
                raise RuntimeError('Server finished while audio source was still active')
            await sender
            end=time.perf_counter()
            # SessionFinished without words is a valid empty result, not a connection error.
            report={'ok':True,'backend':'doubao_input_method','endpoint':c['WEBSOCKET_URL'],
                'connection_ms':round((connected-begin)*1000),'session_ready_ms':round((ready-begin)*1000),
                'first_text_from_audio_ms':round((first_text-first_audio)*1000) if first_text and first_audio else None,
                'finish_wait_ms':round((end-audio_end)*1000) if audio_end else None,
                'audio_seconds':round(bytes_sent/32000,3),'updates':count,
                'first_audio_after_ready_ms':round((first_audio-ready)*1000) if first_audio else None,
                'first_level_onset_audio_ms':first_loud_frame,
                'first_text_after_level_onset_ms':round((first_text-first_loud_sent)*1000) if first_text and first_loud_sent else None,
                'level_onset_threshold_dbfs':-40,'source_chunks':chunks,
                'largest_source_chunk_ms':round(largest_chunk/32,2),
                'streamed_before_stop':any(e['before_input_finished'] for e in events),
                'final_result_received':bool(final),'text':final or latest,'events':events}
            publish({'event':'done' if latest else 'empty',**{k:v for k,v in report.items() if k not in ('events','endpoint','backend')}})
            return report
    finally:
        if sender and not sender.done():
            sender.cancel()
            try:await sender
            except asyncio.CancelledError:pass
        encoder.close()

async def replay(data):
    start=time.perf_counter()
    for offset in range(0,len(data),640):
        await asyncio.sleep(max(0,start+offset/32000-time.perf_counter()))
        yield data[offset:offset+640]
    await asyncio.sleep(max(0,start+len(data)/32000-time.perf_counter()))

async def benchmark(pcm):
    """Manual IME recognition check, existing identity only, no mic or API fallback."""
    if not pcm or len(pcm)%2 or len(pcm)>320000:raise ValueError('内置测速语音无效')
    c=constants()
    creds=await asyncio.to_thread(credentials,c,False)
    report=await transcribe(replay(pcm),c,creds,lambda event:None)
    if not report.get('text'):raise RuntimeError('输入法通道未返回测试文字')
    return {'ok':True,'check':'synthetic_speech','provider':'ime','backend':'doubao_input_method',
            'text':report['text'],'updates':report['updates'],'audio_seconds':report['audio_seconds'],
            'first_text_ms':report['session_ready_ms']+(report['first_audio_after_ready_ms'] or 0)+(report['first_text_from_audio_ms'] or 0),
            'finish_wait_ms':report['finish_wait_ms'],'final_result_received':report['final_result_received'],
            'streamed_before_stop':report['streamed_before_stop'],
            'detail':'豆包输入法通道已完成内置合成语音识别；未使用麦克风，不计入历史和统计。'}

async def probe():
    """Validate the existing IME identity and voice session without sending audio."""
    c=constants();creds=await asyncio.to_thread(credentials,c,False)
    begin=time.perf_counter();request_id=str(uuid.uuid4())
    def request(method,payload=''):
        return b''.join(field(n,v) for n,v in ((2,c['ASR_APP_KEY']),(3,'ASR'),(5,method),(6,payload),(8,request_id)) if v)
    uri=c['WEBSOCKET_URL']+'?aid=401734&device_id='+creds['device_id']
    ctx=ssl.create_default_context(cafile=certifi.where())
    async with websockets.connect(uri,ssl=ctx,open_timeout=8,close_timeout=.5,ping_interval=None,
        user_agent_header=c['USER_AGENT'],additional_headers={'proto-version':'v2','x-custom-keepalive':'true'},
        max_size=4*1024*1024,proxy=NETWORK.websocket_proxy()) as ws:
        async def control(method,payload,expected):
            await ws.send(request(method,payload))
            response=decode(await asyncio.wait_for(ws.recv(),5))
            if utf(response,4)!=expected:raise RuntimeError('输入法通道未接受测试会话')
        await control('StartTask','','TaskStarted')
        config={'audio_info':{'channel':1,'format':'speech_opus','sample_rate':16000},
            'enable_punctuation':True,'enable_speech_rejection':False,
            'extra':{'app_name':'com.android.chrome','cell_compress_rate':8,'did':creds['device_id'],
                'enable_asr_threepass':True,'enable_asr_twopass':True,'input_mode':'tool'}}
        await control('StartSession',json.dumps(config,separators=(',',':')),'SessionStarted')
        elapsed=round((time.perf_counter()-begin)*1000)
        await ws.send(request('FinishSession'))
        return {'ok':True,'check':'ime_session','milliseconds':elapsed,'provider':'ime',
                'detail':'连接与语音会话认证通过，未打开麦克风、未发送音频。'}

async def stdin_audio():
    loop=asyncio.get_running_loop()
    while True:
        line=await loop.run_in_executor(None,sys.stdin.buffer.readline)
        if not line:break
        item=json.loads(line)
        if item['event']=='stop':break
        if item['event']=='audio':
            data=base64.b64decode(item['pcm'],validate=True)
            yield data
            if item.get('replay'):
                # A bounded two-times replay catches up a short connection interruption.
                await asyncio.sleep(len(data)/64000)

def normalized(s):return ''.join(c.lower() for c in unicodedata.normalize('NFKC',s) if c.isalnum())

async def main(args):
    global PERSONALIZER
    if args.mode=='bridge':
        from personalization import Personalizer
        PERSONALIZER=Personalizer(DATA/'sync-wordbook.json', DATA/'corrections.json')
    settings_path=DATA/'asr-settings.json'
    settings=json.loads(settings_path.read_text()) if settings_path.exists() else {}
    diagnostic(DATA,'recognition',phase='start',provider=settings.get('provider','ime'))
    if args.mode=='bridge' and settings.get('provider')=='volcengine':
        try:
            import keyring
            from volcengine_asr import transcribe as official_transcribe
            credential=keyring.get_password('com.xiaoha.voice.asr','volcengine-streaming')
            if not credential: raise ValueError('正式API尚未保存凭证，请在识别通道中配置')
            await official_transcribe(stdin_audio(), {**settings,'proxy':NETWORK.websocket_proxy()}, credential, emit)
        except Exception as exc:
            # Never display a remote exception containing request headers or credentials.
            message=str(exc) if type(exc) in (ValueError, RuntimeError, TimeoutError) else '正式API连接失败，请检查配置、网络和额度'
            if 'credential' in locals() and credential: message=message.replace(credential,'[redacted]')
            emit({'event':'error','message':message})
            raise SystemExit(1)
        return
    c=constants();creds=await asyncio.to_thread(credentials,c,args.register_if_needed)
    try:
        if args.mode=='synth':
            data=Path(args.pcm).read_bytes()
            if len(data)%2:raise ValueError('PCM length must be even')
            report=await asyncio.wait_for(transcribe(replay(data),c,creds),len(data)/32000+30)
            report.update(label=args.label,expected=args.expected,synthetic=True,user_voice=False,
                          exact_after_punctuation_normalization=normalized(report['text'])==normalized(args.expected),
                          audio_sha256=hashlib.sha256(data).hexdigest())
            Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        else:
            report=await transcribe(stdin_audio(),c,creds)
            metrics={k:v for k,v in report.items() if k not in ('text','events')}
            if settings.get('diagnostics') is True:
                PRIVATE.joinpath('last-microphone-metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
                os.chmod(PRIVATE/'last-microphone-metrics.json',0o600)
    except Exception as exc:
        # Only controlled error text is displayed. Library errors may contain URL identifiers.
        controlled=isinstance(exc,(RuntimeError,ValueError,TimeoutError)) and type(exc).__module__=='builtins'
        message=str(exc) if controlled else type(exc).__name__
        for value in (creds.get('device_id',''),c['ASR_APP_KEY']):
            if value:message=message.replace(value,'[redacted]')
        emit({'event':'error','kind':type(exc).__name__,'message':message})
        raise SystemExit(1)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['synth','bridge'])
    ap.add_argument('--register-if-needed',action='store_true');ap.add_argument('--pcm')
    ap.add_argument('--label',default='short');ap.add_argument('--expected',default='');ap.add_argument('--output')
    ns=ap.parse_args()
    try:asyncio.run(main(ns))
    except SystemExit:raise
    except Exception as exc:
        emit({'event':'error','kind':type(exc).__name__,'message':'Connection preparation failed; no automatic retry'})
        raise SystemExit(1)
