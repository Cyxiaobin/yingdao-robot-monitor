"""影刀客户端：MOCK 模式不发网络，真实模式请求格式与错误处理正确。"""
import json

import httpx
import pytest

from app.config import Settings
from app.mock_data import MockStore
from app.yingdao_client import YingdaoAPIError, YingdaoClient


async def test_mock_mode_returns_ok_for_all_endpoints(client):
    responses = [
        await client.client_list(),
        await client.task_newest_list(),
        await client.job_query("j1"),
        await client.task_process_detail("t1", "b1"),
        await client.job_log_search("j1"),
        await client.job_stop("j1"),
    ]
    assert all(r["code"] == 200 and r["success"] is True for r in responses)


def _real_client(handler):
    settings = Settings(
        access_key_id="KEY", access_key_secret="SECRET",
        base_url="https://api.example.com", mock_mode=False, enable_poller=False,
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return YingdaoClient(settings, http_client=http), http


async def test_real_mode_sends_token_and_correct_request():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("token/create"):
            return httpx.Response(200, json={
                "code": 200, "success": True,
                "data": {"accessToken": "REAL_TOKEN", "expiresIn": 7199},
            })
        return httpx.Response(200, json={"code": 200, "success": True, "data": []})

    client, http = _real_client(handler)
    try:
        await client.client_list(page=1, size=50)
        await client.task_newest_list(size=20)
    finally:
        await http.aclose()

    token_req, bots_req, runs_req = seen
    assert token_req.method == "GET"
    assert token_req.url.params["accessKeyId"] == "KEY"
    assert bots_req.url.path == "/oapi/dispatch/v2/client/list"
    assert bots_req.headers["Authorization"] == "Bearer REAL_TOKEN"
    assert json.loads(bots_req.content) == {"page": 1, "size": 50}
    assert runs_req.url.path == "/oapi/dispatch/v2/task/newest/list"
    assert len(seen) == 3  # token 只取一次，后续复用缓存


async def test_log_search_uses_post_with_job_uuid():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("token/create"):
            return httpx.Response(200, json={
                "code": 200, "success": True,
                "data": {"accessToken": "T", "expiresIn": 7199},
            })
        return httpx.Response(200, json={"code": 200, "success": True,
                                         "data": {"page": {}, "logs": []}})

    client, http = _real_client(handler)
    try:
        await client.job_log_search("job-1", page=2, size=10)
    finally:
        await http.aclose()

    log_req = seen[-1]
    assert log_req.method == "POST"
    assert log_req.url.path == "/oapi/dispatch/v2/job/log/search"
    assert json.loads(log_req.content) == {"jobUuid": "job-1", "page": 2, "size": 10}


async def test_business_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("token/create"):
            return httpx.Response(200, json={
                "code": 200, "success": True,
                "data": {"accessToken": "T", "expiresIn": 7199},
            })
        return httpx.Response(200, json={"code": 500, "success": False, "msg": "限频"})

    client, http = _real_client(handler)
    try:
        with pytest.raises(YingdaoAPIError, match="限频") as exc:
            await client.client_list()
        assert exc.value.code == 500
    finally:
        await http.aclose()


async def test_mock_store_advance_changes_state():
    store = MockStore()
    before = store.client_list()["data"][1]["status"]
    store.advance()
    after = store.client_list()["data"][1]["status"]
    assert before == "idle" and after == "running"
    assert len(store.task_newest_list()["data"]["result"]) == 5
