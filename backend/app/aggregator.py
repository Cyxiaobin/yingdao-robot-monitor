"""轮询聚合与状态 diff：把影刀原始响应压成看板快照，只在变化时推送。

2026-11-17：按需求只展示「当天」的实际运行情况，历史记录不进快照。
"""
from __future__ import annotations

from datetime import date, datetime

from .models import BotStatus, Overview, RunRecord, Snapshot
from .yingdao_client import YingdaoClient

# 2026-11-16 真实联调实测枚举：
#   client/list status: idle, offline（运行中/异常态未出现，保留常见值兜底）
#   task/newest/list status: finish, error, stopped（另有 running/waiting 等推测值）
_BOT_RUNNING = {"running", "busy", "executing"}
_BOT_IDLE = {"idle", "online", "free"}
_BOT_ERROR = {"error", "exception", "fail", "failed"}
_BOT_OFFLINE = {"offline", "disconnected", "off"}

_RUN_SUCCESS = {"success", "succeed", "finished", "completed", "done", "finish"}
_RUN_FAIL = {"fail", "failed", "error", "exception", "timeout", "cancel", "cancelled", "stopped"}
_RUN_RUNNING = {"running", "executing", "waiting", "pending", "queue", "dispatching"}

_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S")


def normalize_bot_state(status: str) -> str:
    s = (status or "").strip().lower()
    if s in _BOT_RUNNING:
        return "running"
    if s in _BOT_IDLE:
        return "idle"
    if s in _BOT_ERROR:
        return "error"
    if s in _BOT_OFFLINE:
        return "offline"
    return "unknown"


def normalize_run_state(status: str) -> str:
    s = (status or "").strip().lower()
    if s in _RUN_SUCCESS:
        return "success"
    if s in _RUN_FAIL:
        return "fail"
    if s in _RUN_RUNNING:
        return "running"
    return "unknown"


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _duration_sec(start: str, end: str) -> int:
    a, b = _parse_time(start), _parse_time(end)
    if a is None or b is None or b < a:
        return 0
    return int((b - a).total_seconds())


def _run_date(run) -> date | None:
    """取运行归属日期：优先 createTime，其次开始/结束时间。

    真实联调里 task/newest/list 只有 createTime / updateTime；
    连时间都拿不到的脏数据直接排除，避免把历史记录混进「今日」。
    """
    for value in (run.create_time, run.start_time, run.end_time):
        parsed = _parse_time(value)
        if parsed is not None:
            return parsed.date()
    return None


def filter_today(runs: list, today: date | None = None) -> list:
    """只保留当天运行记录；today 参数便于测试跨天边界。"""
    day = today or datetime.now().date()
    return [r for r in runs if _run_date(r) == day]


# 真实联调确认：task/newest/list 用 result，process/detail 用 jobList，log/search 用 logs
_LIST_KEYS = ("result", "dataList", "list", "records", "jobList", "logs")


def _extract_list(payload: dict, *keys: str) -> list[dict]:
    """兼容影刀各接口响应层级：data 为数组 / data.<key> / 顶层 <key>。"""
    wanted = tuple(dict.fromkeys((*keys, *_LIST_KEYS)))
    data = payload.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in wanted:
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    for key in wanted:
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def build_snapshot(clients_resp: dict, newest_resp: dict, ts: str | None = None,
                   today: date | None = None, only_today: bool = True) -> Snapshot:
    """构建看板快照。默认只保留当天运行记录（历史数据不进看板）。"""
    bots: list[BotStatus] = []
    for raw in _extract_list(clients_resp, "dataList"):
        bots.append(BotStatus(
            uuid=str(raw.get("robotClientUuid") or raw.get("robotUuid") or ""),
            name=str(raw.get("robotClientName") or raw.get("accountName") or "未命名机器人"),
            ip=str(raw.get("clientIp") or ""),
            status=str(raw.get("status") or "unknown"),
            machine_name=str(raw.get("machineName") or ""),
            current_app=str(raw.get("description") or ""),
        ))

    runs: list[RunRecord] = []
    for raw in _extract_list(newest_resp, "result"):
        clients = raw.get("taskClients")
        first_client = (
            clients[0]
            if isinstance(clients, list) and clients and isinstance(clients[0], dict)
            else {}
        )
        # 列表接口无 startTime/endTime，用 sceneInstStartTime / createTime / updateTime 兜底
        start = str(raw.get("startTime") or first_client.get("sceneInstStartTime")
                    or raw.get("createTime") or "")
        end = str(raw.get("endTime") or raw.get("updateTime") or "")
        runs.append(RunRecord(
            id=str(raw.get("taskUuid") or raw.get("jobUuid") or ""),
            app_name=str(raw.get("taskName") or first_client.get("currentRobotName")
                         or raw.get("robotName") or raw.get("appName") or "未命名应用"),
            status=str(raw.get("status") or "unknown"),
            start_time=start,
            end_time=end,
            create_time=str(raw.get("createTime") or ""),
            remark=str(raw.get("remark") or ""),
            screenshot_url=str(raw.get("screenshotUrl") or ""),
            bot_uuid=str(first_client.get("robotClientUuid") or ""),
            duration_sec=_duration_sec(start, end),
        ))

    # 只展示当天的实际运行情况：历史记录不进列表、不进概览、不报警
    day = today or datetime.now().date()
    if only_today:
        runs = filter_today(runs, day)

    success = sum(1 for r in runs if normalize_run_state(r.status) == "success")
    fail = sum(1 for r in runs if normalize_run_state(r.status) == "fail")
    terminal = success + fail
    online = sum(1 for b in bots if normalize_bot_state(b.status) not in ("offline", "unknown"))

    overview = Overview(
        bot_total=len(bots),
        bot_online=online,
        runs_today=len(runs),
        success_rate=round(success / terminal * 100) if terminal else 0,
        error_count=fail,
    )
    return Snapshot(ts=ts or _now(), day=day.isoformat(),
                    overview=overview, bots=bots, runs=runs)


def diff_snapshots(old: Snapshot | None, new: Snapshot) -> dict | None:
    """只在状态真变化时返回增量；无变化返回 None（不推送、不耗电）。"""
    if old is None:
        return None  # 首帧单独发 snapshot

    old_bots = {b.uuid: b.status for b in old.bots}
    old_run_ids = {r.id for r in old.runs}

    bot_changes = [
        {"uuid": b.uuid, "from": old_bots.get(b.uuid), "to": b.status, "bot": b.to_dict()}
        for b in new.bots
        if old_bots.get(b.uuid) != b.status
    ]
    new_runs = [r.to_dict() for r in new.runs if r.id not in old_run_ids]

    overview_changed = old.overview != new.overview
    if not (bot_changes or new_runs or overview_changed):
        return None
    return {
        "has_changes": True,
        "overview": new.overview.to_dict(),
        "bots": bot_changes,
        "runs": new_runs,
        "ts": new.ts,
    }


class Aggregator:
    def __init__(self, client: YingdaoClient) -> None:
        self.client = client
        self.snapshot: Snapshot | None = None

    async def poll_once(self) -> tuple[Snapshot, dict | None]:
        clients_resp = await self.client.client_list()
        newest_resp = await self.client.task_newest_list()
        snap = build_snapshot(clients_resp, newest_resp)
        delta = diff_snapshots(self.snapshot, snap)
        self.snapshot = snap
        return snap, delta

    def reset(self) -> None:
        self.snapshot = None
