"""登录鉴权 / 账号管理 / 仅当天数据 的回归测试（2026-11-17）。"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.aggregator import build_snapshot, filter_today
from app.config import Settings
from app.main import create_app
from app.users import (
    AuthService,
    SessionStore,
    UserStore,
    hash_password,
    validate_password,
    validate_username,
    verify_password,
)
from app.yingdao_client import YingdaoClient


@pytest.fixture
def auth_api(tmp_path, store):
    s = replace(
        Settings(mock_mode=True, enable_poller=False, poll_interval=1.0),
        auth_required=True,
        enforce_password_change=False,  # 本组测鉴权/账号管理本身；强制改密见 test_production_hardening.py
        auth_users_file=str(tmp_path / "users.json"),
        super_admin_username="root",
        super_admin_password="root123",
    )
    with TestClient(create_app(settings=s,
                               client=YingdaoClient(s, mock_store=store),
                               store=store)) as tc:
        yield tc


def _login(api, username, password):
    return api.post("/api/auth/login",
                    json={"username": username, "password": password}).json()


def _headers(token):
    return {"Authorization": "Bearer " + token}


# ---------- 密码与账号库 ----------

def test_password_hash_is_salted_and_verifiable():
    a, b = hash_password("abc123"), hash_password("abc123")
    assert a != b                       # 每次 salt 不同
    assert "abc123" not in a
    assert verify_password("abc123", a)
    assert not verify_password("abc12", a)
    assert not verify_password("abc123", "broken$format")


def test_username_and_password_validation():
    assert validate_username("  Li.Zhongbin@demo ".strip()) == "li.zhongbin@demo"
    for bad in ("ab", "有中文", "a b", "x" * 40):
        with pytest.raises(ValueError):
            validate_username(bad)
    for bad in ("", "12345"):
        with pytest.raises(ValueError):
            validate_password(bad)
    assert validate_password("123456") == "123456"


def test_user_store_crud_and_builtin_protection(tmp_path):
    store = UserStore(tmp_path / "users.json", "root", "root123")
    assert store.list_users()[0]["role"] == "admin"
    assert store.list_users()[0]["builtin"] is True
    assert store.authenticate("root", "root123") is not None
    assert store.authenticate("root", "wrong") is None

    created = store.add_user("zhangsan", "pass123")
    assert created["role"] == "user"     # 只能创建普通用户
    with pytest.raises(ValueError):
        store.add_user("zhangsan", "pass123")   # 重名
    assert store.authenticate("zhangsan", "pass123") is not None

    assert store.change_password("zhangsan", "wrong", "newpass") is False
    assert store.change_password("zhangsan", "pass123", "newpass") is True
    assert store.authenticate("zhangsan", "newpass") is not None
    assert store.reset_password("zhangsan", "reset123") is True
    assert store.authenticate("zhangsan", "reset123") is not None

    with pytest.raises(ValueError):
        store.delete_user("root")         # 内置超管不可删，避免锁死
    assert store.delete_user("zhangsan") is True
    assert store.delete_user("zhangsan") is False
    # 重新加载后数据仍在（持久化）
    assert UserStore(tmp_path / "users.json").authenticate("root", "root123")


def test_session_expiry_and_login_throttle(tmp_path):
    users = UserStore(tmp_path / "u.json", "root", "root123")
    sessions = SessionStore(ttl_hours=1)
    auth = AuthService(users, sessions, max_attempts=3, lock_seconds=60)
    session, msg = auth.login("root", "root123")
    assert session and not msg and auth.resolve(session["token"])["role"] == "admin"
    auth.logout(session["token"])
    assert auth.resolve(session["token"]) is None
    for _ in range(3):
        assert auth.login("root", "bad")[0] is None
    assert "失败次数过多" in auth.login("root", "root123")[1]


# ---------- HTTP 接口 ----------

def test_login_and_me(auth_api):
    assert auth_api.get("/api/auth/me").json()["authenticated"] is False
    bad = _login(auth_api, "root", "wrong")
    assert bad["success"] is False and "错误" in bad["msg"]
    ok = _login(auth_api, "root", "root123")
    assert ok["success"] is True and ok["role"] == "admin" and ok["token"]
    me = auth_api.get("/api/auth/me", headers=_headers(ok["token"])).json()
    assert me["authenticated"] is True and me["username"] == "root"


def test_protected_endpoints_require_login(auth_api):
    assert auth_api.get("/api/settings").status_code == 401
    assert auth_api.get("/api/auth/users").status_code == 401
    token = _login(auth_api, "root", "root123")["token"]
    assert auth_api.get("/api/snapshot", headers=_headers(token)).status_code == 200
    assert auth_api.get("/board").status_code == 200   # 静态页免登录，登录框在页面内
    assert auth_api.get("/health").status_code == 200


def test_only_admin_can_manage_users(auth_api):
    admin = _login(auth_api, "root", "root123")["token"]
    created = auth_api.post("/api/auth/users",
                            headers=_headers(admin),
                            json={"username": "lisi", "password": "pass123"})
    assert created.status_code == 200 and created.json()["success"] is True
    assert created.json()["user"]["role"] == "user"
    assert auth_api.post("/api/auth/users", headers=_headers(admin),
                         json={"username": "lisi", "password": "x12345"}).json()["success"] is False

    users = auth_api.get("/api/auth/users", headers=_headers(admin)).json()
    assert users["total"] == 2

    normal = _login(auth_api, "lisi", "pass123")["token"]
    assert normal
    assert auth_api.get("/api/auth/users", headers=_headers(normal)).status_code == 403
    assert auth_api.post("/api/auth/users", headers=_headers(normal),
                         json={"username": "wangwu", "password": "x12345"}).status_code == 403
    # 普通用户不做权限管理：监控 / 控制 / 设置接口都能用
    assert auth_api.get("/api/snapshot", headers=_headers(normal)).status_code == 200
    assert auth_api.get("/api/settings", headers=_headers(normal)).status_code == 200
    assert auth_api.get("/api/apps/search", headers=_headers(normal)).status_code == 200

    deleted = auth_api.delete("/api/auth/users/lisi", headers=_headers(admin)).json()
    assert deleted["success"] is True
    assert auth_api.delete("/api/auth/users/root",
                           headers=_headers(admin)).json()["success"] is False


def test_change_password_and_logout(auth_api):
    token = _login(auth_api, "root", "root123")["token"]
    assert auth_api.post("/api/auth/password", headers=_headers(token),
                         json={"oldPassword": "bad", "newPassword": "newpass"}).json()["success"] is False
    out = auth_api.post("/api/auth/password", headers=_headers(token),
                        json={"oldPassword": "root123", "newPassword": "newpass"})
    assert out.json()["success"] is True
    assert auth_api.get("/api/settings", headers=_headers(token)).status_code == 401  # 旧 token 作废
    assert _login(auth_api, "root", "newpass")["success"] is True

    fresh = _login(auth_api, "root", "newpass")["token"]
    assert auth_api.post("/api/auth/logout", headers=_headers(fresh)).json()["success"] is True
    assert auth_api.get("/api/settings", headers=_headers(fresh)).status_code == 401


def test_websocket_requires_valid_token(auth_api):
    token = _login(auth_api, "root", "root123")["token"]
    with auth_api.websocket_connect("/ws?token=" + token) as ws:
        assert ws.receive_json()["type"] == "snapshot"
    with pytest.raises(Exception):
        with auth_api.websocket_connect("/ws") as ws:
            ws.receive_json()


# ---------- 仅当天运行 ----------

def test_build_snapshot_filters_yesterday_records():
    fmt = "%Y-%m-%d %H:%M:%S"
    yesterday = (datetime.now() - timedelta(days=1)).strftime(fmt)
    today = datetime.now().strftime(fmt)

    def row(task_id, status, created):
        return {"taskUuid": task_id, "taskName": "流程" + task_id,
                "status": status, "createTime": created, "updateTime": created,
                "taskClients": [{"robotClientUuid": "c1"}]}

    newest = {"data": {"result": [
        row("today-ok", "finish", today),
        row("today-err", "error", today),
        row("old-ok", "finish", yesterday),
        row("no-time", "finish", ""),
    ]}}
    snap = build_snapshot({"data": []}, newest)
    assert [r.id for r in snap.runs] == ["today-ok", "today-err"]
    assert snap.overview.runs_today == 2
    assert snap.overview.error_count == 1
    assert snap.day == datetime.now().date().isoformat()
    assert "date" in snap.to_dict()

    # 显式传 today（跨天边界可测），且可关闭过滤用于排障
    assert len(filter_today(snap.runs, datetime.now().date())) == 2
    all_runs = build_snapshot({"data": []}, newest, only_today=False)
    assert len(all_runs.runs) == 4
