"""Official Volcengine streaming ASR 2.0; protocol from vendor docs 6561/1354869.
No automatic fallback or credential rotation. User explicitly chooses the paid API.
"""
import asyncio
import gzip
import json
import ssl
import struct
import time
import uuid
import certifi
import websockets

ENDPOINT = 'wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async'
RESOURCES = ('volc.seedasr.sauc.duration','volc.seedasr.sauc.concurrent')

async def probe(config, credential, connect=websockets.connect):
    """Check the authenticated WebSocket handshake without microphone or audio."""
    ident=str(uuid.uuid4())
    headers={'X-Api-Resource-Id':config['resource'],'X-Api-Request-Id':ident,'X-Api-Connect-Id':ident}
    if config['auth']=='legacy':headers.update({'X-Api-App-Key':config['app_id'],'X-Api-Access-Key':credential})
    else:headers['X-Api-Key']=credential
    begin=time.perf_counter()
    ctx=ssl.create_default_context(cafile=certifi.where())
    async with connect(ENDPOINT,additional_headers=headers,ssl=ctx,open_timeout=8,close_timeout=1,max_size=4_000_000,proxy=config.get('proxy',True)):
        return {'ok':True,'milliseconds':round((time.perf_counter()-begin)*1000),'check':'websocket_handshake','detail':'已建立语音连接，凭证通过握手。未上传音频；资源可用性与识别效果请再实际说一句确认。'}

async def benchmark(config, credential, pcm):
    """Replay bundled synthetic speech in real time; never opens a microphone."""
    if not pcm or len(pcm) % 2 or len(pcm) > 320000:
        raise ValueError('内置测速语音无效')
    async def source():
        begin = time.perf_counter()
        for offset in range(0, len(pcm), 6400):
            await asyncio.sleep(max(0, begin + offset / 32000 - time.perf_counter()))
            yield pcm[offset:offset+6400]
        await asyncio.sleep(max(0, begin + len(pcm) / 32000 - time.perf_counter()))
    result = await transcribe(source(), config, credential, lambda event: None)
    return {'ok':True, 'check':'synthetic_speech', **result,
            'detail':'内置合成语音已完成识别；未使用麦克风，不计入历史和统计。'}

def packet(kind, payload, final=False):
    raw = json.dumps(payload).encode() if kind==1 else payload
    body = gzip.compress(raw)
    return bytes([0x11, kind<<4 | (2 if final else 0), 0x11 if kind==1 else 0x01, 0])+struct.pack('>I',len(body))+body

def parse(raw):
    if not isinstance(raw,bytes) or len(raw)<8 or raw[0]>>4!=1: raise ValueError('API返回了无效协议帧')
    size=(raw[0]&15)*4; kind=raw[1]>>4; flags=raw[1]&15
    if size<4 or size>len(raw)-4: raise ValueError('API协议头长度无效')
    code=0
    if kind==15:
        if len(raw)<size+8: raise ValueError('API错误帧不完整')
        code=struct.unpack_from('>I',raw,size)[0]; size+=4
    elif flags&1: size+=4
    if len(raw)<size+4: raise ValueError('API响应不完整')
    count=struct.unpack_from('>I',raw,size)[0]; data=raw[size+4:]
    if count!=len(data) or count>4_000_000: raise ValueError('API返回数据长度无效')
    if raw[2]&15==1:
        import io
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as f: data=f.read(4_000_001)
        if len(data)>4_000_000: raise ValueError('API响应超出大小限制')
    if code: raise RuntimeError('正式API请求失败，错误码 '+str(code)+'；请检查资源和额度')
    if kind!=9: raise ValueError('API消息类型无效')
    return json.loads(data), bool(flags&2)

async def transcribe(source, config, credential, publish, connect=websockets.connect):
    resource=config.get('resource')
    if resource not in RESOURCES or not credential: raise ValueError('正式API配置不完整')
    ident=str(uuid.uuid4())
    headers={'X-Api-Resource-Id':resource,'X-Api-Request-Id':ident,'X-Api-Connect-Id':ident}
    if config.get('auth')=='legacy': headers.update({'X-Api-App-Key':config['app_id'],'X-Api-Access-Key':credential})
    else: headers['X-Api-Key']=credential
    begin=time.perf_counter(); sent=0; audio_end=None; first_text=None; latest=''; updates=0
    ctx=ssl.create_default_context(cafile=certifi.where())
    sender=None
    try:
        async with connect(ENDPOINT,additional_headers=headers,ssl=ctx,open_timeout=10,close_timeout=2,max_size=4_000_000,proxy=config.get('proxy',True)) as ws:
            request={'user':{'uid':'xiaoha-voice'},'audio':{'format':'pcm','codec':'raw','rate':16000,'bits':16,'channel':1},
                     'request':{'model_name':'bigmodel','enable_itn':True,'enable_punc':True,'show_utterances':True,'enable_nonstream':config.get('second_pass',True)}}
            await ws.send(packet(1,request))
            publish({'event':'ready'})
            async def send():
                nonlocal sent,audio_end
                pending=b''
                async for chunk in source:
                    sent+=len(chunk); pending+=chunk
                    while len(pending)>=6400:
                        await ws.send(packet(2,pending[:6400]));pending=pending[6400:]
                await ws.send(packet(2,pending,final=True));audio_end=time.perf_counter()
            sender=asyncio.create_task(send())
            while True:
                if sender.done(): sender.result()
                if audio_end and time.perf_counter()-audio_end>10: raise TimeoutError('正式API最终结果等待超过10秒，音频仍保留')
                try: raw=await asyncio.wait_for(ws.recv(),.5)
                except asyncio.TimeoutError: continue
                data,final=parse(raw)
                if data.get('code') not in (None,0,1000,20000000): raise RuntimeError('正式API识别被拒绝，错误码 '+str(data['code']))
                result=data.get('result') or {}; result=result[0] if isinstance(result,list) and result else result
                text=result.get('text','') if isinstance(result,dict) else ''
                if text and text!=latest:
                    latest=text;updates+=1;first_text=first_text or time.perf_counter()
                    publish({'event':'final' if final else 'interim','text':text})
                if final:
                    if not sender.done(): raise RuntimeError('正式API提前结束，音频仍保留')
                    await sender
                    if not latest: raise RuntimeError('正式API未识别到文字，音频仍保留')
                    report={'text':latest,'final_result_received':True,'updates':updates,'audio_seconds':sent/32000,
                        'finish_wait_ms':round((time.perf_counter()-audio_end)*1000),
                        'first_text_ms':round((first_text-begin)*1000) if first_text else None,'backend':'volcengine_2'}
                    publish({'event':'done',**report});return report
    finally:
        if sender and not sender.done():
            sender.cancel()
            try: await sender
            except asyncio.CancelledError: pass
