"""端到端冒烟：对真实运行的 uvicorn 服务验证 REST + WebSocket 全链路。

前置：在 backend/ 目录启动服务（建议关闭后台轮询，避免 delta 帧干扰断言）
    AUTH_REQUIRED=0 ENABLE_POLLER=0 python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
然后：python smoke.py
（若服务开启了登录鉴权，本脚本会自动用超级管理员登录后再验证）
"""
from __future__ import annotations

import asyncio
import json
import os

import httpx
import websockets

BASE = os.getenv("SMOKE_BASE", "http://127.0.0.1:8765")
ADMIN_USER = os.getenv("SUPER_ADMIN_USERNAME", "admin")
ADMIN_PWD = os.getenv("SUPER_ADMIN_PASSWORD", "admin123")


async def wait_ready(http: httpx.AsyncClient) -> None:
    for _ in range(20):
        try:
            resp = await http.get(BASE + "/health", timeout=1.0)
            if resp.status_code == 200:
                return
        except Exception:
            pass
        await asyncio.sleep(0.25)
    raise RuntimeError("服务未就绪，请先启动 uvicorn")


async def main() -> None:
    async with httpx.AsyncClient(timeout=5.0) as http:
        await wait_ready(http)

        health = (await http.get(BASE + "/health")).json()
        assert health["status"] == "ok", health
        assert health["mock_mode"] is True, "冒烟需在 MOCK 模式运行"

        # 登录鉴权开启时先取会话 token；未开启时 login 直接返回空 token
        login = (await http.post(BASE + "/api/auth/login",
                                 json={"username": ADMIN_USER, "password": ADMIN_PWD})).json()
        assert login["success"] is True, login
        token = login.get("token") or ""
        headers = {"Authorization": "Bearer " + token} if token else {}
        ws_url = (BASE.replace("http://", "ws://").replace("https://", "wss://")
                  + "/ws" + ("?token=" + token if token else ""))

        snap = (await http.get(BASE + "/api/snapshot", headers=headers)).json()
        assert snap["type"] == "snapshot"
        assert snap["data"]["overview"]["bot_total"] == 4
        assert len(snap["data"]["runs"]) == 4

        async with websockets.connect(ws_url) as ws:
            first = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert first["type"] == "snapshot", first

            await http.post(BASE + "/api/callback", headers=headers,
                            json={"jobUuid": "smoke-1", "status": "fail"})
            pushed = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert pushed["type"] == "callback", pushed
            assert pushed["data"]["jobUuid"] == "smoke-1"

            await ws.send("ping")
            assert await asyncio.wait_for(ws.recv(), timeout=5) == "pong"

    print("端到端冒烟通过：/health → /api/snapshot → WS 首帧 → 回调推送 → 心跳")


if __name__ == "__main__":
    asyncio.run(main())
