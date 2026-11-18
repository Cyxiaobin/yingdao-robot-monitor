"""测试夹具：全部跑在 MOCK 模式 + 关闭后台轮询，无需网络、无需密钥。"""
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.mock_data import MockStore
from app.yingdao_client import YingdaoClient


@pytest.fixture
def settings():
    # 现有 79 个测试聚焦业务链路，免登录；鉴权由 test_auth_api.py 单独开启验证
    return Settings(mock_mode=True, enable_poller=False, poll_interval=1.0,
                    auth_required=False)


@pytest.fixture
def store():
    s = MockStore()
    s.reset()
    return s


@pytest.fixture
def client(settings, store):
    return YingdaoClient(settings, mock_store=store)


@pytest.fixture
def app(settings, client, store):
    return create_app(settings=settings, client=client, store=store)


@pytest.fixture
def api(app):
    with TestClient(app) as test_client:
        yield test_client
