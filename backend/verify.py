"""阶段0 联调脚本：只读验证影刀开放 API，打印原始响应与字段核对摘要。

用法（在 backend 目录下，配置好 .env 或环境变量）：
    python verify.py

安全约束：本脚本只调用查询类接口，绝不调用 job/start、job/stop 等写操作。
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter

from app.config import Settings
from app.yingdao_client import YingdaoClient


def rows_of(resp: dict) -> list:
    """兼容影刀不同接口的响应层级：data 为数组 / data.dataList / 顶层 dataList。"""
    data = resp.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("result", "dataList", "list", "records", "jobList", "logs"):
            if isinstance(data.get(key), list):
                return data[key]
    for key in ("result", "dataList", "list"):
        if isinstance(resp.get(key), list):
            return resp[key]
    return []


def first_of(rows: list, *keys: str) -> str:
    """从列表里取第一个非空字段，用于给详情接口传真实 ID。"""
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in keys:
            if row.get(key):
                return str(row[key])
    return ""


def pick_run(rows: list, status: str | None = None) -> dict:
    """挑一条指定状态的记录；找不到就退回首条，便于打印样本。"""
    for row in rows:
        if isinstance(row, dict) and (status is None or row.get("status") == status):
            return row
    return {}


def summarize(name: str, resp: dict) -> None:
    rows = [r for r in rows_of(resp) if isinstance(r, dict)]
    fields = sorted({k for r in rows for k in r})
    statuses = Counter(str(r.get("status")) for r in rows if r.get("status") is not None)
    print(f"\n--- {name} 字段核对 ---")
    print(f"条数: {len(rows)}")
    print(f"字段: {', '.join(fields) if fields else '(无)'}")
    print(f"status 枚举: {dict(statuses) if statuses else '(无)'}")


def show(name: str, resp: dict) -> None:
    print(f"\n=== {name} ===\n{json.dumps(resp, ensure_ascii=False, indent=2)[:2000]}")


async def safe(name: str, factory) -> dict | None:
    try:
        resp = await factory()
        show(name, resp)
        return resp
    except Exception as exc:
        print(f"\n=== {name} 失败: {type(exc).__name__}: {exc}")
        return None


async def main() -> None:
    settings = Settings.from_env()
    print(f"模式: {'MOCK' if settings.mock_mode else '真实'} | 域名: {settings.base_url}")
    print(f"凭证: {settings.access_key_id[:6]}*** | 平台级: {'@platform' in settings.access_key_id}")
    client = YingdaoClient(settings)

    await safe("token/create", client._fetch_token_data)

    clients_resp = await safe("client/list", lambda: client.client_list())
    newest_resp = await safe("task/newest/list", lambda: client.task_newest_list(size=100))

    bots = rows_of(clients_resp or {})
    runs = rows_of(newest_resp or {})
    if clients_resp:
        summarize("client/list", clients_resp)
    if newest_resp:
        summarize("task/newest/list", newest_resp)

    for status in sorted({str(r.get("status")) for r in runs if isinstance(r, dict) and r.get("status")}):
        show(f"样本 status={status}", pick_run(runs, status))

    probe = pick_run(runs, "error") or pick_run(runs)
    task_uuid = str(probe.get("taskUuid") or "")
    bot_uuid = first_of(probe.get("taskClients") or [], "robotClientUuid") or first_of(
        bots, "robotClientUuid", "robotUuid", "uuid"
    )
    job_uuid = first_of(runs, "jobUuid", "appUuid") or task_uuid
    print(f"\n探测记录: {probe.get('taskName')} | status={probe.get('status')}")
    print(f"探测用真实 ID: bot={bot_uuid or '(无)'} task={task_uuid or '(无)'} job={job_uuid or '(无)'}")

    real_job_uuid = job_uuid
    if task_uuid and bot_uuid:
        detail = await safe("task/process/detail", lambda: client.task_process_detail(task_uuid, bot_uuid))
        if detail:
            jobs = rows_of(detail)
            show("task/process/detail 内层列表", {"data": {"jobList": jobs}})
            summarize("task/process/detail", {"data": {"jobList": jobs}})
            real_job_uuid = first_of(jobs, "jobUuid", "uuid") or job_uuid
    else:
        print("\n跳过 task/process/detail：缺 taskUuid 或 robotClientUuid")

    if real_job_uuid:
        await safe("job/query", lambda: client.job_query(real_job_uuid))
        logs = await safe("job/log/search", lambda: client.job_log_search(real_job_uuid))
        if logs:
            log_rows = rows_of(logs)
            print(f"\n--- job/log/search 字段核对 ---\n条数: {len(log_rows)}\n"
                  f"字段: {', '.join(sorted({k for r in log_rows if isinstance(r, dict) for k in r})) or '(无)'}")
    else:
        print("\n跳过 job/query、job/log/search：无可用 jobUuid")

    await client.aclose()
    print("\n=== 联调结束（全程只读）===")


if __name__ == "__main__":
    asyncio.run(main())
