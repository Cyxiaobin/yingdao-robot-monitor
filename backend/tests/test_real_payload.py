"""2026-11-16 真实联调响应样本（脱敏）回归测试。

锁死四个易错点：data.result 层级、status 枚举 finish/error/stopped、
taskName + taskClients 字段映射、列表无截图字段。
"""
from datetime import datetime, timedelta

from app.aggregator import _extract_list, build_snapshot, normalize_run_state

_FMT = "%Y-%m-%d %H:%M:%S"


def _ago(seconds: int) -> str:
    return (datetime.now() - timedelta(seconds=seconds)).strftime(_FMT)


def _days_ago(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).strftime(_FMT)


def _clients() -> dict:
    return {"code": 200, "success": True, "data": [
        {"robotClientUuid": "c1", "robotClientName": "bot-a", "status": "idle",
         "clientIp": "10.0.0.1", "machineName": "PC-A", "clientVersion": "6.3.39"},
        {"robotClientUuid": "c2", "robotClientName": "bot-b", "status": "offline",
         "clientIp": "10.0.0.2", "machineName": "PC-B", "clientVersion": "6.3.22"},
    ]}


def _newest(old_record: bool = False) -> dict:
    rows = [
        {"taskUuid": "t1", "taskName": "商超订单同步", "status": "finish",
         "createTime": _ago(300), "updateTime": _ago(180), "remark": "结束任务",
         "taskClients": [{"robotClientUuid": "c1", "robotClientName": "bot-a",
                          "currentRobotName": "商超-订单同步-2.0",
                          "sceneInstStartTime": _ago(300), "clientStatus": "finish",
                          "clientStatusName": "完成", "clientIp": "10.0.0.1"}]},
        {"taskUuid": "t2", "taskName": "鲜活GO报数", "status": "error",
         "createTime": _ago(600), "updateTime": _ago(540), "remark": "运行异常",
         "taskClients": [{"robotClientUuid": "c2", "robotClientName": "bot-b",
                          "currentRobotName": "鲜活GO报数_A2",
                          "sceneInstStartTime": _ago(600), "clientStatus": "error",
                          "clientStatusName": "异常"}]},
        {"taskUuid": "t3", "taskName": "天香保百", "status": "stopped",
         "createTime": _days_ago(2) if old_record else _ago(900),
         "updateTime": _days_ago(2) if old_record else _ago(870),
         "remark": "任务取消-控制台手动取消",
         "taskClients": [{"robotClientUuid": "c1", "currentRobotName": "唯品001-保百",
                          "sceneInstStartTime": _ago(900), "clientStatus": "stopped"}]},
    ]
    return {"code": 200, "success": True,
            "data": {"pageDTO": {"total": len(rows), "size": 50, "page": 1, "pages": 1},
                     "result": rows}}


def test_real_payload_parses_into_snapshot():
    snap = build_snapshot(_clients(), _newest())
    assert len(snap.bots) == 2 and snap.overview.bot_online == 1
    assert len(snap.runs) == 3

    run = snap.runs[0]
    assert run.id == "t1"
    assert run.app_name == "商超订单同步"        # 真实字段是 taskName，不是 robotName
    assert run.duration_sec == 120               # createTime -> updateTime
    assert run.bot_uuid == "c1"
    assert run.screenshot_url == ""              # 列表接口确实没有

    assert normalize_run_state(run.status) == "success"
    assert normalize_run_state(snap.runs[1].status) == "fail"
    assert normalize_run_state(snap.runs[2].status) == "fail"

    assert snap.overview.runs_today == 3
    assert snap.overview.success_rate == 33      # 1 成功 / 3 终态
    assert snap.overview.error_count == 2


def test_snapshot_only_keeps_today_records():
    """2026-11-17：历史运行既不进列表，也不进概览统计、不报警。"""
    snap = build_snapshot(_clients(), _newest(old_record=True))
    assert len(snap.runs) == 2                  # 前两天的记录被过滤掉
    assert [r.id for r in snap.runs] == ["t1", "t2"]
    assert snap.overview.runs_today == 2
    assert snap.overview.success_rate == 50
    assert snap.overview.error_count == 1
    assert snap.day == datetime.now().date().isoformat()


def test_detail_and_log_payload_shapes():
    detail = {"code": 200, "success": True, "data": {"jobList": [{
        "jobUuid": "j1", "taskUuid": "t2", "status": "error",
        "remark": "任务失败，在【登录】中第21行：无效的截图区域",
        "screenshotUrl": "https://example.com/error.png",
        "startTime": _ago(600), "endTime": _ago(540), "robotName": "鲜活GO报数_A2",
    }]}}
    logs = {"code": 200, "success": True, "data": {
        "page": {"total": 13, "page": 1, "size": 20},
        "logs": [{"time": "11/16/2026 17:00:11", "level": "信息",
                  "text": "开始执行...", "logId": 1}]}}

    jobs = _extract_list(detail)
    assert len(jobs) == 1
    assert jobs[0]["jobUuid"] == "j1" and jobs[0]["screenshotUrl"]
    assert _extract_list(logs)[0]["text"] == "开始执行..."
