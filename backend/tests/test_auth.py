"""鉴权缓存与续期测试。"""
import asyncio

import pytest

from app.auth import TokenManager


def _manager(mock_mode=False, refresh_ahead=300):
    calls = []

    async def fetch():
        calls.append(1)
        return {"accessToken": "TOKEN", "expiresIn": 7199}

    return TokenManager(fetch, refresh_ahead=refresh_ahead, mock_mode=mock_mode), calls


async def test_mock_mode_never_calls_remote():
    mgr, calls = _manager(mock_mode=True)
    assert await mgr.get_token() == "MOCK_ACCESS_TOKEN"
    assert calls == []


async def test_token_is_cached():
    mgr, calls = _manager()
    tokens = [await mgr.get_token() for _ in range(3)]
    assert tokens == ["TOKEN"] * 3
    assert len(calls) == 1


async def test_concurrent_calls_only_fetch_once():
    mgr, calls = _manager()
    tokens = await asyncio.gather(*[mgr.get_token() for _ in range(10)])
    assert set(tokens) == {"TOKEN"}
    assert len(calls) == 1


async def test_refreshes_when_near_expiry():
    # expiresIn=10 < refresh_ahead=300 -> 每次调用都视为即将过期
    calls = []

    async def fetch():
        calls.append(1)
        return {"accessToken": f"TOKEN-{len(calls)}", "expiresIn": 10}

    mgr = TokenManager(fetch, refresh_ahead=300)
    assert await mgr.get_token() == "TOKEN-1"
    assert await mgr.get_token() == "TOKEN-2"
    assert len(calls) == 2


async def test_invalidate_forces_refetch():
    mgr, calls = _manager()
    await mgr.get_token()
    mgr.invalidate()
    await mgr.get_token()
    assert len(calls) == 2


async def test_rejects_invalid_token_payload():
    async def fetch():
        return {"expiresIn": 100}

    with pytest.raises(ValueError, match="accessToken"):
        await TokenManager(fetch, refresh_ahead=1).get_token()
