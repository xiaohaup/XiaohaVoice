from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import pytest
from fastapi.testclient import TestClient
from desktop.control import Companion, create_control
from desktop.workbench import LocalWorkbench


def fixture(tmp_path):
    path=tmp_path/'history.json'
    # Foundation dates and ISO dates are both supported. Midnight belongs to Beijing's day.
    rows=[{'id':'one','created_at':'2026-10-17T16:01:00Z','text':'小哈 Mac 123','seconds':30},
          {'id':'two','created_at':'2026-10-16T09:00:00+08:00','text':'昨天的测试','seconds':20},
          {'id':'one','created_at':'2026-10-17T16:01:00Z','text':'重复不计','seconds':30},
          {'id':'future','created_at':'2026-10-19T09:00:00+08:00','text':'未来不计','seconds':20}]
    path.write_text(json.dumps(rows),encoding='utf-8')
    now=lambda:datetime(2026,10,18,18,tzinfo=ZoneInfo('Asia/Shanghai'))
    return LocalWorkbench(tmp_path/'data',path,now),path


def test_filters_and_dedup_without_modifying_history(tmp_path):
    store,path=fixture(tmp_path); before=path.read_bytes()
    assert len(store.records(period='today'))==1
    assert len(store.records('MAC'))==1
    assert len(store.records(period='all'))==2
    assert store.records('不存在')==[]
    assert path.read_bytes()==before


def test_metrics_calendar_and_estimate(tmp_path):
    store,_=fixture(tmp_path)
    result=store.summary('today')
    assert result['characters']==8 and result['sessions']==1 and result['seconds']==30
    assert result['words_per_minute']==16
    assert result['estimated_saved_minutes']==0  # Never report a negative saving.
    assert len(result['days'])==365 and result['days'][-1]['date']=='2026-10-18'
    assert result['active_days']==2 and result['longest_streak']==1
    store.save_preferences({'theme':'ink','text_size':'large','typing_speed':10})
    assert store.summary('today')['estimated_saved_minutes']==0.3
    assert LocalWorkbench(store.directory,store.history_path,store.now).preferences()['theme']=='ink'


def test_foundation_dates_and_unicode_count(tmp_path):
    store,path=fixture(tmp_path)
    timestamp=store.now().timestamp()-978307200
    path.write_text(json.dumps([{'id':'foundation','createdAt':timestamp,'text':'你，e\u0301！','seconds':5}]))
    rows=store.records(period='today')
    assert rows[0]['characters']==3 and rows[0]['created_at'].startswith('2026-10-18')


def test_workbench_requires_cookie_and_csrf(tmp_path):
    store,history=fixture(tmp_path)
    c=Companion(tmp_path/'companion',history_path=history)
    app=create_control(c)
    # Keep the fixture's future-date check independent of the real calendar.
    app.state.workbench.now=store.now
    client=TestClient(app)
    assert client.get('/workbench/api/history').status_code==401
    assert client.get('/workbench').status_code==200
    status=client.get('/workbench/api/status').json()
    assert len(client.get('/workbench/api/history').json()['records'])==2
    value={'theme':'mint','text_size':'normal','typing_speed':50}
    assert client.post('/workbench/api/preferences',json=value).status_code==403
    headers={'Origin':'http://127.0.0.1:8766','X-CSRF-Token':status['csrf']}
    assert client.post('/workbench/api/preferences',json=value,headers=headers).status_code==200
    assert client.get('/workbench/api/status').json()['preferences']['typing_speed']==50
    assert client.get('/workbench/api/history',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
    assert client.get('/workbench',headers={'Host':'attacker.invalid'}).status_code==400


def test_local_workbench_does_not_contact_cloud(tmp_path):
    _,history=fixture(tmp_path)
    def forbidden(*args,**kwargs):raise AssertionError('local workbench attempted cloud access')
    companion=Companion(tmp_path/'companion',history_path=history,remote_factory=forbidden)
    client=TestClient(create_control(companion))
    client.get('/workbench')
    assert client.get('/workbench/api/status').json()['cloud_configured'] is False
    assert client.get('/workbench/api/summary').status_code==200
    assert client.get('/workbench/api/history?q=Mac').status_code==200
    assert not (tmp_path/'companion/accounts').exists()


def test_corrupt_history_is_preserved(tmp_path):
    store,path=fixture(tmp_path);path.write_text('{broken fixture')
    companion=Companion(tmp_path/'companion',history_path=path)
    client=TestClient(create_control(companion));client.get('/workbench')
    assert client.get('/workbench/api/history').status_code==422
    assert path.read_text()=='{broken fixture'


def test_exact_history_day_uses_local_date_and_preserves_source(tmp_path):
    store,path=fixture(tmp_path);before=path.read_bytes()
    assert [r['id'] for r in store.records(day='2026-10-18')]==['one']
    assert [r['id'] for r in store.records('测试',day='2026-10-16')]==['two']
    assert store.records(day='2026-10-19')==[]
    with pytest.raises(ValueError):store.records(day='2026-02-30')
    with pytest.raises(ValueError):store.records(day='20261018')
    assert path.read_bytes()==before


def test_history_day_filter_through_guarded_endpoint(tmp_path):
    store,history=fixture(tmp_path)
    app=create_control(Companion(tmp_path/'companion',history_path=history))
    app.state.workbench.now=store.now
    client=TestClient(app);client.get('/workbench')
    assert [r['id'] for r in client.get('/workbench/api/history?day=2026-10-18').json()['records']]==['one']
    assert client.get('/workbench/api/history?day=invalid').status_code==422


def test_embedded_account_panel_only_allows_same_origin_framing(tmp_path):
    client = TestClient(create_control(Companion(tmp_path/'companion')))
    embedded = client.get('/?embedded=1')
    assert embedded.status_code == 200
    assert "frame-ancestors 'self'" in embedded.headers['content-security-policy']
    for path in ('/', '/workbench', '/api/health'):
        response = client.get(path)
        assert "frame-ancestors 'none'" in response.headers['content-security-policy']
    assert client.get('/?embedded=1', headers={'Host': 'attacker.invalid'}).status_code == 400
    assert client.get('/api/me', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
