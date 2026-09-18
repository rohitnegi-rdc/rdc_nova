import datetime as dt
import io
import zipfile
import json
import sys
import base64
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from open_webui.routers import knowledge_export as api


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv('KNOWLEDGE_EXPORT_ADMIN_IDS', raising=False)
    monkeypatch.setenv('KNOWLEDGE_EXPORT_SECRET', 'local-test-secret-with-at-least-32-characters')
    monkeypatch.setenv('KNOWLEDGE_EXPORT_STATE_PATH', str(tmp_path / 'limits.sqlite'))
    app = FastAPI()
    app.include_router(api.router)
    async def load(start, end):
        return [], []
    monkeypatch.setattr(api, 'load_threads', load)
    return TestClient(app, base_url='https://testserver')


HEADERS = {'Authorization': 'Bearer local-test-secret-with-at-least-32-characters'}


def test_authentication_and_disabled_endpoint(client, monkeypatch):
    assert client.get('/export').status_code == 401
    monkeypatch.delenv('KNOWLEDGE_EXPORT_SECRET')
    assert client.get('/export', headers=HEADERS).status_code == 503


def test_dates_and_empty_archive(client):
    r = client.get('/export?from=2026-09-17&to=2026-09-17', headers=HEADERS)
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert 'threads.json' in z.namelist()
    assert client.get('/export?from=invalid', headers=HEADERS).status_code == 422
    assert client.get('/export?from=2026-09-18&to=2026-09-17', headers=HEADERS).status_code == 422


def test_daily_limit_survives_new_guard_instance(client):
    for _ in range(5):
        assert client.get('/export', headers=HEADERS).status_code == 200
    assert client.get('/export', headers=HEADERS).status_code == 429


def test_concurrent_admission_and_release(tmp_path):
    guard = api.ExportGuard(tmp_path / 'state.sqlite')
    token = guard.admit('one', True, 1000)
    with pytest.raises(api.HTTPException) as exc:
        api.ExportGuard(tmp_path / 'state.sqlite').admit('two', True, 1001)
    assert exc.value.status_code == 409
    guard.release(token)
    assert guard.admit('two', True, 1002)


def test_flood_ban(tmp_path):
    guard = api.ExportGuard(tmp_path / 'state.sqlite')
    for i in range(9):
        assert guard.admit('one', False, 1000 + i) is None
    with pytest.raises(api.HTTPException) as exc:
        guard.admit('one', False, 1010)
    assert exc.value.status_code == 429
    with pytest.raises(api.HTTPException):
        guard.admit('one', True, 1070)


def test_india_inclusive_date_bounds():
    start, end = api.date_bounds(dt.date(2026, 9, 17), dt.date(2026, 9, 17))
    assert (end - start) == 86400 * 10**9
    assert dt.datetime.fromtimestamp(start / 10**9, dt.timezone.utc).hour == 18


def test_https_required(client):
    r = client.get('http://testserver/export', headers=HEADERS)
    assert r.status_code == 400


def test_complete_thread_and_actual_media(client, tmp_path, monkeypatch):
    image = tmp_path / 'formula.png'
    image.write_bytes(b'example-image-bytes')
    monkeypatch.setitem(sys.modules, 'open_webui.storage.provider', SimpleNamespace(Storage=SimpleNamespace(get_file=lambda p: p)))
    async def load(start, end):
        return [{'question': {'content': 'How to calculate throughput?', 'id': 'q', 'attachments': []}, 'replies': [
            {'id': 'a1', 'content': 'Checking', 'attachments': []},
            {'id': 'a2', 'content': 'Use the formula in this image', 'attachments': [{'file_id': 'b7ae8c82-2ec7-4f0f-96b8-c4e2e2ffaa6f', 'filename': 'formula.png', '_path': str(image)}]},
            {'id': 'a3', 'content': 'Sum the batch durations', 'attachments': []},
        ]}], []
    monkeypatch.setattr(api, 'load_threads', load)
    response = client.get('/export', headers=HEADERS)
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        payload = json.loads(archive.read('threads.json'))
        assert len(payload['threads'][0]['replies']) == 3
        assert payload['complete']
        media = payload['threads'][0]['replies'][1]['attachments'][0]
        assert archive.read(media['archive_path']) == image.read_bytes()
        assert '_path' not in media


def test_missing_media_not_silently_complete(client, monkeypatch):
    async def load(start, end):
        return [{'question': {'id': 'q', 'attachments': [{'file_id': 'missing', '_path': None}]}, 'replies': []}], []
    monkeypatch.setattr(api, 'load_threads', load)
    response = client.get('/export', headers=HEADERS)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        payload = json.loads(archive.read('threads.json'))
        assert not payload['complete']
        assert payload['missing_attachments'][0]['message_id'] == 'q'


def test_failure_releases_global_lock(client, monkeypatch):
    async def fail(start, end):
        raise api.HTTPException(413, 'too large')
    monkeypatch.setattr(api, 'load_threads', fail)
    assert client.get('/export', headers=HEADERS).status_code == 413
    assert client.get('/export', headers=HEADERS).status_code == 413


def test_crash_lock_cleanup_and_daily_reset(tmp_path):
    guard = api.ExportGuard(tmp_path / 'limits.sqlite')
    first = guard.admit('one', True, 1000)
    guard._lock.close()  # OS closes descriptors when a worker exits.
    guard._lock = None
    other = api.ExportGuard(tmp_path / 'limits.sqlite')
    second = other.admit('two', True, 1001)
    other.release(second)
    guard.release(first)
    for _ in range(3):
        token = guard.admit('one', True, 1002)
        guard.release(token)
    with pytest.raises(api.HTTPException):
        guard.admit('one', True, 1003)
    token = guard.admit('one', True, 1000 + 86400)
    guard.release(token)


def test_simultaneous_workers_only_one_admitted(tmp_path):
    guards = [api.ExportGuard(tmp_path / 'limits.sqlite') for _ in range(2)]
    barrier = Barrier(2)
    def attempt(index):
        barrier.wait()
        try:
            return index, guards[index].admit(str(index), True), 200
        except api.HTTPException as exc:
            return index, None, exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(r[2] for r in results) == [200, 409]
    for index, token, status in results:
        if token:
            guards[index].release(token)


def test_inline_image_bytes_exported(client, monkeypatch):
    async def load(start, end):
        url = 'data:image/png;base64,' + base64.b64encode(b'image').decode()
        return [{'question': {'id': 'q', 'attachments': [{'_inline': url}]}, 'replies': []}], []
    monkeypatch.setattr(api, 'load_threads', load)
    response = client.get('/export', headers=HEADERS)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        payload = json.loads(archive.read('threads.json'))
        media = payload['threads'][0]['question']['attachments'][0]
        assert archive.read(media['archive_path']) == b'image'
        assert '_inline' not in media
        assert payload['complete']


def test_unauthorized_flood_banned(client):
    for _ in range(9):
        assert client.get('/export').status_code == 401
    assert client.get('/export').status_code == 429
    assert client.get('/export', headers=HEADERS).status_code == 429


def test_default_admin_list(monkeypatch):
    monkeypatch.delenv('KNOWLEDGE_EXPORT_ADMIN_IDS', raising=False)
    assert api.get_admin_ids() == list(api.DEFAULT_ADMIN_IDS)


def test_multiple_admin_ids_deduplicated(monkeypatch):
    first = 'a49a4c0b-b8e0-41d1-88be-8d5798044ed9'
    second = '11111111-1111-4111-8111-111111111111'
    monkeypatch.setenv('KNOWLEDGE_EXPORT_ADMIN_IDS', f' {first}, {second}, {first} ')
    assert api.get_admin_ids() == [first, second]


@pytest.mark.parametrize('value', ['', 'not-a-uuid', 'a49a4c0b-b8e0-41d1-88be-8d5798044ed9,', ','.join(str(i) for i in range(51))])
def test_invalid_admin_configuration_fails_closed(monkeypatch, value):
    monkeypatch.setenv('KNOWLEDGE_EXPORT_ADMIN_IDS', value)
    with pytest.raises(api.HTTPException) as error:
        api.get_admin_ids()
    assert error.value.status_code == 503


def test_archive_identifies_configured_admins(client, monkeypatch):
    ids = ['a49a4c0b-b8e0-41d1-88be-8d5798044ed9', '11111111-1111-4111-8111-111111111111']
    monkeypatch.setenv('KNOWLEDGE_EXPORT_ADMIN_IDS', ','.join(ids))
    response = client.get('/export', headers=HEADERS)
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        payload = json.loads(archive.read('threads.json'))
        assert payload['admin_ids'] == ids
        assert payload['schema_version'] == 2
