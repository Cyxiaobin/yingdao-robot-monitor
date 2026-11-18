"""生产安全加固回归测试（2026-11-18）。

覆盖：回调令牌校验 / 强制改密 / 写操作仅管理员 / STRICT_REAL 拒绝 MOCK 启动。
全部 MOCK + 临时账号库，无需网络与真实密钥。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.users import UserStore
from app.yingdao_client import YingdaoClient


@pytest.fixture
def hardened(tmp_path, store):
    """开启鉴权 + 回调令牌；返回 (TestClient, 管理员token, 普通用户token)。"""
    s = Settings(
        mock_mode=True, enable_poller=False, poll_interval=1.0,
        auth_required=True, callback_token="cb-secret-xyz",
        auth_users_file=str(tmp_path / "users.json"),
        super_admin_username="root", super_admin_password="root123",
    )
    # 首次登录会标记 mustChangePassword，先改密清掉标志，模拟已启用的管理员
    with TestClient(create_app(settings=s, client=YingdaoClient(s, mock_store=store),
                               store=store)) as tc:
        admin = tc.post("/api/auth/login",
                        json={"username": "root", "password": "root123"}).json()["token"]
        tc.post("/api/auth/password",
                headers={"Authorization": "Bearer " + admin},
                json={"oldPassword": "root123", "newPassword": "strongpass1"})
        admin = tc.post("/api/auth/login",
                        json={"username": "root", "password": "strongpass1"}).json()["token"]
        tc.post("/api/auth/users", headers={"Authorization": "Bearer " + admin},
                json={"username": "normal", "password": "normal123"})
        normal = tc.post("/api/auth/login",
                         json={"username": "normal", "password": "normal123"}).json()["token"]
        yield tc, s, admin, normal


def _h(token):
    return {"Authorization": "Bearer " + token}


# ---------- 回调令牌 ----------

def test_callback_requires_valid_token(hardened):
    tc, _, _, _ = hardened
    bad = tc.post("/api/callback", json={"jobUuid": "j1"},
                  headers={"X-Callback-Token": "wrong"})
    assert bad.status_code == 401
    ok = tc.post("/api/callback", json={"jobUuid": "j1"},
                 headers={"X-Callback-Token": "cb-secret-xyz"})
    assert ok.status_code == 200 and ok.json()["received"] is True


def test_callback_open_when_no_token_configured(tmp_path, store):
    s = Settings(mock_mode=True, enable_poller=False, auth_required=False,
                 callback_token="")
    with TestClient(create_app(settings=s, client=YingdaoClient(s, mock_store=store),
                               store=store)) as tc:
        assert tc.post("/api/callback", json={}).status_code == 200


# ---------- 强制改密 ----------

def test_default_password_user_forced_to_change(tmp_path, store):
    s = Settings(mock_mode=True, enable_poller=False, auth_required=True,
                 enforce_password_change=True,
                 auth_users_file=str(tmp_path / "users.json"),
                 super_admin_username="root", super_admin_password="admin123")
    with TestClient(create_app(settings=s, client=YingdaoClient(s, mock_store=store),
                               store=store)) as tc:
        token = tc.post("/api/auth/login",
                        json={"username": "root", "password": "admin123"}).json()["token"]
        assert token
        # 默认口令用户：只读与改密可用，其他接口一律 403
        assert tc.get("/api/auth/me", headers=_h(token)).status_code == 200
        assert tc.get("/api/snapshot", headers=_h(token)).status_code == 403
        blocked = tc.get("/api/settings", headers=_h(token))
        assert blocked.status_code == 403
        assert blocked.json()["code"] == "MUST_CHANGE_PASSWORD"
        assert tc.post("/api/control/start", headers=_h(token),
                       json={"appId": "x"}).status_code == 403
        # 改密后标志清除，恢复正常访问
        changed = tc.post("/api/auth/password", headers=_h(token),
                          json={"oldPassword": "admin123", "newPassword": "brandnew1"})
        assert changed.json()["success"] is True
        fresh = tc.post("/api/auth/login",
                        json={"username": "root", "password": "brandnew1"}).json()["token"]
        assert tc.get("/api/settings", headers=_h(fresh)).status_code == 200


def test_enforce_password_change_can_be_disabled(tmp_path, store):
    s = Settings(mock_mode=True, enable_poller=False, auth_required=True,
                 enforce_password_change=False,
                 auth_users_file=str(tmp_path / "users.json"),
                 super_admin_username="root", super_admin_password="admin123")
    with TestClient(create_app(settings=s, client=YingdaoClient(s, mock_store=store),
                               store=store)) as tc:
        token = tc.post("/api/auth/login",
                        json={"username": "root", "password": "admin123"}).json()["token"]
        assert tc.get("/api/settings", headers=_h(token)).status_code == 200


# ---------- 写操作仅管理员 ----------

def test_write_operations_are_admin_only(hardened):
    tc, _, admin, normal = hardened
    # 普通用户只读可用
    assert tc.get("/api/snapshot", headers=_h(normal)).status_code == 200
    assert tc.get("/api/apps/search", headers=_h(normal)).status_code == 200
    assert tc.get("/api/settings", headers=_h(normal)).status_code == 200
    # 写操作全部 403
    assert tc.post("/api/control/start", headers=_h(normal),
                   json={"appId": "app-001"}).status_code == 403
    assert tc.post("/api/control/retry", headers=_h(normal),
                   json={"taskUuid": "run-001"}).status_code == 403
    assert tc.post("/api/apps/refresh", headers=_h(normal)).status_code == 403
    assert tc.post("/api/settings/test", headers=_h(normal)).status_code == 403
    denied = tc.post("/api/settings/credentials", headers=_h(normal), json={
        "accessKeyId": "k", "accessKeySecret": "s"})
    assert denied.status_code == 403
    # 管理员可执行（返回业务结果而非 403 即可）
    assert tc.post("/api/apps/refresh", headers=_h(admin)).status_code == 200


# ---------- STRICT_REAL ----------

def test_strict_real_refuses_mock_startup(store):
    s = Settings(mock_mode=True, enable_poller=False, strict_real=True)
    with pytest.raises(RuntimeError, match="STRICT_REAL"):
        create_app(settings=s, client=YingdaoClient(s, mock_store=store), store=store)


def test_strict_real_allows_real_mode(tmp_path, store):
    s = Settings(mock_mode=False, enable_poller=False, strict_real=True,
                 auth_users_file=str(tmp_path / "users.json"))
    app = create_app(settings=s, client=YingdaoClient(s, mock_store=store), store=store)
    assert app.state.settings.strict_real is True


# ---------- 账号库原子写 ----------

def test_user_store_atomic_write_leaves_no_temp(tmp_path):
    p = tmp_path / "users.json"
    store = UserStore(p, "root", "root123")
    store.add_user("lisi", "pass123")
    assert p.exists()
    assert not (tmp_path / "users.json.tmp").exists()
    # 重载后数据完整，密码可验证
    reloaded = UserStore(p)
    assert reloaded.authenticate("root", "root123") is not None
    assert reloaded.authenticate("lisi", "pass123") is not None
