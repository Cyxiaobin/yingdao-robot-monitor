"""报警去重：只推异常、同因同应用窗口期抑制、换原因/过窗口仍推。"""
from datetime import datetime, timedelta

from app.alarms import AlarmTracker


def _run(run_id: str, app: str, status: str, remark: str = "") -> dict:
    return {"id": run_id, "app_name": app, "status": status, "remark": remark,
            "bot_uuid": "bot-1", "create_time": "2026-11-17 08:00:00"}


def test_only_fail_records_become_alarms():
    out = AlarmTracker().new_alarms([
        _run("1", "商超订单同步", "finish", "结束任务"),
        _run("2", "鲜活GO报数", "error", "运行异常"),
        _run("3", "天香保百", "stopped", "任务取消"),
        _run("4", "银企直连", "running", ""),
    ])
    assert len(out) == 2
    assert [a["app_name"] for a in out] == ["鲜活GO报数", "天香保百"]
    assert out[0]["status"] == "error" and out[0]["id"] == "2"


def test_same_app_same_reason_is_suppressed_within_window():
    tracker = AlarmTracker(window_sec=300)
    now = datetime(2026, 11, 17, 8, 0, 0)
    first = tracker.new_alarms([_run("1", "鲜活GO", "error", "元素未找到")], now)
    second = tracker.new_alarms([_run("2", "鲜活GO", "error", "元素未找到")],
                                now + timedelta(seconds=60))
    assert len(first) == 1
    assert second == []


def test_different_reason_and_expired_window_still_push():
    tracker = AlarmTracker(window_sec=300)
    now = datetime(2026, 11, 17, 8, 0, 0)
    tracker.new_alarms([_run("1", "鲜活GO", "error", "元素未找到")], now)
    other = tracker.new_alarms([_run("2", "鲜活GO", "error", "登录态失效")],
                               now + timedelta(seconds=10))
    expired = tracker.new_alarms([_run("3", "鲜活GO", "error", "登录态失效")],
                                 now + timedelta(seconds=400))
    assert len(other) == 1 and len(expired) == 1


def test_alarm_payload_has_fields_frontend_needs():
    out = AlarmTracker().new_alarms([_run("t1", "商超采购单", "error", "运行异常")])
    assert set(["id", "app_name", "status", "remark", "bot_uuid", "create_time", "ts"]) <= set(out[0])
