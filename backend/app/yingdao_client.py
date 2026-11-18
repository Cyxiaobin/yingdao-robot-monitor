"""影刀开放 API 客户端封装。

所有方法返回与影刀一致的原始响应 dict（含 code / success / data），
由 aggregator 负责取字段。MOCK 模式下不发任何网络请求。
"""
from __future__ import annotations

import uuid

import httpx

from .auth import TokenManager
from .config import Settings
from .mock_data import MockStore


class YingdaoAPIError(Exception):
    """影刀返回业务失败或网络异常。"""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class YingdaoClient:
    def __init__(
        self,
        settings: Settings,
        mock_store: MockStore | None = None,
        http_client: httpx.AsyncClient | None = None,
        refresh_ahead: int = 300,
    ) -> None:
        self.settings = settings
        self.mock = mock_store or MockStore()
        self._http = http_client
        self._owns_http = http_client is None
        self.token_manager = TokenManager(
            self._fetch_token_data,
            refresh_ahead=refresh_ahead,
            mock_mode=settings.mock_mode,
        )

    async def _ensure_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=10.0)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and self._owns_http:
            await self._http.aclose()
            self._http = None

    @staticmethod
    def _check(payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise YingdaoAPIError("影刀响应不是 JSON 对象")
        if payload.get("code") != 200 or payload.get("success") is not True:
            raise YingdaoAPIError(
                str(payload.get("msg") or "影刀接口返回失败"),
                code=payload.get("code"),
            )
        return payload

    async def _fetch_token_data(self) -> dict:
        http = await self._ensure_http()
        resp = await http.get(
            f"{self.settings.base_url}/oapi/token/v2/token/create",
            params={
                "accessKeyId": self.settings.access_key_id,
                "accessKeySecret": self.settings.access_key_secret,
            },
        )
        payload = self._check(resp.json())
        return payload.get("data") or {}

    async def _post(self, path: str, body: dict) -> dict:
        token = await self.token_manager.get_token()
        http = await self._ensure_http()
        resp = await http.post(
            f"{self.settings.base_url}{path}",
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        return self._check(resp.json())

    # ---- 已封装的开放 API ----

    async def client_list(self, page: int = 1, size: int = 100) -> dict:
        if self.settings.mock_mode:
            return self.mock.client_list()
        return await self._post(
            "/oapi/dispatch/v2/client/list", {"page": page, "size": size}
        )

    async def task_newest_list(self, size: int = 50) -> dict:
        if self.settings.mock_mode:
            return self.mock.task_newest_list()
        # 请求体字段以影刀官方文档核实；当前传 size + 空过滤条件
        return await self._post("/oapi/dispatch/v2/task/newest/list", {"size": size})

    async def job_query(self, job_uuid: str) -> dict:
        if self.settings.mock_mode:
            return self.mock.job_query(job_uuid)
        return await self._post("/oapi/dispatch/v2/job/query", {"jobUuid": job_uuid})

    async def task_process_detail(self, task_uuid: str, robot_client_uuid: str) -> dict:
        if self.settings.mock_mode:
            return self.mock.task_process_detail(task_uuid, robot_client_uuid)
        return await self._post(
            "/oapi/dispatch/v2/task/process/detail",
            {"taskUuid": task_uuid, "robotClientUuid": robot_client_uuid},
        )

    async def job_log_search(self, job_uuid: str, page: int = 1, size: int = 20) -> dict:
        """一步式查日志。影刀另有 notify(POST)+query(GET requestId) 两步轮询方案。"""
        if self.settings.mock_mode:
            return self.mock.job_log_search(job_uuid, page, size)
        return await self._post(
            "/oapi/dispatch/v2/job/log/search",
            {"jobUuid": job_uuid, "page": page, "size": size},
        )

    async def job_stop(self, job_uuid: str) -> dict:
        if self.settings.mock_mode:
            return self.mock.job_stop(job_uuid)
        return await self._post("/oapi/dispatch/v2/job/stop", {"jobUuid": job_uuid})

    # ---- 应用目录与远程控制（2026-11-17 实测接口）----

    async def app_query_list(self, page: int = 1, size: int = 100,
                             app_name: str = "") -> dict:
        """查询应用列表。真实路径是 /oapi/app/open/query/list（不是 dispatch/v2）。"""
        if self.settings.mock_mode:
            return self.mock.app_query_list(page, size, app_name)
        body: dict = {"page": page, "size": size}
        if app_name:
            body["appName"] = app_name
        return await self._post("/oapi/app/open/query/list", body)

    async def job_start(self, robot_uuid: str, account_name: str = "",
                        params: list | None = None,
                        idempotent_uuid: str = "") -> dict:
        """启动应用。robotUuid = 应用列表的 appId；accountName = client/list 的 robotClientName。"""
        if self.settings.mock_mode:
            return self.mock.job_start(robot_uuid, account_name)
        body: dict = {
            "robotUuid": robot_uuid,
            "idempotentUuid": (idempotent_uuid or str(uuid.uuid4()))[:36],
        }
        if account_name:
            body["accountName"] = account_name
        if params:
            body["params"] = params
        return await self._post("/oapi/dispatch/v2/job/start", body)

    async def job_retry(self, job_uuid: str) -> dict:
        """重试异常/已停止的应用运行；仅对这两种状态有效。"""
        if self.settings.mock_mode:
            return self.mock.job_retry(job_uuid)
        return await self._post("/oapi/dispatch/v2/job/retry", {"jobUuid": job_uuid})
