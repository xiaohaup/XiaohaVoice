"""Only the isolated loopback preview, only synthetic accounts and data."""
from pathlib import Path
from uuid import uuid5,NAMESPACE_URL
import json
import httpx

BASE='http://127.0.0.1:8765'
PASSWORD='Local-preview-only-2026!'

def run():
    first=httpx.Client(base_url=BASE,timeout=15,headers={'X-Xiaoha-Native':'1'})
    assert first.get('/api/health').json()['local_only']
    window_id=str(uuid5(NAMESPACE_URL,'xiaoha-synthetic-Windows'))
    def login(client,platform,did,name):
        response=client.post('/api/login',json={'username':'local_preview','password':PASSWORD,'device_id':did,'device_name':name,'platform':platform})
        response.raise_for_status();value=response.json();client.headers['Authorization']='Bearer '+value['token'];return value
    login(first,'Windows',window_id,'合成协议验证 · Windows')
    snapshot=first.get('/api/state').json()
    mac=next(d for d in snapshot['devices'] if d['platform']=='Mac' and '本机预览' in d['name'])
    results=[]
    for platform in ['Mac','Windows','iPhone','iPad','Android']:
        client=httpx.Client(base_url=BASE,timeout=15,headers={'X-Xiaoha-Native':'1'})
        did=mac['id'] if platform=='Mac' else str(uuid5(NAMESPACE_URL,'xiaoha-synthetic-'+platform))
        login(client,platform,did,mac['name'] if platform=='Mac' else '合成协议验证 · '+platform)
        state=client.get('/api/state').json()
        kinds={x['kind'] for x in state['items']}
        assert {'clipboard','glossary','preference'}<=kinds
        if platform in ('Mac','Windows','Android'):
            event={'session_id':str(uuid5(NAMESPACE_URL,'xiaoha-synthetic-usage-'+platform)),
                   'created_at':'2026-10-18T01:00:00Z','characters':{'Mac':200,'Windows':120,'Android':60}[platform],
                   'seconds':{'Mac':60,'Windows':35,'Android':20}[platform]}
            for _ in range(2):
                assert client.post('/api/usage',json={'events':[event]}).status_code==200
        results.append({'platform_metadata':platform,'same_account_items_received':True,'physical_device_test':False})
    total=first.get('/api/state').json()['usage_total']
    assert total=={'sessions':3,'characters':380,'seconds':115.0}
    receipt={'scope':'loopback HTTP protocol clients; synthetic fixtures only','platform_clients':results,'usage_total':total,
             'duplicate_uploads_counted_once':True,'physical_five_device_acceptance':False,'real_clipboard_read':False,'cloud_deployed':False}
    (Path(__file__).resolve().parents[1]/'reports/local-protocol.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'platform_protocol_clients':5,'synthetic_usage_total':total,'physical_device_test':False},ensure_ascii=False))

if __name__=='__main__':run()
