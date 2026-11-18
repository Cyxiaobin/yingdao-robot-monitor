"""聚合器：状态归一化、快照构建、diff 只在变化时推送。"""
import pytest

from app.aggregator import (
    Aggregator,
    _duration_sec,
    _extract_list,
    build_snapshot,
    diff_snapshots,
    normalize_bot_state,
    normalize_run_state,
)
from app.mock_data import MockStore


def _snap(store, ts="2026-01-01T00:00:00"):
    return build_snapshot(store.client_list(), store.task_newest_list(), ts=ts)


@pytest.mark.parametrize("raw,expected", [
    ("running", "running"), ("idle", "idle"), ("error", "error"),
    ("offline", "offline"), ("some_new_enum", "unknown"), ("", "unknown"),
])
def test_normalize_bot_state(raw, expected):
    assert normalize_bot_state(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("success", "success"), ("finish", "success"), ("fail", "fail"),
    ("error", "fail"), ("stopped", "fail"), ("running", "running"),
    ("new_status", "unknown"),
])
def test_normalize_run_state(raw, expected):
    assert normalize_run_state(raw) == expected


@pytest.mark.parametrize("start,end,expected", [
    ("2026-01-01 10:00:00", "2026-01-01 10:02:00", 120),
    ("2026-01-01 10:02:00", "2026-01-01 10:00:00", 0),
    ("", "2026-01-01 10:00:00", 0),
    ("bad", "bad", 0),
])
def test_duration(start, end, expected):
    assert _duration_sec(start, end) == expected


def test_extract_list_handles_three_shapes():
    assert _extract_list({"data": [{"a": 1}]}, "dataList") == [{"a": 1}]
    assert _extract_list({"data": {"dataList": [{"a": 1}]}}, "dataList") == [{"a": 1}]
    assert _extract_list({"dataList": [{"a": 1}]}, "dataList") == [{"a": 1}]
    # 2026-11-16 真实联调确认的层级
    assert _extract_list({"data": {"result": [{"a": 1}]}}) == [{"a": 1}]
    assert _extract_list({"data": {"jobList": [{"a": 1}]}}) == [{"a": 1}]
    assert _extract_list({"data": {"logs": [{"a": 1}]}}) == [{"a": 1}]
    assert _extract_list({"data": None}, "dataList") == []


def test_build_snapshot_matches_dashboard():
    store = MockStore()
    snap = _snap(store)

    assert snap.overview.bot_total == 4
    assert snap.overview.bot_online == 3      # offline 不计
    assert snap.overview.runs_today == 4
    assert snap.overview.success_rate == 50   # 2 成功 / 2 失败
    assert snap.overview.error_count == 2

    bot = snap.bots[0]
    assert bot.name == "admin@ydsc" and bot.ip == "10.0.0.79"
    assert bot.status == "running"

    run = snap.runs[0]
    assert run.app_name == "抖音电商罗盘抓取"
    assert run.duration_sec == 120
    assert snap.runs[2].remark == "运行异常"          # 真实列表只给简要备注
    assert snap.runs[2].bot_uuid == "bot-003"         # 详情接口需要
    assert snap.runs[2].screenshot_url == ""          # 截图只在 process/detail 里


def test_diff_returns_none_when_nothing_changed():
    store = MockStore()
    old = _snap(store)
    new = _snap(store, ts="2026-01-01T00:00:05")
    assert diff_snapshots(old, new) is None


def test_diff_returns_none_for_first_snapshot():
    assert diff_snapshots(None, _snap(MockStore())) is None


def test_diff_detects_bot_change_and_new_run():
    store = MockStore()
    old = _snap(store)
    store.advance()
    new = _snap(store, ts="2026-01-01T00:00:05")
    delta = diff_snapshots(old, new)

    assert delta["has_changes"] is True
    assert any(c["uuid"] == "bot-002" and c["from"] == "idle" and c["to"] == "running"
               for c in delta["bots"])
    assert any(r["app_name"] == "微信小店GMV同步" for r in delta["runs"])
    assert delta["overview"]["runs_today"] == 5


async def test_aggregator_poll_once_integration(client, store):
    agg = Aggregator(client)
    first, delta = await agg.poll_once()
    assert delta is None and agg.snapshot is first

    _, still_none = await agg.poll_once()
    assert still_none is None

    store.advance()
    _, changed = await agg.poll_once()
    assert changed is not None and changed["has_changes"] is True
