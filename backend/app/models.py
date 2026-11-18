"""看板数据模型：纯 dataclass，序列化用 asdict，避免引入额外依赖。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class BotStatus:
    uuid: str
    name: str
    ip: str
    status: str = "unknown"          # 影刀原始 status
    machine_name: str = ""
    current_app: str = ""             # 当前在跑的应用名，无则空

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunRecord:
    id: str
    app_name: str
    status: str = "unknown"           # 影刀原始 status
    start_time: str = ""
    end_time: str = ""
    create_time: str = ""
    remark: str = ""
    screenshot_url: str = ""          # 列表接口无此字段，详情接口 jobList 才有
    bot_uuid: str = ""                # 来自 taskClients[0]，用于拉详情/日志
    duration_sec: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Overview:
    bot_total: int = 0
    bot_online: int = 0
    runs_today: int = 0
    success_rate: int = 0             # 百分比整数，如 95
    error_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Snapshot:
    ts: str
    overview: Overview
    day: str = ""                     # 数据归属日期 YYYY-MM-DD（仅展示当天）
    bots: list[BotStatus] = field(default_factory=list)
    runs: list[RunRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "date": self.day,
            "overview": self.overview.to_dict(),
            "bots": [b.to_dict() for b in self.bots],
            "runs": [r.to_dict() for r in self.runs],
        }
