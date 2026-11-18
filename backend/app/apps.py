"""已发布应用目录：分页拉全量 → 内存缓存 → 本地搜索 / 启动前校验。

为什么要缓存：影刀应用列表接口有频率限制，147+ 个应用逐次搜索会撞限频；
一次拉全量后本地过滤，搜索响应更快，也能在启动前校验 appId 真实存在。
"""
from __future__ import annotations

import asyncio
import time

from .aggregator import _extract_list
from .yingdao_client import YingdaoClient

_MAX_PAGES = 20  # 上限 2000 个应用，避免异常分页导致死循环


class AppCatalog:
    def __init__(self, client: YingdaoClient, ttl: float = 60.0,
                 page_size: int = 100) -> None:
        self.client = client
        self.ttl = ttl
        self.page_size = page_size
        self._items: list[dict] = []
        self._loaded_at = 0.0
        self._lock = asyncio.Lock()

    @staticmethod
    def _normalize(raw: dict) -> dict:
        # 实测：appStatus 恒为 'r'、version 恒有值，但 40% 记录没有 publishTime。
        # 因此「已发布」以 publishTime 非空 + appType == 'app' 判定。
        publish_time = str(raw.get("publishTime") or "")
        app_type = str(raw.get("appType") or "app")
        return {
            "appId": str(raw.get("appId") or ""),
            "appName": str(raw.get("appName") or "未命名应用"),
            "version": str(raw.get("version") or ""),
            "ownerName": str(raw.get("ownerName") or ""),
            "ownerAccount": str(raw.get("ownerAccount") or ""),
            "appType": app_type,
            "appTypeName": str(raw.get("appTypeName") or "应用"),
            "publishTime": publish_time,
            "updateTime": str(raw.get("updateTime") or ""),
            "description": str(raw.get("description") or ""),
            "supportParam": bool(raw.get("supportParam")),
            "published": bool(publish_time) and app_type == "app",
        }

    async def load(self, force: bool = False) -> list[dict]:
        async with self._lock:
            fresh = self._items and (time.monotonic() - self._loaded_at) < self.ttl
            if fresh and not force:
                return self._items
            rows: list[dict] = []
            page = 1
            while page <= _MAX_PAGES:
                resp = await self.client.app_query_list(page=page, size=self.page_size)
                batch = _extract_list(resp)
                rows.extend(batch)
                meta = resp.get("page")
                pages = 1
                if isinstance(meta, dict):
                    try:
                        pages = int(meta.get("pages") or 1)
                    except (TypeError, ValueError):
                        pages = 1
                if not batch or page >= pages:
                    break
                page += 1
            self._items = [self._normalize(x) for x in rows if x.get("appId")]
            self._loaded_at = time.monotonic()
            return self._items

    async def search(self, keyword: str = "", page: int = 1, size: int = 20,
                     only_published: bool = True) -> dict:
        items = await self.load()
        if only_published:
            items = [x for x in items if x["published"]]
        kw = (keyword or "").strip().lower()
        if kw:
            items = [x for x in items
                     if kw in x["appName"].lower()
                     or kw in x["ownerName"].lower()
                     or kw in x["description"].lower()]
        total = len(items)
        start = max(0, (max(1, page) - 1) * max(1, size))
        return {
            "keyword": keyword or "",
            "total": total,
            "page": max(1, page),
            "size": max(1, size),
            "apps": items[start:start + max(1, size)],
            "cachedAt": self._loaded_at,
        }

    async def is_runnable(self, app_id: str) -> bool:
        """启动前校验：只允许运行目录里真实存在且已发布的应用。"""
        if not app_id:
            return False
        items = await self.load()
        return any(x["appId"] == app_id and x["published"] for x in items)

    def invalidate(self) -> None:
        self._items = []
        self._loaded_at = 0.0
