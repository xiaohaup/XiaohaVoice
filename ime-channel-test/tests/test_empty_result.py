"""Offline protocol regressions using synthetic PCM and a fake websocket."""
import asyncio
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('channel_probe',Path(__file__).resolve().parents[1]/'channel_probe.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
class Encoder:
    def encode(self,data):return b'opus-fixture'
    def close(self):pass
class Socket:
    def __init__(self,responses):self.responses=iter(responses);self.sent=[]
    async def send(self,data):self.sent.append(data)
    async def recv(self):await asyncio.sleep(0);return next(self.responses)
class Connection:
    def __init__(self,responses):self.ws=Socket(responses)
    async def __aenter__(self):return self.ws
    async def __aexit__(self,*args):pass
async def source():yield bytes(3200)
class EmptyResultTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self,responses):
        events=[]
        with patch.object(probe,'Opus',Encoder),patch.object(probe.websockets,'connect',return_value=Connection([{4:'TaskStarted'},{4:'SessionStarted'}]+responses)),patch.object(probe,'decode',lambda raw:raw),patch.object(probe,'utf',lambda d,n:d.get(n,'')):
            report=await probe.transcribe(source(),{'WEBSOCKET_URL':'wss://fixture.invalid','USER_AGENT':'fixture','ASR_APP_KEY':'synthetic'}, {'device_id':'synthetic'},events.append)
        return report,events
    async def test_finished_without_words_is_empty_not_error(self):
        report,events=await self.run_case([{4:'SessionFinished'}])
        self.assertEqual(report['text'],'');self.assertEqual(events[-1]['event'],'empty')
        self.assertFalse(report['final_result_received']);self.assertFalse(any(e['event']=='error' for e in events))
    async def test_final_words_keep_existing_done_contract(self):
        payload=json.dumps({'results':[{'text':'仅合成测试','is_interim':False,'is_vad_finished':True}]})
        report,events=await self.run_case([{4:'TaskResponse',7:payload},{4:'SessionFinished'}])
        self.assertEqual(report['text'],'仅合成测试');self.assertEqual(events[-1]['event'],'done');self.assertTrue(report['final_result_received'])
    async def test_real_session_failure_is_not_an_empty_success(self):
        with self.assertRaisesRegex(RuntimeError,'SessionFailed'):
            await self.run_case([{4:'SessionFailed',5:500}])
    async def test_connection_probe_authenticates_session_without_audio_or_encoder(self):
        connection=Connection([{4:'TaskStarted'},{4:'SessionStarted'}])
        config={'WEBSOCKET_URL':'wss://fixture.invalid','USER_AGENT':'fixture','ASR_APP_KEY':'fixture-public'}
        def credentials(c,register):
            self.assertFalse(register)
            return {'device_id':'fixture-device'}
        with patch.object(probe,'constants',return_value=config),patch.object(probe,'credentials',credentials),patch.object(probe,'Opus',side_effect=AssertionError('no audio encoder')),patch.object(probe.websockets,'connect',return_value=connection),patch.object(probe,'decode',lambda raw:raw),patch.object(probe,'utf',lambda d,n:d.get(n,'')):
            result=await probe.probe()
        self.assertTrue(result['ok']);self.assertEqual(result['check'],'ime_session')
        self.assertEqual(len(connection.ws.sent),3)
        self.assertFalse(any(b'TaskRequest' in raw for raw in connection.ws.sent))
        self.assertNotIn('fixture-device',str(result))
if __name__=='__main__':unittest.main()
