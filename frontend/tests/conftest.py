from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

API_TOKEN = "test-api-token"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    from itsm_mimic.config import get_settings

    monkeypatch.setenv("ITSM_DB_PATH", str(tmp_path / "itsm.db"))
    monkeypatch.setenv("ITSM_API_TOKEN", API_TOKEN)
    monkeypatch.setenv("DBAOPS_API_TOKEN", "test-backend-token")
    monkeypatch.chdir(tmp_path)  # keep a developer's real .env out of tests
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def dispatch(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr("itsm_mimic.app.dispatch_incident", mock)
    return mock


@pytest.fixture
def client(dispatch):
    from itsm_mimic.app import app

    with TestClient(app, follow_redirects=False) as c:
        yield c


@pytest.fixture
def form() -> dict:
    return {
        "short_description": "tempdb full on SQLPROD01",
        "description": "Users report error 1105.",
        "configuration_item": "SQLPROD01\\INST1",
        "assignment_group": "DBAopsv3",
        "priority": "2",
        "category": "Database",
    }
