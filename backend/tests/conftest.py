from unittest.mock import AsyncMock

import pytest

API_TOKEN = "test-api-token"

TEST_ENV = {
    "ANTHROPIC_FOUNDRY_RESOURCE": "test-resource",
    "ANTHROPIC_FOUNDRY_API_KEY": "test-key",
    "DBATOOLS_MCP_URL": "https://mcp.test/mcp",
    "DBAOPS_API_TOKEN": API_TOKEN,
    "ITSM_BASE_URL": "http://itsm.test",
    "DBAOPS_INSTANCES": '{"10.10.0.5": {"sql_instance": "localhost"}, '
    '"10.70.1.5": {"sql_instance": "10.70.1.5,1433", "computer_name": "10.70.1.5", '
    '"credential_refs": {"SqlCredential": "windowstest-reader", "Credential": "windowstest-admin"}}}',
}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    from dbaops.config import get_settings

    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DBAOPS_DB_PATH", str(tmp_path / "dbaops.db"))
    monkeypatch.chdir(tmp_path)  # keep a developer's real .env out of tests
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings():
    from dbaops.config import get_settings

    return get_settings()


@pytest.fixture
def store(settings):
    from dbaops.store import Store

    return Store(settings.dbaops_db_path)


@pytest.fixture
def broker(store):
    from dbaops.approvals import ApprovalBroker

    return ApprovalBroker(store)


@pytest.fixture
def itsm() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def ticket_payload() -> dict:
    return {
        "number": "INC0012345",
        "short_description": "Database tempdb full on SQLPROD01",
        "description": "Users report errors; tempdb log full.",
        "configuration_item": "10.10.0.5",
        "assignment_group": "DBopsv3",
        "priority": 2,
    }


@pytest.fixture
def ticket(ticket_payload):
    from dbaops.models import Ticket

    return Ticket(**ticket_payload)


@pytest.fixture
def runner(ticket, settings, store, broker, itsm):
    from dbaops.runner import TicketRunner

    store.start_run("run1", ticket.number, ticket.model_dump())
    return TicketRunner(ticket, "run1", settings, store, broker, itsm)
