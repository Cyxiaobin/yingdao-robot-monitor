"""本地账号体系：超级管理员 + 普通用户 + 会话 token。

设计要点（2026-11-17 新增登录功能）：
- 密码用 PBKDF2-HMAC-SHA256 加盐哈希，users.json 里没有任何明文口令
- 会话 token 只存内存（secrets.token_urlsafe），服务重启需重新登录
- 普通用户在看板 / 异常 / 应用 / 设置上与管理员同权；
  只有 /api/auth/users 这组「账号管理」接口要求 admin 角色
- 超级管理员账号由 SUPER_ADMIN_USERNAME / SUPER_ADMIN_PASSWORD 首次启动时引导生成
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_ITERATIONS = 120_000
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{3,32}$")
_PASSWORD_MIN = 6
_PASSWORD_MAX = 128


def _ts() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """恒定时间比较；格式异常/旧格式一律判失败，不抛异常。"""
    try:
        algo, iters, salt_hex, digest_hex = str(encoded).split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac(
            "sha256", str(password).encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(calc.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def validate_username(value: str) -> str:
    name = str(value or "").strip().lower()
    if not _USERNAME_RE.match(name):
        raise ValueError("账号需为 3-32 位字母、数字或 . _ @ -")
    return name


def validate_password(value: str) -> str:
    pwd = str(value or "")
    if not (_PASSWORD_MIN <= len(pwd) <= _PASSWORD_MAX):
        raise ValueError(f"密码长度需为 {_PASSWORD_MIN}-{_PASSWORD_MAX} 位")
    return pwd


@dataclass
class User:
    username: str
    role: str                       # admin | user
    password_hash: str
    created_at: str = ""
    last_login_at: str = ""
    builtin: bool = False           # 内置超级管理员：禁止删除
    must_change_password: bool = False

    def public(self) -> dict:
        return {
            "username": self.username,
            "role": self.role,
            "createdAt": self.created_at,
            "lastLoginAt": self.last_login_at,
            "builtin": self.builtin,
            "mustChangePassword": self.must_change_password,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "User":
        return cls(
            username=str(raw.get("username") or ""),
            role="admin" if raw.get("role") == "admin" else "user",
            password_hash=str(raw.get("passwordHash") or ""),
            created_at=str(raw.get("createdAt") or ""),
            last_login_at=str(raw.get("lastLoginAt") or ""),
            builtin=bool(raw.get("builtin")),
            must_change_password=bool(raw.get("mustChangePassword")),
        )

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "role": self.role,
            "passwordHash": self.password_hash,
            "createdAt": self.created_at,
            "lastLoginAt": self.last_login_at,
            "builtin": self.builtin,
            "mustChangePassword": self.must_change_password,
        }


class UserStore:
    """users.json 持久化。文件只在账号变更时写，读操作全部走内存。"""

    def __init__(self, path: Path, admin_username: str = "admin",
                 admin_password: str = "admin123") -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._users: dict[str, User] = {}
        self._load_or_bootstrap(admin_username, admin_password)

    def _load_or_bootstrap(self, admin_username: str, admin_password: str) -> None:
        admin_name = validate_username(admin_username)
        if self.path.is_file():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                rows = payload.get("users", []) if isinstance(payload, dict) else payload
                self._users = {
                    u.username: u for u in (User.from_dict(x) for x in rows)
                    if u.username and u.password_hash
                }
            except (ValueError, OSError, TypeError):
                self._users = {}
        if self._users:
            return
        # 首次启动 / 文件损坏：引导内置超级管理员。默认口令应由部署者尽快修改。
        self._users[admin_name] = User(
            username=admin_name, role="admin",
            password_hash=hash_password(validate_password(admin_password)),
            created_at=_ts(), builtin=True, must_change_password=True,
        )
        self._write()

    def _write(self) -> None:
        """原子写：先写同目录临时文件再 os.replace，避免崩溃时写坏账号库。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rows = [self._users[k].to_dict() for k in sorted(self._users)]
        payload = json.dumps({"version": 1, "users": rows}, ensure_ascii=False, indent=2)
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, self.path)
        finally:
            if tmp.exists():
                tmp.unlink()

    def list_users(self) -> list[dict]:
        with self._lock:
            return [self._users[k].public() for k in sorted(self._users)]

    def get(self, username: str) -> User | None:
        with self._lock:
            return self._users.get(str(username or "").strip().lower())

    def authenticate(self, username: str, password: str) -> User | None:
        user = self.get(username)
        if user is None or not verify_password(password, user.password_hash):
            return None
        with self._lock:
            user.last_login_at = _ts()
            self._write()
        return user

    def add_user(self, username: str, password: str) -> dict:
        """管理员只能创建普通用户；不允许通过接口再造一个 admin。"""
        name = validate_username(username)
        pwd = validate_password(password)
        with self._lock:
            if name in self._users:
                raise ValueError("该账号已存在")
            user = User(username=name, role="user", password_hash=hash_password(pwd),
                        created_at=_ts())
            self._users[name] = user
            self._write()
        return user.public()

    def delete_user(self, username: str) -> bool:
        name = str(username or "").strip().lower()
        with self._lock:
            user = self._users.get(name)
            if user is None:
                return False
            if user.builtin:
                raise ValueError("内置超级管理员不能删除")
            del self._users[name]
            self._write()
        return True

    def reset_password(self, username: str, new_password: str) -> bool:
        """管理员重置他人密码；不校验旧密码。"""
        pwd = validate_password(new_password)
        with self._lock:
            user = self._users.get(str(username or "").strip().lower())
            if user is None:
                return False
            user.password_hash = hash_password(pwd)
            user.must_change_password = False
            self._write()
        return True

    def change_password(self, username: str, old_password: str,
                        new_password: str) -> bool:
        """本人改密：必须验证旧密码。"""
        pwd = validate_password(new_password)
        with self._lock:
            user = self._users.get(str(username or "").strip().lower())
            if user is None or not verify_password(old_password, user.password_hash):
                return False
            user.password_hash = hash_password(pwd)
            user.must_change_password = False
            self._write()
        return True


class SessionStore:
    """内存会话表。token 不落盘、不进日志；过期自动清理。"""

    def __init__(self, ttl_hours: float = 12.0) -> None:
        self.ttl = max(0.5, ttl_hours) * 3600
        self._items: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, user: User) -> dict:
        token = secrets.token_urlsafe(32)
        now = time.time()
        session = {
            "token": token,
            "username": user.username,
            "role": user.role,
            "mustChangePassword": user.must_change_password,
            "issuedAt": now,
            "expiresAt": now + self.ttl,
        }
        with self._lock:
            self._purge(now)
            self._items[token] = session
        return dict(session)

    def resolve(self, token: str) -> dict | None:
        if not token:
            return None
        with self._lock:
            self._purge(time.time())
            session = self._items.get(token)
            return dict(session) if session else None

    def revoke(self, token: str) -> None:
        with self._lock:
            self._items.pop(token, None)

    def _purge(self, now: float) -> None:
        for key in [k for k, v in self._items.items() if v["expiresAt"] <= now]:
            self._items.pop(key, None)

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._items)


class AuthService:
    """登录入口：带失败次数限流，避免局域网内被暴力猜口令。"""

    def __init__(self, users: UserStore, sessions: SessionStore,
                 max_attempts: int = 5, lock_seconds: float = 60.0) -> None:
        self.users = users
        self.sessions = sessions
        self.max_attempts = max_attempts
        self.lock_seconds = lock_seconds
        self._failures: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def login(self, username: str, password: str) -> tuple[dict | None, str]:
        name = str(username or "").strip().lower()
        with self._lock:
            count, first_at = self._failures.get(name, (0, time.time()))
            if count >= self.max_attempts and time.time() - first_at < self.lock_seconds:
                left = int(self.lock_seconds - (time.time() - first_at)) + 1
                return None, f"失败次数过多，请 {left} 秒后再试"
        user = self.users.authenticate(name, password)
        if user is None:
            with self._lock:
                count, first_at = self._failures.get(name, (0, time.time()))
                if time.time() - first_at >= self.lock_seconds:
                    count, first_at = 0, time.time()
                self._failures[name] = (count + 1, first_at)
            return None, "账号或密码错误"
        with self._lock:
            self._failures.pop(name, None)
        return self.sessions.create(user), ""

    def logout(self, token: str) -> None:
        self.sessions.revoke(token)

    def resolve(self, token: str) -> dict | None:
        return self.sessions.resolve(token)
