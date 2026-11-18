"""API 层：REST、WebSocket 首帧、回调广播、远程控制。"""

from fastapi.testclient import TestClient

from app.main import create_app
from app.yingdao_client import YingdaoClient


def test_health(api):
    body = api.get("/health").json()
    assert body["status"] == "ok"
    assert body["mock_mode"] is True
    assert api.app.state.poll_task is None  # 测试环境关闭后台轮询


def test_logs_endpoint_degrades_when_robot_offline(settings, store):
    """真实环境：机器人离线时影刀拒查日志，端点必须返回 200 + 原因，不能 500。"""
    class LogFailClient(YingdaoClient):
        async def job_log_search(self, job_uuid):
            raise RuntimeError("原因：机器人未连接，无法查询日志")

    with TestClient(create_app(settings=settings,
                              client=LogFailClient(settings, mock_store=store),
                              store=store)) as local:
        resp = local.get("/api/bot/bot-003/logs")
        assert resp.status_code == 200
        body = resp.json()
        assert body["logs"] == []
        assert "机器人未连接" in body["error"]


def test_run_detail_degrades_when_task_expired(settings, store):
    """任务过期/机器人离线时详情降级为空，截图入口不能崩。"""
    class DetailFailClient(YingdaoClient):
        async def task_process_detail(self, task_uuid, bot_uuid):
            raise RuntimeError("任务详情不可用")

    with TestClient(create_app(settings=settings,
                              client=DetailFailClient(settings, mock_store=store),
                              store=store)) as local:
        resp = local.get("/api/run/run-003/detail?botUuid=bot-003")
        assert resp.status_code == 200
        body = resp.json()
        assert body["jobs"] == []
        assert body["error"]


def test_board_page_served_and_root_redirects(api):
    """手机浏览器看板：同源静态页可访问，根路径自动跳转。"""
    root = api.get("/", follow_redirects=False)
    assert root.status_code in (302, 307)
    assert root.headers["location"] == "/board"
    page = api.get("/board")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    html = page.text
    for marker in ("影刀机器人指挥中心", "/api/snapshot", "/ws", "data-tab"):
        assert marker in html


def test_board_ui_covers_six_features(api):
    """看板页需覆盖本轮 6 项优化，且不能把密钥写死在前端。"""
    html = api.get("/board").text
    features = {
        "关于改为设置": "data-tab=\"settings\"",
        "异常重试": "/api/control/retry",
        "失败截图": "/detail?botUuid=",
        "错误日志": "/logs?botUuid=",
        "流程搜索": "/api/apps/search",
        "远程运行": "/api/control/start",
        "密钥配置": "/api/settings/credentials",
        "静态预览": "location.protocol === 'file:'",
    }
    for label, marker in features.items():
        assert marker in html, f"看板缺少：{label}"
    for secret_marker in ("AKDEMO", "SECdemo99", "accessKeySecret\":\"AKDEMO"):
        assert secret_marker not in html, "看板里出现密钥明文"


def test_board_three_segments_are_exclusive(api):
    """看板分段改为 机器人 / 运行中 / 已完成，三个区域互斥展示。"""
    html = api.get("/board").text
    for marker in ('data-filter="bots"', 'data-filter="running"', 'data-filter="done"',
                   'id="cardBots"', 'id="cardRuns"', 'id="runTitle"', 'function applyFilter'):
        assert marker in html, f"看板缺少分段标记：{marker}"
    assert 'data-filter="all"' not in html, "旧的「全部」筛选未移除"
    assert 'data-filter="fail"' not in html, "旧的「异常」筛选未移除（异常已有独立标签页）"


def test_snapshot_shape(api):
    body = api.get("/api/snapshot").json()
    assert body["type"] == "snapshot"
    data = body["data"]
    assert data["overview"]["bot_total"] == 4
    assert len(data["bots"]) == 4 and len(data["runs"]) == 4
    assert data["runs"][0]["duration_sec"] == 120


def test_websocket_first_frame_is_snapshot(api):
    with api.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        assert msg["data"]["overview"]["success_rate"] == 50


def test_callback_is_pushed_to_connected_client(api):
    with api.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "snapshot"
        resp = api.post("/api/callback", json={"jobUuid": "j1", "status": "fail"})
        assert resp.json()["connections"] == 1
        pushed = ws.receive_json()
        assert pushed["type"] == "callback"
        assert pushed["data"]["status"] == "fail"


def test_websocket_ping_pong(api):
    with api.websocket_connect("/ws") as ws:
        ws.receive_json()  # snapshot
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


def test_stop_job_requires_uuid(api):
    assert api.post("/api/control/stop", json={}).json()["success"] is False


def test_stop_job_ok_and_broadcasts(api):
    with api.websocket_connect("/ws") as ws:
        ws.receive_json()
        resp = api.post("/api/control/stop", json={"jobUuid": "j1"})
        assert resp.json()["success"] is True
        pushed = ws.receive_json()
        assert pushed["type"] == "control_result"
        assert pushed["data"]["jobUuid"] == "j1"


def test_stop_by_task_resolves_job_uuid(api):
    body = api.post("/api/control/stop-by-task",
                    json={"taskUuid": "run-003", "botUuid": "bot-003"}).json()
    assert body["success"] is True
    assert body["jobUuid"] == "job-running-run-003"


def test_stop_by_task_requires_task_uuid(api):
    assert api.post("/api/control/stop-by-task", json={}).json()["success"] is False


def test_stop_job_returns_friendly_error(api, monkeypatch):
    from app.yingdao_client import YingdaoAPIError

    async def reject(_job_uuid):
        raise YingdaoAPIError("任务已结束")

    monkeypatch.setattr(api.app.state.client, "job_stop", reject)
    body = api.post("/api/control/stop", json={"jobUuid": "j1"}).json()
    assert body["success"] is False
    assert "任务已结束" in body["msg"]


def test_detail_and_logs_endpoints(api):
    detail = api.get("/api/run/run-003/detail").json()
    assert detail["jobs"][0]["remark"] == "元素未找到"
    assert detail["botUuid"] == "bot-003"      # 真实接口必须传匹配的机器人 uuid
    logs = api.get("/api/bot/bot-003/logs").json()
    assert len(logs["logs"]) == 3
    assert logs["jobUuid"] == "job-run-003"    # newest -> process/detail -> log/search 链路
