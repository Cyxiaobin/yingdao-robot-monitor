"""MOCK 模式数据源：按 2026-11-16 真实联调响应结构构造（已脱敏）。

真实结构要点：
  client/list      -> data 为数组
  task/newest/list -> data.pageDTO + data.result[]（无 startTime/endTime/screenshotUrl）
  task/process/detail -> data.jobList[]（含 jobUuid、remark、screenshotUrl）
  job/log/search   -> data.page + data.logs[]（time/level/text/logId）

advance() 可制造一次状态变化，供轮询 / diff / WebSocket 测试与本地演示使用。
"""
from __future__ import annotations

from datetime import datetime, timedelta

_TIME_FMT = "%Y-%m-%d %H:%M:%S"


def _ts(minutes_ago: int) -> str:
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime(_TIME_FMT)


def _client(bot_uuid: str, name: str, app: str, status: str, ip: str, machine: str, start: str) -> dict:
    return {
        "robotClientUuid": bot_uuid,
        "robotClientName": name,
        "currentRobotUuid": "robot-" + bot_uuid,
        "currentRobotName": app,
        "sceneInstStartTime": start,
        "clientStatus": status,
        "clientStatusName": {"finish": "完成", "error": "异常", "stopped": "已停止"}.get(status, status),
        "clientIp": ip,
        "machineName": machine,
    }


class MockStore:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._tick = 0
        self._bots = [
            {"robotClientUuid": "bot-001", "robotClientName": "admin@ydsc",
             "status": "running", "description": "抖音电商罗盘抓取",
             "machineName": "RPA-PC-01", "clientIp": "10.0.0.79"},
            {"robotClientUuid": "bot-002", "robotClientName": "finance-bot",
             "status": "idle", "description": "应收三表匹配",
             "machineName": "RPA-PC-02", "clientIp": "10.0.0.81"},
            {"robotClientUuid": "bot-003", "robotClientName": "refund-bot",
             "status": "error", "description": "退单写入",
             "machineName": "RPA-PC-03", "clientIp": "10.0.0.82"},
            {"robotClientUuid": "bot-004", "robotClientName": "shop-bot",
             "status": "offline", "description": "美妆小店GMV",
             "machineName": "RPA-PC-04", "clientIp": "10.0.0.83"},
        ]
        self._runs = self._initial_runs()

    def _initial_runs(self) -> list[dict]:
        return [
            {"taskUuid": "run-001", "taskName": "抖音电商罗盘抓取", "status": "finish",
             "createTime": _ts(5), "updateTime": _ts(3), "remark": "结束任务",
             "taskClients": [_client("bot-001", "admin@ydsc", "抖音电商罗盘抓取",
                                     "finish", "10.0.0.79", "RPA-PC-01", _ts(5))]},
            {"taskUuid": "run-002", "taskName": "应收三表匹配", "status": "finish",
             "createTime": _ts(11), "updateTime": _ts(8), "remark": "结束任务",
             "taskClients": [_client("bot-002", "finance-bot", "应收三表匹配",
                                     "finish", "10.0.0.81", "RPA-PC-02", _ts(11))]},
            {"taskUuid": "run-003", "taskName": "退单写入", "status": "error",
             "createTime": _ts(13), "updateTime": _ts(12), "remark": "运行异常",
             "taskClients": [_client("bot-003", "refund-bot", "退单写入",
                                     "error", "10.0.0.82", "RPA-PC-03", _ts(13))]},
            {"taskUuid": "run-004", "taskName": "门店-退单核对", "status": "stopped",
             "createTime": _ts(16), "updateTime": _ts(15), "remark": "任务取消-控制台手动取消",
             "taskClients": [_client("bot-004", "shop-bot", "门店-退单核对",
                                     "stopped", "10.0.0.83", "RPA-PC-04", _ts(16))]},
        ]

    @staticmethod
    def _ok(data) -> dict:
        return {"code": 200, "success": True, "msg": "success", "data": data,
                "requestId": "mock-request-id"}

    def token_create(self) -> dict:
        return self._ok({"accessToken": "MOCK_ACCESS_TOKEN", "expiresIn": 7199})

    def client_list(self) -> dict:
        return self._ok([dict(b) for b in self._bots])

    def task_newest_list(self) -> dict:
        rows = [dict(r) for r in self._runs]
        return self._ok({"pageDTO": {"total": len(rows), "size": 50, "page": 1,
                                     "pages": 1, "offset": 0, "order": "desc"},
                         "result": rows})

    def job_query(self, job_uuid: str) -> dict:
        return self._ok({"jobUuid": job_uuid, "status": "running", "statusName": "运行中"})

    def task_process_detail(self, task_uuid: str, robot_client_uuid: str) -> dict:
        # 同一任务下可有多个 job 实例（重试）；第二条模拟仍在运行，供 stop-by-task 使用
        return self._ok({"jobList": [
            {"jobUuid": "job-" + task_uuid, "taskUuid": task_uuid,
             "status": "error", "startTime": _ts(13), "endTime": _ts(12),
             "remark": "元素未找到", "screenshotUrl": "https://example.com/shot-003.png",
             "robotClientUuid": robot_client_uuid, "robotName": "退单写入"},
            {"jobUuid": "job-running-" + task_uuid, "taskUuid": task_uuid,
             "status": "running", "startTime": _ts(1), "endTime": "",
             "remark": "", "screenshotUrl": "",
             "robotClientUuid": robot_client_uuid, "robotName": "退单写入"},
        ]})

    def job_log_search(self, job_uuid: str, page: int = 1, size: int = 20) -> dict:
        return self._ok({"page": {"total": 3, "page": page, "size": size}, "logs": [
            {"time": _ts(14), "level": "信息", "text": "开始执行：打开浏览器", "logId": 1},
            {"time": _ts(13), "level": "信息", "text": "写入第 1 批数据", "logId": 2},
            {"time": _ts(12), "level": "错误", "text": "元素未找到：#submit-btn", "logId": 3},
        ]})

    def job_stop(self, job_uuid: str) -> dict:
        return self._ok({"jobUuid": job_uuid, "stopped": True})

    def app_query_list(self, page: int = 1, size: int = 100, app_name: str = "") -> dict:
        """模拟应用列表：结构对齐 /oapi/app/open/query/list（data 为数组、分页在顶层 page）。"""
        rows = [
            {"appId": "app-001", "appName": "退单写入", "appType": "app",
             "appTypeName": "应用", "version": "7", "appStatus": "r",
             "publishTime": _ts(600), "updateTime": _ts(600), "createTime": _ts(20000),
             "ownerName": "张伟", "ownerAccount": "dev@demo", "supportParam": False,
             "description": "松鼠便利退单数据写入 MySQL"},
            {"appId": "app-002", "appName": "门店-退单核对", "appType": "app",
             "appTypeName": "应用", "version": "3", "appStatus": "r",
             "publishTime": _ts(900), "updateTime": _ts(900), "createTime": _ts(20000),
             "ownerName": "张伟", "ownerAccount": "dev@demo", "supportParam": True,
             "description": "门店-退单核对 Excel 入库"},
            {"appId": "app-003", "appName": "应收三表匹配", "appType": "app",
             "appTypeName": "应用", "version": "12", "appStatus": "r",
             "publishTime": _ts(1200), "updateTime": _ts(1200), "createTime": _ts(20000),
             "ownerName": "财务共享", "ownerAccount": "fin@demo", "supportParam": False,
             "description": "公司支付信息 / SAP 银行信息三表匹配"},
            {"appId": "app-004", "appName": "抖音电商罗盘抓取", "appType": "app",
             "appTypeName": "应用", "version": "5", "appStatus": "r",
             "publishTime": _ts(1500), "updateTime": _ts(1500), "createTime": _ts(20000),
             "ownerName": "电商运营", "ownerAccount": "ec@demo", "supportParam": False,
             "description": "罗盘 GMV 与退款数据"},
            {"appId": "app-005", "appName": "未发版草稿流程", "appType": "app",
             "appTypeName": "应用", "version": "1", "appStatus": "r",
             "publishTime": "", "updateTime": _ts(60), "createTime": _ts(60),
             "ownerName": "测试", "ownerAccount": "test@demo", "supportParam": False,
             "description": "无 publishTime，应被搜索结果过滤掉"},
        ]
        if app_name:
            rows = [r for r in rows if app_name in r["appName"]]
        return {"code": 200, "success": True, "msg": "success", "data": rows,
                "page": {"total": len(rows), "size": size, "page": 1, "pages": 1}}

    def job_start(self, robot_uuid: str, account_name: str = "") -> dict:
        return self._ok({"jobUuid": "job-start-" + robot_uuid,
                         "idempotentFlag": False, "accountName": account_name})

    def job_retry(self, job_uuid: str) -> dict:
        return self._ok({"jobUuid": job_uuid, "retried": True})

    def advance(self) -> None:
        """制造一次可观测变化：bot-002 由空闲转运行，并新增一条完成记录。"""
        self._tick += 1
        for bot in self._bots:
            if bot["robotClientUuid"] == "bot-002":
                bot["status"] = "running"
                bot["description"] = "应收三表匹配"
        self._runs.insert(0, {
            "taskUuid": f"run-new-{self._tick}", "taskName": "微信小店GMV同步",
            "status": "finish", "createTime": _ts(1), "updateTime": _ts(0),
            "remark": "结束任务",
            "taskClients": [_client("bot-002", "finance-bot", "微信小店GMV同步",
                                    "finish", "10.0.0.81", "RPA-PC-02", _ts(1))],
        })
