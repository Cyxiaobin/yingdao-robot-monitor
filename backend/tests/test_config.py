""".env 加载与 MOCK 安全闸：无凭证绝不向影刀发真实请求。"""
import os

from app.config import Settings, _load_dotenv

_ENV_KEYS = (
    "YINGDAO_ACCESS_KEY_ID",
    "YINGDAO_ACCESS_KEY_SECRET",
    "YINGDAO_MOCK",
    "YINGDAO_BASE_URL",
    "POLL_INTERVAL",
    "ENABLE_POLLER",
)


def _isolated(monkeypatch, tmp_path, text=""):
    """清掉真实环境变量，把 .env 指向临时文件，保证测试不碰真实凭证。"""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text(text, encoding="utf-8")
    monkeypatch.setattr("app.config._DOTENV_PATH", env)
    return env


def test_dotenv_loads_credentials(monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path, "# 注释\nYINGDAO_ACCESS_KEY_ID=KEY\nYINGDAO_ACCESS_KEY_SECRET=SECRET\nYINGDAO_MOCK=0\n")
    s = Settings.from_env()
    assert s.access_key_id == "KEY"
    assert s.access_key_secret == "SECRET"
    assert s.mock_mode is False


def test_explicit_env_wins_over_dotenv(monkeypatch, tmp_path):
    env = _isolated(monkeypatch, tmp_path, "YINGDAO_ACCESS_KEY_ID=FROM_FILE\n")
    monkeypatch.setenv("YINGDAO_ACCESS_KEY_ID", "FROM_SHELL")
    _load_dotenv(env)
    assert os.environ["YINGDAO_ACCESS_KEY_ID"] == "FROM_SHELL"


def test_no_credentials_forces_mock(monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path, "YINGDAO_MOCK=0\n")
    s = Settings.from_env()
    assert s.mock_mode is True


def test_quoted_and_blank_lines_are_handled(monkeypatch, tmp_path):
    env = _isolated(monkeypatch, tmp_path, '\n# c\nYINGDAO_BASE_URL="https://example.com/"  \nBROKEN_LINE\n')
    _load_dotenv(env)
    assert os.environ["YINGDAO_BASE_URL"] == "https://example.com/"
