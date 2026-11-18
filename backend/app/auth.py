"""accessToken 缓存与自动续期。

影刀文档约定：accessToken 有效期最长 2 小时，未过期时返回旧 token，过期时返回新 token。
这里按 expiresIn 缓存，提前 refresh_ahead 秒刷新，避免与服务端有效期判断不一致。
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable


class TokenManager:
    """fetch_token 需返回 {'accessToken': str, 'expiresIn': int}。"""

    def __init__(
        self,
        fetch_token: Callable[[], Awaitable[dict]],
        refresh_ahead: int = 300,
        mock_mode: bool = False,
    ) -> None:
        self._fetch = fetch_token
        self._refresh_ahead = refresh_ahead
        self._mock_mode = mock_mode
        self._token: str = ""
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()
        self.fetch_count = 0

    def _valid(self) -> bool:
        return bool(self._token) and time.monotonic() < self._expires_at - self._refresh_ahead

    async def get_token(self) -> str:
        if self._mock_mode:
            return "MOCK_ACCESS_TOKEN"

        if self._valid():
            return self._token

        async with self._lock:
            # 双重检查：等待锁期间可能已有其他协程完成刷新
            if self._valid():
                return self._token
            data = await self._fetch()
            token = str(data.get("accessToken") or "")
            if not token:
                raise ValueError("影刀鉴权响应缺少 accessToken")
            expires_in = int(data.get("expiresIn") or 0)
            if expires_in <= 0:
                raise ValueError("影刀鉴权响应 expiresIn 非法")
            self._token = token
            self._expires_at = time.monotonic() + expires_in
            self.fetch_count += 1
            return self._token

    def invalidate(self) -> None:
        """收到鉴权失败时强制下次重新获取。"""
        self._token = ""
        self._expires_at = 0.0
