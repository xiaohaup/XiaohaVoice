from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest
from server.app import Config, create_app

PASSWORD = 'Local-fixture-password-2026!'


@pytest.fixture
def service(tmp_path):
    return create_app(Config(tmp_path, 'http://testserver', True))


def connect(app, username='fixture_a', register=True, device=None):
    c = TestClient(app)
    model = {'username': username, 'password': PASSWORD, 'device_id': device or str(uuid4()),
             'device_name': 'Synthetic fixture', 'platform': 'Mac'}
    response = c.post('/api/register' if register else '/api/login', json=model, headers={'x-xiaoha-native': '1'})
    assert response.status_code == 200, response.text
    session = response.json()
    c.headers['Authorization'] = 'Bearer ' + session['token']
    return c, session


def change(c, kind='clipboard', item='current', value=None, base=0, operation=None, deleted=False):
    body = {'operation_id': operation or str(uuid4()), 'kind': kind, 'id': item,
            'value': value if value is not None else {'text': 'Synthetic private fixture'},
            'base_revision': base, 'deleted': deleted}
    return c.post('/api/mutate', json=body), body


def test_account_isolation_and_ciphertext(service):
    a, _ = connect(service)
    b, _ = connect(service, 'fixture_b')
    assert change(a)[0].status_code == 200
    assert b.get('/api/state').json()['items'] == []
    assert b.get('/api/state').json()['usage_total']['characters'] == 0
    assert 'Synthetic private fixture' in a.get('/api/state').text
    with sqlite3.connect(service.state.store.path) as db:
        payload = db.execute('SELECT payload FROM items').fetchone()[0]
        assert b'Synthetic private fixture' not in payload


def test_same_account_devices_share_current_text(service):
    a, _ = connect(service)
    b, _ = connect(service, register=False)
    change(a)
    assert b.get('/api/state').json()['items'][0]['value']['text'] == 'Synthetic private fixture'
    assert len(b.get('/api/state').json()['devices']) == 2


def test_retry_idempotency_and_tampering(service):
    c, _ = connect(service)
    r, body = change(c)
    assert r.status_code == 200
    again = c.post('/api/mutate', json=body)
    assert again.status_code == 200 and again.json()['duplicate']
    body['value']['text'] = 'Other content'
    assert c.post('/api/mutate', json=body).status_code == 409
    assert c.get('/api/state').json()['revision'] == 1


def test_offline_conflict_retains_other_device_copy(service):
    a, _ = connect(service)
    b, _ = connect(service, register=False)
    change(a, value={'text': 'First online copy'})
    stale, _ = change(b, value={'text': 'Offline draft'}, base=0)
    assert stale.status_code == 409
    assert stale.json()['detail']['current']['value']['text'] == 'First online copy'
    assert a.get('/api/state').json()['items'][0]['value']['text'] == 'First online copy'


def test_independent_words_merge_and_tombstone_survives(service):
    a, _ = connect(service)
    b, _ = connect(service, register=False)
    first, second = str(uuid4()), str(uuid4())
    assert change(a, 'glossary', first, {'term': '小哈', 'aliases': ['小蛤']})[0].status_code == 200
    assert change(b, 'glossary', second, {'term': '独立词条', 'aliases': []})[0].status_code == 200
    assert len(a.get('/api/state').json()['items']) == 2
    assert change(b, 'glossary', first, {}, base=1, deleted=True)[0].status_code == 200
    resurrection, _ = change(a, 'glossary', first, {'term': '旧设备离线词条', 'aliases': []}, base=1)
    assert resurrection.status_code == 409
    assert resurrection.json()['detail']['current']['deleted']


def test_stats_merge_and_retries_never_duplicate(service):
    a, one = connect(service)
    b, two = connect(service, register=False)
    event = {'session_id': str(uuid4()), 'created_at': '2026-10-18T01:00:00Z', 'characters': 12, 'seconds': 4.5}
    assert a.post('/api/usage', json={'events': [event, event]}).status_code == 200
    assert a.post('/api/usage', json={'events': [event]}).status_code == 200
    assert b.post('/api/usage', json={'events': [{**event, 'session_id': str(uuid4()), 'characters': 8}]}).status_code == 200
    total = a.get('/api/state').json()['usage_total']
    assert total == {'sessions': 2, 'characters': 20, 'seconds': 9.0}
    assert b.post('/api/usage', json={'events': [event]}).status_code == 409


def test_usage_rejects_transcripts_and_local_settings_are_not_synced(service):
    c, _ = connect(service)
    event = {'session_id': str(uuid4()), 'created_at': '2026-10-18T01:00:00Z', 'characters': 8, 'seconds': 4, 'text': 'never upload history'}
    assert c.post('/api/usage', json={'events': [event]}).status_code == 422
    assert change(c, 'preference', 'hotkey', {'value': 'RightOption'})[0].status_code == 422
    assert change(c, 'preference', 'theme', {'value': 'ink'})[0].status_code == 200
    assert c.get('/api/history').status_code == 404


def test_cookie_csrf_origin_and_session_stability(service):
    c = TestClient(service)
    body = {'username': 'fixture_browser', 'password': PASSWORD, 'device_id': str(uuid4()), 'device_name': 'Browser', 'platform': 'iPhone'}
    login = c.post('/api/register', json=body, headers={'origin': 'http://testserver'})
    assert login.status_code == 200 and 'token' not in login.json()
    csrf = login.json()['csrf']
    assert c.get('/api/me').json()['csrf'] == csrf
    assert c.get('/api/me').json()['csrf'] == csrf
    mutation = {'operation_id': str(uuid4()), 'kind': 'clipboard', 'id': 'current', 'base_revision': 0, 'value': {'text': 'browser fixture'}}
    assert c.post('/api/mutate', json=mutation, headers={'origin': 'http://testserver'}).status_code == 403
    assert c.post('/api/mutate', json=mutation, headers={'origin': 'https://untrusted.invalid', 'x-csrf-token': csrf}).status_code == 403
    assert c.post('/api/mutate', json=mutation, headers={'origin': 'http://testserver', 'x-csrf-token': csrf}).status_code == 200
    assert 'httponly' in login.headers['set-cookie'].lower()
    assert 'samesite=strict' in login.headers['set-cookie'].lower()


def test_revoke_device_removes_access_without_erasing_stats(service):
    a, _ = connect(service)
    b, other = connect(service, register=False)
    event = {'session_id': str(uuid4()), 'created_at': '2026-10-18T01:00:00Z', 'characters': 7, 'seconds': 2}
    b.post('/api/usage', json={'events': [event]})
    assert a.post('/api/devices/'+other['device_id']+'/revoke', json={}).status_code == 200
    assert b.get('/api/state').status_code == 401
    assert a.get('/api/state').json()['usage_total']['characters'] == 7


def test_atomic_race_only_one_clipboard_write_wins(service):
    a, _ = connect(service)
    b, _ = connect(service, register=False)
    with ThreadPoolExecutor(max_workers=2) as executor:
        replies = list(executor.map(lambda c: change(c)[0].status_code, [a, b]))
    assert sorted(replies) == [200, 409]


def test_input_size_and_timezone_boundaries(service):
    c, _ = connect(service)
    assert c.post('/api/mutate', content='x' * 1_048_577, headers={'content-type': 'application/json'}).status_code == 413
    assert c.post('/api/mutate', content='{}', headers={'content-type': 'text/plain'}).status_code == 415
    event = {'session_id': str(uuid4()), 'created_at': '2026-10-18T01:00:00', 'characters': 7, 'seconds': 2}
    assert c.post('/api/usage', json={'events': [event]}).status_code == 422


def test_deployment_refuses_remote_plain_http_and_open_registration(tmp_path):
    with pytest.raises(ValueError):
        Config(tmp_path, 'http://public.example')
    with pytest.raises(ValueError):
        Config(tmp_path, 'https://public.example', True, '')


def test_restored_database_resets_a_future_client_cursor(service):
    c,_=connect(service)
    change(c)
    result=c.get('/api/state?since=1000').json()
    assert result['reset'] is True and result['revision']==1
    assert len(result['items'])==1
