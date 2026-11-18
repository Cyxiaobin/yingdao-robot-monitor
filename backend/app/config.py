"""运行配置：全部来自环境变量，密钥不落盘、不进代码。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_TRUE = {"1", "true", "yes", "on"}
_DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _load_dotenv(path: Path) -> None:
    """读取 backend/.env，只补齐缺失的变量（显式环境变量优先，不覆盖）。"""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in _TRUE


@dataclass(frozen=True)
class Settings:
    access_key_id: str = ""
    access_key_secret: str = ""
    base_url: str = "https://api.yingdao.com"
    poll_interval: float = 5.0
    mock_mode: bool = True
    enable_poller: bool = True
    admin_token: str = ""        # 设置页保存密钥时的管理口令；为空表示不启用（仅建议内网）
    allow_control: bool = True   # 是否允许远程启动/重试/停止
    # ---- 生产安全加固（2026-11-18）----
    callback_token: str = ""          # /api/callback 校验头；为空=不校验（仅内网/测试）
    enforce_password_change: bool = True  # 默认口令用户登录后只允许改密，防止 admin123 长期在用
    strict_real: bool = False         # 生产置 1：无真实凭证立即启动失败，杜绝静默 MOCK 假数据
    # ---- 登录与账号（2026-11-17）----
    auth_required: bool = True   # 关闭后所有接口免登录（仅供本地开发/自动化测试）
    auth_users_file: str = ""   # 为空则用 backend/data/users.json
    super_admin_username: str = "admin"
    super_admin_password: str = "admin123"
    session_ttl_hours: float = 12.0

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv(_DOTENV_PATH)
        key = os.getenv("YINGDAO_ACCESS_KEY_ID", "").strip()
        secret = os.getenv("YINGDAO_ACCESS_KEY_SECRET", "").strip()
        has_credentials = bool(key and secret)

        # 无密钥时强制 MOCK，避免误向影刀发真实请求；有密钥时按 YINGDAO_MOCK 决定
        mock_mode = True if not has_credentials else _flag("YINGDAO_MOCK", False)

        try:
            interval = float(os.getenv("POLL_INTERVAL", "5") or 5)
        except ValueError:
            interval = 5.0

        try:
            ttl = float(os.getenv("SESSION_TTL_HOURS", "12") or 12)
        except ValueError:
            ttl = 12.0

        return cls(
            access_key_id=key,
            access_key_secret=secret,
            base_url=os.getenv("YINGDAO_BASE_URL", "https://api.yingdao.com").rstrip("/"),
            poll_interval=max(1.0, interval),
            mock_mode=mock_mode,
            enable_poller=_flag("ENABLE_POLLER", True),
            admin_token=os.getenv("ADMIN_TOKEN", "").strip(),
            allow_control=_flag("ALLOW_REMOTE_CONTROL", True),
            callback_token=os.getenv("CALLBACK_TOKEN", "").strip(),
            enforce_password_change=_flag("ENFORCE_PASSWORD_CHANGE", True),
            strict_real=_flag("STRICT_REAL", False),
            auth_required=_flag("AUTH_REQUIRED", True),
            auth_users_file=os.getenv("AUTH_USERS_FILE", "").strip(),
            super_admin_username=os.getenv("SUPER_ADMIN_USERNAME", "admin").strip() or "admin",
            super_admin_password=os.getenv("SUPER_ADMIN_PASSWORD", "admin123"),
            session_ttl_hours=ttl,
        )
