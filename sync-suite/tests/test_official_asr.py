"""No real credentials or network: exercise binary frames and duplex streaming."""
import asyncio
import gzip
import importlib.util
import json
from pathlib import Path
import struct
import pytest
ROOT=Path(__file__).resolve().parents[2]
path=ROOT/'ime-channel-test/volcengine_asr.py'
if not path.exists():path=Path(__file__).resolve().parents[1]/'integration/volcengine_asr.py'
spec=importlib.util.spec_from_file_location('official_asr',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def response(text,final=False):
    data=gzip.compress(json.dumps({'result':{'text':text}}).encode())
    return bytes([0x11,0x93 if final else 0x91,0x11,0])+struct.pack('>iI',-2 if final else 1,len(data))+data

def test_parser_final_error_and_malformed():
    data,final=m.parse(response('Claude',True));assert final and data['result']['text']=='Claude'
    with pytest.raises(ValueError):m.parse(b'broken')
    with pytest.raises(ValueError):m.parse(response('test')[:-1])
    err=b'no quota';raw=bytes([0x11,0xf0,0x10,0])+struct.pack('>II',45000081,len(err))+err
    with pytest.raises(RuntimeError,match='45000081'):m.parse(raw)

def test_request_frames_have_pcm_and_terminal_flag():
    frame=m.packet(1,{'audio':{'format':'pcm'}})
    assert frame[:4]==b'\x11\x10\x11\x00'
    assert json.loads(gzip.decompress(frame[8:]))['audio']['format']=='pcm'
    frame=m.packet(2,b'\x00'*6400,True)
    assert frame[1]==0x22 and gzip.decompress(frame[8:])==bytes(6400)

def test_duplex_stream_emits_partial_and_final_without_network():
    class Fake:
        def __init__(self):self.sent=[];self.index=0
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def send(self,data):self.sent.append(data)
        async def recv(self):
            await asyncio.sleep(.001)
            self.index+=1
            return response('测试' if self.index==1 else '测试 Claude',self.index==2)
    ws=Fake();headers={};events=[]
    def connect(endpoint,**kwargs):
        assert endpoint==m.ENDPOINT
        headers.update(kwargs['additional_headers']);return ws
    async def audio():yield bytes(6400);yield bytes(3200)
    result=asyncio.run(m.transcribe(audio(),{'resource':m.RESOURCES[0],'auth':'api_key','second_pass':True},'fixture-key',events.append,connect=connect))
    assert [e['event'] for e in events]==['ready','interim','final','done']
    assert result['text']=='测试 Claude' and result['final_result_received']
    assert ws.sent[-1][1]==0x22 and headers['X-Api-Resource-Id']=='volc.seedasr.sauc.duration'
    assert all('fixture-key' not in str(e) for e in events)

def test_connection_probe_checks_handshake_without_sending_audio():
    class Fake:
        def __init__(self):self.sent=[]
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def send(self,data):self.sent.append(data)
        async def recv(self):return response('',True)
    ws=Fake()
    def connect(endpoint,**kwargs):
        assert kwargs['additional_headers']['X-Api-Key']=='fixture-key';return ws
    result=asyncio.run(m.probe({'resource':m.RESOURCES[0],'auth':'api_key'},'fixture-key',connect))
    assert result['ok'] and result['check']=='websocket_handshake' and len(ws.sent)==0
    assert 'fixture-key' not in str(result)
