"""报警去重：同一应用 + 同一原因在窗口期内只推送一次。

内存态即可：服务重启后重新计数，不做持久化（避免引入数据库）。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .aggregator import normalize_run_state


class AlarmTracker:
    def __init__(self, window_sec: int = 300) -> None:
        self.window = timedelta(seconds=window_sec)
        self._last: dict[tuple[str, str], datetime] = {}

    def new_alarms(self, runs: list[dict], now: datetime | None = None) -> list[dict]:
        """从新增运行记录里筛出需要推送的异常（入参为 RunRecord.to_dict() 列表）。"""
        now = now or datetime.now()
        out: list[dict] = []
        for run in runs:
            if normalize_run_state(str(run.get("status") or "")) != "fail":
                continue
            app_name = str(run.get("app_name") or "")
            reason = str(run.get("remark") or run.get("status") or "")
            key = (app_name, reason)
            last = self._last.get(key)
            if last is not None and now - last < self.window:
                continue
            self._last[key] = now
            out.append({
                "id": str(run.get("id") or ""),
                "app_name": app_name,
                "status": str(run.get("status") or ""),
                "remark": reason,
                "bot_uuid": str(run.get("bot_uuid") or ""),
                "create_time": str(run.get("create_time") or ""),
                "ts": now.isoformat(timespec="seconds"),
            })
        return out
