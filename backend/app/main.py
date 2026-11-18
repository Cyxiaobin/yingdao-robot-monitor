"""FastAPI 入口：REST 首屏 + WebSocket 实时推送 + 影刀回调 + 远程控制。"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from .aggregator import Aggregator, _extract_list, normalize_run_state
from .alarms import AlarmTracker
from .apps import AppCatalog
from .config import Settings
from .connection_manager import ConnectionManager
from .mock_data import MockStore
from .users import AuthService, SessionStore, UserStore, validate_password
from .yingdao_client import YingdaoClient


def _ts() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


# job/retry 官方说明：仅「异常」或「已停止」状态可重试
_RETRYABLE = {"error", "exception", "fail", "failed", "stopped",
              "cancel", "cancelled", "timeout"}

# 设置页写凭证的目标文件；测试可 monkeypatch 到临时路径，避免碰真实 .env
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
# 账号库默认位置；测试可 monkeypatch 到 tmp_path，或用 AUTH_USERS_FILE 覆盖
_USERS_PATH = Path(__file__).resolve().parent.parent / "data" / "users.json"

# 免登录路径：静态看板页本身必须能打开（登录框在页面里），登录/查询登录态同理
_PUBLIC_PATHS = {"/", "/health", "/board", "/favicon.ico",
                 "/api/auth/login", "/api/auth/me", "/api/auth/logout",
                 # 影刀回调由外部系统发起，无法携带本系统的会话 token；
                 # 改由 CALLBACK_TOKEN 请求头校验（见 yingdao_callback）
                 "/api/callback"}

# 仅超级管理员可调用的写操作前缀（普通用户保留只读监控能力）
_ADMIN_WRITE_PREFIXES = (
    "/api/control/",              # start / retry / stop / stop-by-task 均会真实操作影刀
    "/api/apps/refresh",          # 强制刷新目录会撞影刀限频
    "/api/settings/test",         # 用当前凭证探测连通性
    "/api/settings/credentials",  # 更换影刀密钥
)
# 强制改密期间允许的接口：只够完成改密 + 登出 + 读取自身状态
_MUST_CHANGE_ALLOWED = {"/api/auth/password", "/api/auth/logout", "/api/auth/me"}
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


async def _poll_loop(app: FastAPI) -> None:
    agg: Aggregator = app.state.aggregator
    manager: ConnectionManager = app.state.manager
    interval = app.state.settings.poll_interval
    while True:
        try:
            snap, delta = await agg.poll_once()
            if delta:
                await manager.broadcast({"type": "delta", "data": delta, "ts": snap.ts})
                # 新增失败记录才判报警，避免每轮重复刷屏
                alarms = app.state.alarms.new_alarms(delta.get("runs") or [])
                if alarms:
                    await manager.broadcast(
                        {"type": "alarm", "data": alarms, "ts": snap.ts}
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # 单轮失败不能让后台任务整体退出
            print(f"[poll] 拉取失败，下轮重试: {exc}")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if app.state.settings.enable_poller:
        task = asyncio.create_task(_poll_loop(app))
    app.state.poll_task = task
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if app.state.owns_client:
            await app.state.client.aclose()


def create_app(
    settings: Settings | None = None,
    client: YingdaoClient | None = None,
    store: MockStore | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    if settings.strict_real and settings.mock_mode:
        raise RuntimeError(
            "STRICT_REAL=1 但当前为 MOCK 模式（凭证缺失或 YINGDAO_MOCK=1），拒绝以假数据启动"
        )
    owns_client = client is None
    client = client or YingdaoClient(settings, mock_store=store)

    app = FastAPI(title="影刀RPA监控中转服务", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.client = client
    app.state.owns_client = owns_client
    app.state.store = store
    app.state.aggregator = Aggregator(client)
    app.state.manager = ConnectionManager()
    app.state.alarms = AlarmTracker()
    app.state.catalog = AppCatalog(client)
    app.state.poll_task = None

    users_path = Path(settings.auth_users_file) if settings.auth_users_file else _USERS_PATH
    app.state.users = UserStore(users_path, settings.super_admin_username,
                                settings.super_admin_password)
    app.state.sessions = SessionStore(settings.session_ttl_hours)
    app.state.auth = AuthService(app.state.users, app.state.sessions)

    def _token_of(request: Request) -> str:
        raw = request.headers.get("authorization", "")
        if raw.lower().startswith("bearer "):
            return raw[7:].strip()
        return request.headers.get("x-auth-token", "").strip()

    @app.middleware("http")
    async def auth_guard(request: Request, call_next):
        """统一登录校验：所有 /api/* 需会话；账号管理接口仅超级管理员可用。"""
        s = app.state.settings
        path = request.url.path
        if not s.auth_required:
            # 本地开发 / 自动化测试：免登录，身份视为管理员
            request.state.user = {"username": "local", "role": "admin"}
            return await call_next(request)
        identity = app.state.auth.resolve(_token_of(request))
        request.state.user = identity
        if path in _PUBLIC_PATHS or not path.startswith("/api/"):
            return await call_next(request)
        if identity is None:
            return JSONResponse(
                status_code=401,
                content={"success": False, "code": "AUTH_REQUIRED",
                         "msg": "未登录或登录已过期，请重新登录"},
            )
        if path.startswith("/api/auth/users") and identity["role"] != "admin":
            return JSONResponse(
                status_code=403,
                content={"success": False, "code": "FORBIDDEN",
                         "msg": "仅超级管理员可以管理账号"},
            )
        # 写操作（真实启停流程 / 改密钥 / 刷新目录）仅管理员可用
        if (request.method in _WRITE_METHODS
                and path.startswith(_ADMIN_WRITE_PREFIXES)
                and identity["role"] != "admin"):
            return JSONResponse(
                status_code=403,
                content={"success": False, "code": "FORBIDDEN",
                         "msg": "该操作仅超级管理员可执行"},
            )
        # 默认口令用户：只允许改密，杜绝 admin123 长期登录执行任意操作
        if (s.enforce_password_change and identity.get("mustChangePassword")
                and path not in _MUST_CHANGE_ALLOWED):
            return JSONResponse(
                status_code=403,
                content={"success": False, "code": "MUST_CHANGE_PASSWORD",
                         "msg": "首次登录请先修改默认密码"},
            )
        return await call_next(request)

    def _client() -> YingdaoClient:
        """永远取最新 client：设置页更换密钥后会热替换，闭包里的旧引用会失效。"""
        return app.state.client

    async def _push(data: dict, kind: str = "control_result") -> None:
        await app.state.manager.broadcast({"type": kind, "ts": _ts(), "data": data})

    def _mask(key: str) -> str:
        if not key:
            return ""
        return key[:6] + "***" + key[-4:] if len(key) > 12 else key[:4] + "***"

    @app.get("/", include_in_schema=False)
    async def root_page() -> RedirectResponse:
        """手机浏览器输 http://<局域网IP>:8000 直接进看板。"""
        return RedirectResponse(url="/board")

    @app.get("/board", include_in_schema=False)
    async def board_page() -> FileResponse:
        """同源手机看板：无需微信开发者工具即可看真实实时数据（只读）。"""
        return FileResponse(Path(__file__).resolve().parent / "board.html",
                            media_type="text/html")

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "mock_mode": settings.mock_mode,
            "connections": app.state.manager.count,
            "auth_required": app.state.settings.auth_required,
            "ts": _ts(),
        }

    # ---- 登录 / 账号管理（2026-11-17 新增）----

    @app.post("/api/auth/login")
    async def login(payload: dict) -> dict:
        """超级管理员与普通用户共用的登录入口；口令错误返回 200 + success=false。"""
        if not app.state.settings.auth_required:
            return {"success": True, "authEnabled": False, "token": "",
                    "username": "local", "role": "admin", "expiresAt": 0}
        session, msg = app.state.auth.login(
            str(payload.get("username") or ""), str(payload.get("password") or "")
        )
        if session is None:
            return {"success": False, "msg": msg}
        return {
            "success": True, "authEnabled": True,
            "token": session["token"], "username": session["username"],
            "role": session["role"],
            "mustChangePassword": session["mustChangePassword"],
            "expiresAt": session["expiresAt"],
        }

    @app.get("/api/auth/me")
    async def auth_me(request: Request) -> dict:
        """前端启动先问这里：authEnabled=false 时直接放行，无需弹登录框。"""
        if not app.state.settings.auth_required:
            return {"authEnabled": False, "authenticated": True,
                    "username": "local", "role": "admin", "expiresAt": 0}
        identity = app.state.auth.resolve(_token_of(request))
        if identity is None:
            return {"authEnabled": True, "authenticated": False,
                    "username": "", "role": "", "expiresAt": 0}
        return {
            "authEnabled": True, "authenticated": True,
            "username": identity["username"], "role": identity["role"],
            "mustChangePassword": identity.get("mustChangePassword", False),
            "expiresAt": identity["expiresAt"],
        }

    @app.post("/api/auth/logout")
    async def auth_logout(request: Request) -> dict:
        app.state.auth.logout(_token_of(request))
        return {"success": True}

    @app.post("/api/auth/password")
    async def change_own_password(payload: dict, request: Request) -> dict:
        identity = getattr(request.state, "user", None) or {}
        try:
            validate_password(str(payload.get("newPassword") or ""))
        except ValueError as exc:
            return {"success": False, "msg": str(exc)}
        ok = app.state.users.change_password(
            str(identity.get("username") or ""),
            str(payload.get("oldPassword") or ""),
            str(payload.get("newPassword") or ""),
        )
        if not ok:
            return {"success": False, "msg": "旧密码不正确"}
        app.state.auth.logout(_token_of(request))  # 改密后强制重新登录
        return {"success": True, "msg": "密码已修改，请重新登录"}

    @app.get("/api/auth/users")
    async def list_users() -> dict:
        users = app.state.users.list_users()
        return {"success": True, "users": users, "total": len(users)}

    @app.post("/api/auth/users")
    async def add_user(payload: dict) -> dict:
        """仅超级管理员可添加普通用户（不开放通过接口创建第二个管理员）。"""
        try:
            user = app.state.users.add_user(
                str(payload.get("username") or ""),
                str(payload.get("password") or ""),
            )
        except ValueError as exc:
            return {"success": False, "msg": str(exc)}
        return {"success": True, "user": user, "msg": "普通用户已创建"}

    @app.post("/api/auth/users/{username}/reset")
    async def reset_user_password(username: str, payload: dict) -> dict:
        try:
            ok = app.state.users.reset_password(
                username, str(payload.get("newPassword") or "")
            )
        except ValueError as exc:
            return {"success": False, "msg": str(exc)}
        return {"success": ok, "msg": "密码已重置" if ok else "账号不存在"}

    @app.delete("/api/auth/users/{username}")
    async def delete_user(username: str) -> dict:
        try:
            ok = app.state.users.delete_user(username)
        except ValueError as exc:
            return {"success": False, "msg": str(exc)}
        return {"success": ok, "msg": "账号已删除" if ok else "账号不存在"}

    @app.get("/api/snapshot")
    async def get_snapshot() -> dict:
        agg: Aggregator = app.state.aggregator
        snap, _ = await agg.poll_once()
        return {"type": "snapshot", "ts": snap.ts, "data": snap.to_dict()}

    @app.get("/api/bot/{bot_uuid}/logs")
    async def get_bot_logs(bot_uuid: str) -> dict:
        """某机器人最近一次运行的日志。

        真实链路：newest/list 按 robotClientUuid 找 taskUuid
        -> process/detail 拿 jobUuid -> log/search 拿日志（jobUuid ≠ taskUuid）。
        """
        newest = await _client().task_newest_list(size=100)
        run = next(
            (row for row in _extract_list(newest)
             if any(c.get("robotClientUuid") == bot_uuid
                    for c in (row.get("taskClients") or []) if isinstance(c, dict))),
            None,
        )
        if run is None:
            return {"botUuid": bot_uuid, "jobUuid": "", "logs": []}

        detail = await _client().task_process_detail(str(run.get("taskUuid") or ""), bot_uuid)
        jobs = _extract_list(detail)
        job_uuid = str(jobs[0].get("jobUuid") or "") if jobs else ""
        if not job_uuid:
            return {"botUuid": bot_uuid, "jobUuid": "", "logs": []}

        try:
            data = (await _client().job_log_search(job_uuid)).get("data") or {}
        except Exception as exc:
            # 真实环境：机器人离线时影刀返回「机器人未连接，无法查询日志」。
            # 详情页不能因此 500，降级为空日志 + 原因提示。
            return {"botUuid": bot_uuid, "jobUuid": job_uuid, "logs": [],
                    "error": str(exc)}
        return {"botUuid": bot_uuid, "jobUuid": job_uuid,
                "logs": [x for x in (data.get("logs") or []) if isinstance(x, dict)]}

    @app.get("/api/run/{run_id}/detail")
    async def get_run_detail(run_id: str, botUuid: str = "") -> dict:
        """失败详情（含 remark / screenshotUrl）；process/detail 必须传匹配的机器人 uuid。"""
        bot_uuid = botUuid
        if not bot_uuid:
            newest = await _client().task_newest_list(size=100)
            for row in _extract_list(newest):
                if str(row.get("taskUuid") or "") == run_id:
                    clients = row.get("taskClients") or []
                    if clients and isinstance(clients[0], dict):
                        bot_uuid = str(clients[0].get("robotClientUuid") or "")
                    break
        try:
            resp = await _client().task_process_detail(run_id, bot_uuid)
        except Exception as exc:
            # 任务已过期 / 机器人离线时影刀会拒查详情，截图入口降级为空结果。
            return {"runId": run_id, "botUuid": bot_uuid, "jobs": [], "error": str(exc)}
        return {"runId": run_id, "botUuid": bot_uuid, "jobs": _extract_list(resp)}

    @app.post("/api/callback")
    async def yingdao_callback(payload: dict, request: Request):
        """影刀应用终态回调入口；回调体字段结构待密钥到位后核实。

        外部系统无法携带本系统会话 token，改用 CALLBACK_TOKEN 请求头校验。
        token 未配置时放行（本地/内网），生产须配置。
        """
        expected = app.state.settings.callback_token
        if expected and request.headers.get("X-Callback-Token", "") != expected:
            return JSONResponse(status_code=401,
                                content={"received": False, "msg": "回调令牌无效"})
        message = {"type": "callback", "ts": _ts(), "data": payload}
        await app.state.manager.broadcast(message)
        return {"received": True, "connections": app.state.manager.count}

    async def _resolve_bot_uuid(task_uuid: str, bot_uuid: str) -> str:
        """process/detail 必须传与该任务匹配的机器人 uuid；未传时从最近运行反查。"""
        if bot_uuid:
            return bot_uuid
        newest = await _client().task_newest_list(size=100)
        for row in _extract_list(newest):
            if str(row.get("taskUuid") or "") == task_uuid:
                clients = row.get("taskClients") or []
                if clients and isinstance(clients[0], dict):
                    return str(clients[0].get("robotClientUuid") or "")
        return ""

    @app.post("/api/control/stop")
    async def stop_job(payload: dict) -> dict:
        job_uuid = str(payload.get("jobUuid") or "")
        if not job_uuid:
            return {"success": False, "msg": "缺少 jobUuid"}
        try:
            resp = await _client().job_stop(job_uuid)
        except Exception as exc:
            return {"success": False, "msg": f"影刀拒绝停止：{exc}"}
        await app.state.manager.broadcast(
            {"type": "control_result", "ts": _ts(),
             "data": {"action": "stop", "jobUuid": job_uuid, "result": resp.get("data") or {}}}
        )
        return {"success": True, "data": resp.get("data") or {}}

    @app.post("/api/control/stop-by-task")
    async def stop_by_task(payload: dict) -> dict:
        """按任务停止：taskUuid + botUuid -> process/detail 拿 jobUuid -> job/stop。

        前端只持有 taskUuid，不持有 jobUuid；真实环境避免误停，先确认任务仍在运行。
        """
        task_uuid = str(payload.get("taskUuid") or "")
        if not task_uuid:
            return {"success": False, "msg": "缺少 taskUuid"}
        bot_uuid = await _resolve_bot_uuid(task_uuid, str(payload.get("botUuid") or ""))
        try:
            detail = await _client().task_process_detail(task_uuid, bot_uuid)
        except Exception as exc:
            return {"success": False, "msg": f"查询任务详情失败：{exc}"}

        jobs = _extract_list(detail)
        running = [j for j in jobs
                   if normalize_run_state(str(j.get("status") or "")) == "running"]
        if not running:
            return {"success": False, "msg": "该任务已结束或无运行中的应用，未执行停止"}
        job_uuid = str(running[0].get("jobUuid") or "")
        if not job_uuid:
            return {"success": False, "msg": "未取到 jobUuid，未执行停止"}

        try:
            resp = await _client().job_stop(job_uuid)
        except Exception as exc:
            return {"success": False, "msg": f"影刀拒绝停止：{exc}"}
        await app.state.manager.broadcast(
            {"type": "control_result", "ts": _ts(),
             "data": {"action": "stop", "taskUuid": task_uuid,
                      "jobUuid": job_uuid, "result": resp.get("data") or {}}}
        )
        return {"success": True, "jobUuid": job_uuid, "data": resp.get("data") or {}}

    # ---- 应用搜索 / 远程运行 / 异常重试 / 错误日志（2026-11-17 新增）----

    @app.get("/api/apps/search")
    async def search_apps(keyword: str = "", page: int = 1, size: int = 20) -> dict:
        """搜索已发布流程。应用目录带 60 秒缓存，本地过滤，避免撞影刀限频。"""
        try:
            return await app.state.catalog.search(keyword, page, min(max(1, size), 50))
        except Exception as exc:
            return {"keyword": keyword, "total": 0, "apps": [], "error": str(exc)}

    @app.post("/api/apps/refresh")
    async def refresh_apps() -> dict:
        try:
            items = await app.state.catalog.load(force=True)
            return {"success": True, "total": len(items),
                    "published": sum(1 for x in items if x["published"])}
        except Exception as exc:
            return {"success": False, "msg": str(exc)}

    @app.post("/api/control/start")
    async def start_app(payload: dict) -> dict:
        """远程运行流程。启动前校验 appId 必须是应用目录里真实存在且已发布的应用。"""
        if not app.state.settings.allow_control:
            return {"success": False, "msg": "服务端已关闭远程控制（ALLOW_REMOTE_CONTROL=0）"}
        app_id = str(payload.get("appId") or "")
        account = str(payload.get("accountName") or "")
        if not app_id:
            return {"success": False, "msg": "缺少 appId"}
        try:
            runnable = await app.state.catalog.is_runnable(app_id)
        except Exception as exc:
            return {"success": False, "msg": f"应用目录查询失败：{exc}"}
        if not runnable:
            return {"success": False, "msg": "应用不存在或未发布，已阻止启动"}
        params = payload.get("params")
        params = params if isinstance(params, list) else []
        try:
            resp = await _client().job_start(app_id, account, params)
        except Exception as exc:
            return {"success": False, "msg": f"影刀拒绝启动：{exc}"}
        data = resp.get("data") or {}
        await _push({"action": "start", "appId": app_id, "accountName": account,
                     "jobUuid": data.get("jobUuid"), "result": data})
        return {"success": True, "appId": app_id,
                "jobUuid": str(data.get("jobUuid") or ""), "data": data}

    @app.post("/api/control/retry")
    async def retry_task(payload: dict) -> dict:
        """重试异常流程：taskUuid -> 确认状态可重试 -> process/detail 取 jobUuid -> job/retry。"""
        if not app.state.settings.allow_control:
            return {"success": False, "msg": "服务端已关闭远程控制（ALLOW_REMOTE_CONTROL=0）"}
        task_uuid = str(payload.get("taskUuid") or "")
        if not task_uuid:
            return {"success": False, "msg": "缺少 taskUuid"}
        try:
            newest = await _client().task_newest_list(size=100)
        except Exception as exc:
            return {"success": False, "msg": f"查询运行记录失败：{exc}"}
        run = next((r for r in _extract_list(newest)
                    if str(r.get("taskUuid") or "") == task_uuid), None)
        if run is None:
            return {"success": False, "msg": "未找到该运行记录（可能已被滚动淘汰），未执行重试"}
        status = str(run.get("status") or "").lower()
        if status not in _RETRYABLE:
            return {"success": False, "msg": f"当前状态 {status or '未知'} 不支持重试"}
        bot_uuid = await _resolve_bot_uuid(task_uuid, str(payload.get("botUuid") or ""))
        try:
            detail = await _client().task_process_detail(task_uuid, bot_uuid)
            jobs = _extract_list(detail)
            job = next((j for j in jobs
                        if str(j.get("status") or "").lower() in _RETRYABLE), None)
            job = job or (jobs[0] if jobs else {})
            job_uuid = str(job.get("jobUuid") or "")
            if not job_uuid:
                return {"success": False, "msg": "未取到 jobUuid，未执行重试"}
            resp = await _client().job_retry(job_uuid)
        except Exception as exc:
            return {"success": False, "msg": f"重试失败：{exc}"}
        await _push({"action": "retry", "taskUuid": task_uuid,
                     "jobUuid": job_uuid, "result": resp.get("data") or {}})
        return {"success": True, "taskUuid": task_uuid, "jobUuid": job_uuid,
                "data": resp.get("data") or {}}

    @app.get("/api/run/{run_id}/logs")
    async def get_run_logs(run_id: str, botUuid: str = "") -> dict:
        """按运行记录查错误日志：process/detail 拿 jobUuid -> log/search。"""
        bot_uuid = botUuid or await _resolve_bot_uuid(run_id, "")
        try:
            detail = await _client().task_process_detail(run_id, bot_uuid)
            jobs = _extract_list(detail)
            job = next((j for j in jobs
                        if str(j.get("status") or "").lower() in _RETRYABLE), None)
            job = job or (jobs[0] if jobs else {})
            job_uuid = str(job.get("jobUuid") or "")
            if not job_uuid:
                return {"runId": run_id, "jobUuid": "", "logs": []}
            data = (await _client().job_log_search(job_uuid)).get("data") or {}
            return {"runId": run_id, "jobUuid": job_uuid,
                    "logs": [x for x in (data.get("logs") or []) if isinstance(x, dict)]}
        except Exception as exc:
            # 机器人离线 / 任务过期时影刀拒查，降级为空日志 + 原因
            return {"runId": run_id, "jobUuid": "", "logs": [], "error": str(exc)}

    # ---- 设置（关于 → 设置）：密钥只存后端 .env，前端不落盘 ----

    @app.get("/api/settings")
    async def get_settings() -> dict:
        s = app.state.settings
        snap = app.state.aggregator.snapshot
        return {
            "baseUrl": s.base_url,
            "mockMode": s.mock_mode,
            "hasCredentials": bool(s.access_key_id and s.access_key_secret),
            "accessKeyIdMasked": _mask(s.access_key_id),
            "adminTokenRequired": bool(s.admin_token),
            "allowRemoteControl": s.allow_control,
            "pollInterval": s.poll_interval,
            "authEnabled": s.auth_required,
            "onlyToday": True,
            "date": snap.day if snap else datetime.now().date().isoformat(),
        }

    @app.post("/api/settings/test")
    async def test_credentials() -> dict:
        """用当前凭证调一次只读接口，验证密钥是否可用。"""
        try:
            resp = await _client().client_list(size=1)
            return {"success": True, "mockMode": app.state.settings.mock_mode,
                    "botCount": len(_extract_list(resp))}
        except Exception as exc:
            return {"success": False, "msg": str(exc)}

    @app.post("/api/settings/credentials")
    async def save_credentials(payload: dict, request: Request):
        """保存影刀 accessKeyId / accessKeySecret 到后端 .env 并热更新客户端。

        Secret 绝不回显、不写日志、不进前端存储；管理口令（ADMIN_TOKEN）可选。
        """
        s = app.state.settings
        if s.admin_token and request.headers.get("X-Admin-Token") != s.admin_token:
            return JSONResponse(status_code=403,
                                content={"success": False, "msg": "管理口令错误"})
        key = str(payload.get("accessKeyId") or "").strip()
        secret = str(payload.get("accessKeySecret") or "").strip()
        if not key or not secret:
            return {"success": False, "msg": "AccessKey ID 与 Secret 都不能为空"}
        if len(key) > 200 or len(secret) > 200 or "\n" in key or "\n" in secret:
            return {"success": False, "msg": "凭证格式异常"}

        env_path = _ENV_PATH
        lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.is_file() else []
        kept = [ln for ln in lines
                if not ln.strip().startswith("YINGDAO_ACCESS_KEY_ID=")
                and not ln.strip().startswith("YINGDAO_ACCESS_KEY_SECRET=")]
        kept += [f"YINGDAO_ACCESS_KEY_ID={key}", f"YINGDAO_ACCESS_KEY_SECRET={secret}"]
        env_path.write_text("\n".join(kept) + "\n", encoding="utf-8")

        os.environ["YINGDAO_ACCESS_KEY_ID"] = key
        os.environ["YINGDAO_ACCESS_KEY_SECRET"] = secret
        forced_mock = os.getenv("YINGDAO_MOCK", "").strip().lower() in {"1", "true", "yes", "on"}
        new_settings = replace(s, access_key_id=key, access_key_secret=secret,
                               mock_mode=True if forced_mock else False)
        new_client = YingdaoClient(new_settings)
        old_client = app.state.client
        app.state.settings = new_settings
        app.state.client = new_client
        app.state.aggregator.client = new_client
        app.state.catalog.client = new_client
        app.state.catalog.invalidate()
        try:
            await old_client.aclose()
        except Exception:
            pass
        return {"success": True, "accessKeyIdMasked": _mask(key),
                "msg": "已保存并立即生效，无需重启服务"}

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        # 浏览器 WebSocket 无法自定义 Header，token 走 ?token=；小程序同理
        if app.state.settings.auth_required:
            token = ws.query_params.get("token") or ""
            if not token:
                raw = ws.headers.get("authorization", "")
                if raw.lower().startswith("bearer "):
                    token = raw[7:].strip()
            if app.state.auth.resolve(token) is None:
                await ws.close(code=4401)
                return
        manager: ConnectionManager = app.state.manager
        await manager.connect(ws)
        try:
            # 首帧发全量快照，避免客户端等下一次轮询才有数据
            agg: Aggregator = app.state.aggregator
            snap = agg.snapshot
            if snap is None:
                snap, _ = await agg.poll_once()
            await ws.send_json({"type": "snapshot", "ts": snap.ts, "data": snap.to_dict()})
            while True:
                raw = await ws.receive_text()
                if raw.strip() == "ping":
                    await ws.send_text("pong")
        except WebSocketDisconnect:
            pass
        finally:
            manager.disconnect(ws)

    return app


app = create_app()
