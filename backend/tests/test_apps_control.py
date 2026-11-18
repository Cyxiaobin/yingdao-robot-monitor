"""应用搜索 / 远程运行 / 异常重试 / 错误日志 / 设置页凭证（全部 MOCK，不发真实请求）。"""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.apps import AppCatalog
from app.main import create_app
from app.yingdao_client import YingdaoClient


# ---- 应用目录 ----

async def test_catalog_filters_unpublished_and_matches_keyword(settings, store):
    catalog = AppCatalog(YingdaoClient(settings, mock_store=store))
    result = await catalog.search("退单")
    assert result["total"] == 2                       # 退单写入 / 门店-退单核对
    assert all(x["published"] for x in result["apps"])
    assert all("退单" in x["appName"] for x in result["apps"])

    all_published = await catalog.search("")
    assert all_published["total"] == 4               # app-005 无 publishTime，被过滤
    assert not any(x["appId"] == "app-005" for x in all_published["apps"])


async def test_catalog_pagination_and_runnable_check(settings, store):
    catalog = AppCatalog(YingdaoClient(settings, mock_store=store))
    page2 = await catalog.search("", page=2, size=2)
    assert page2["total"] == 4 and len(page2["apps"]) == 2
    assert await catalog.is_runnable("app-001") is True
    assert await catalog.is_runnable("app-005") is False      # 未发布
    assert await catalog.is_runnable("not-exist") is False
    assert await catalog.is_runnable("") is False


# ---- REST 端点 ----

def test_apps_search_endpoint(api):
    body = api.get("/api/apps/search", params={"keyword": "退单"}).json()
    assert body["total"] == 2
    assert body["apps"][0]["appId"]


def test_apps_refresh_endpoint(api):
    body = api.post("/api/apps/refresh").json()
    assert body["success"] is True
    assert body["total"] == 5 and body["published"] == 4


def test_start_blocks_unknown_app(api):
    """安全：不在已发布目录里的 appId 一律拒绝，绝不发启动请求。"""
    body = api.post("/api/control/start", json={"appId": "not-exist"}).json()
    assert body["success"] is False
    assert "已阻止启动" in body["msg"]


def test_start_known_app_returns_job_uuid(api):
    body = api.post("/api/control/start",
                    json={"appId": "app-001", "accountName": "refund-bot"}).json()
    assert body["success"] is True
    assert body["jobUuid"] == "job-start-app-001"


def test_start_respects_control_switch(settings, store, client):
    disabled = replace(settings, allow_control=False)
    with TestClient(create_app(settings=disabled, client=client, store=store)) as local:
        body = local.post("/api/control/start", json={"appId": "app-001"}).json()
        assert body["success"] is False and "关闭" in body["msg"]


def test_retry_only_for_failed_runs(api):
    ok = api.post("/api/control/retry",
                  json={"taskUuid": "run-003", "botUuid": "bot-003"}).json()
    assert ok["success"] is True and ok["jobUuid"] == "job-run-003"

    finished = api.post("/api/control/retry", json={"taskUuid": "run-001"}).json()
    assert finished["success"] is False and "不支持重试" in finished["msg"]

    missing = api.post("/api/control/retry", json={"taskUuid": "no-such-task"}).json()
    assert missing["success"] is False and "未执行重试" in missing["msg"]


def test_run_logs_endpoint(api):
    body = api.get("/api/run/run-003/logs", params={"botUuid": "bot-003"}).json()
    assert body["runId"] == "run-003"
    assert body["jobUuid"] == "job-run-003"
    assert len(body["logs"]) == 3
    assert body["logs"][2]["level"] == "错误"


def test_run_logs_degrades_on_error(settings, store):
    class LogFail(YingdaoClient):
        async def job_log_search(self, job_uuid, page=1, size=20):
            raise RuntimeError("机器人未连接，无法查询日志")

    with TestClient(create_app(settings=settings,
                              client=LogFail(settings, mock_store=store),
                              store=store)) as local:
        body = local.get("/api/run/run-003/logs?botUuid=bot-003").json()
        assert body["logs"] == []
        assert "机器人未连接" in body["error"]


# ---- 设置页 ----

def test_settings_never_returns_secret(settings, store, client):
    with_secret = replace(settings, access_key_id="AKDEMOa1b2c3d4e5@platform",
                          access_key_secret="SUPER_SECRET_VALUE")
    with TestClient(create_app(settings=with_secret, client=client, store=store)) as local:
        body = local.get("/api/settings").json()
        assert body["hasCredentials"] is True
        assert "SUPER_SECRET_VALUE" not in str(body)
        assert body["accessKeyIdMasked"].startswith("AKDEMO")
        assert body["allowRemoteControl"] is True


def test_settings_test_credentials(api):
    body = api.post("/api/settings/test").json()
    assert body["success"] is True and body["botCount"] == 4


def test_save_credentials_writes_env_and_hot_reloads(api, monkeypatch, tmp_path):
    target = tmp_path / ".env"
    target.write_text("POLL_INTERVAL=5\nYINGDAO_ACCESS_KEY_ID=old\n", encoding="utf-8")
    monkeypatch.setattr(main_module, "_ENV_PATH", target)
    monkeypatch.setenv("YINGDAO_MOCK", "1")   # 保存后仍保持 MOCK，避免真实网络
    # save 会写 os.environ，交给 monkeypatch 在用例结束后恢复，避免污染其他用例
    monkeypatch.setenv("YINGDAO_ACCESS_KEY_ID", "PLACEHOLDER")
    monkeypatch.setenv("YINGDAO_ACCESS_KEY_SECRET", "PLACEHOLDER")

    body = api.post("/api/settings/credentials", json={
        "accessKeyId": "NEW_KEY_ID@platform",
        "accessKeySecret": "NEW_SECRET_VALUE",
    }).json()
    assert body["success"] is True
    assert "NEW_SECRET_VALUE" not in str(body)       # Secret 绝不回显
    assert body["accessKeyIdMasked"].startswith("NEW_KE")

    text = target.read_text(encoding="utf-8")
    assert "POLL_INTERVAL=5" in text                 # 保留其他配置
    assert "YINGDAO_ACCESS_KEY_ID=NEW_KEY_ID@platform" in text
    assert "old" not in text
    assert api.app.state.settings.access_key_id == "NEW_KEY_ID@platform"
    assert api.app.state.aggregator.client is api.app.state.client
    assert api.app.state.catalog.client is api.app.state.client


def test_save_credentials_requires_admin_token(settings, store, client, monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "_ENV_PATH", tmp_path / ".env")
    monkeypatch.setenv("YINGDAO_MOCK", "1")
    monkeypatch.setenv("YINGDAO_ACCESS_KEY_ID", "PLACEHOLDER")
    monkeypatch.setenv("YINGDAO_ACCESS_KEY_SECRET", "PLACEHOLDER")
    locked = replace(settings, admin_token="letmein")
    with TestClient(create_app(settings=locked, client=client, store=store)) as local:
        denied = local.post("/api/settings/credentials", json={
            "accessKeyId": "K", "accessKeySecret": "S"})
        assert denied.status_code == 403
        ok = local.post("/api/settings/credentials",
                        json={"accessKeyId": "K", "accessKeySecret": "S"},
                        headers={"X-Admin-Token": "letmein"})
        assert ok.json()["success"] is True


@pytest.mark.parametrize("payload", [
    {}, {"accessKeyId": "K"}, {"accessKeySecret": "S"},
    {"accessKeyId": "K\nBAD", "accessKeySecret": "S"},
])
def test_save_credentials_validates_input(api, monkeypatch, tmp_path, payload):
    monkeypatch.setattr(main_module, "_ENV_PATH", tmp_path / ".env")
    body = api.post("/api/settings/credentials", json=payload).json()
    assert body["success"] is False
    assert not (tmp_path / ".env").exists()          # 非法输入不落盘
