import asyncio

import pytest
from conftest import API_TOKEN
from fastapi.testclient import TestClient

from dbaops import service as service_module
from dbaops.api import app

AUTH = {"Authorization": f"Bearer {API_TOKEN}"}


class HangingRunner:
    def __init__(self, *args):
        pass

    async def run(self):
        await asyncio.sleep(3600)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(service_module, "TicketRunner", HangingRunner)
    with TestClient(app) as c:
        yield c


def test_requires_token(client, ticket_payload):
    assert client.post("/api/tickets", json=ticket_payload).status_code in (401, 403)
    assert client.post("/api/tickets", json=ticket_payload, headers={"Authorization": "Bearer x"}).status_code == 401
    assert client.get("/api/tickets/INC0012345/trace").status_code in (401, 403)


def test_one_active_run_per_ticket(client, ticket_payload):
    first = client.post("/api/tickets", json=ticket_payload, headers=AUTH)
    assert first.status_code == 202
    assert client.post("/api/tickets", json=ticket_payload, headers=AUTH).status_code == 409
    runs = client.get("/api/tickets/INC0012345/runs", headers=AUTH).json()
    assert [r["run_id"] for r in runs] == [first.json()["run_id"]]
    assert runs[0]["status"] == "running"


@pytest.mark.parametrize(
    "override",
    [{"assignment_group": "Network"}, {"configuration_item": "SQL01; DROP DATABASE x"}, {"number": "nope"}],
)
def test_rejects_invalid_ticket(client, ticket_payload, override):
    assert client.post("/api/tickets", json=ticket_payload | override, headers=AUTH).status_code == 422


def test_trace_and_approval_endpoints(client):
    store, broker = client.app.state.store, client.app.state.broker
    store.add_event("r1", "INC0012345", "health-performance", "tool_call", {"tool": "x"})
    store.add_event("r1", "INC0012345", "coordinator", "work_note", {"text": "hi"})

    trace = client.get("/api/tickets/INC0012345/trace", headers=AUTH, params={"agent": "health-performance"}).json()
    assert [e["kind"] for e in trace] == ["tool_call"]

    async def open_approval():
        return broker.open("r1", "INC0012345", "build-config", "tool", {"confirm": True})

    approval = client.portal.call(open_approval)
    pending = client.get("/api/approvals", headers=AUTH, params={"status": "pending"}).json()
    assert [a["id"] for a in pending] == [approval.id]

    body = {"decision": "approve", "approver": "alice"}
    decided = client.post(f"/api/approvals/{approval.id}", json=body, headers=AUTH)
    assert decided.status_code == 200 and decided.json()["status"] == "approved"
    assert client.post(f"/api/approvals/{approval.id}", json=body, headers=AUTH).status_code == 409


def test_restart_marks_active_runs_interrupted(settings, store, ticket):
    store.start_run("old", ticket.number, ticket.model_dump())
    store.recover_after_restart()
    assert store.list_runs(ticket.number)[0]["status"] == "interrupted"
    assert store.start_run("new", ticket.number, ticket.model_dump())


@pytest.mark.parametrize("value", ["https://x.services.ai.azure.com/api/projects/p", "x.services.ai.azure.com", "-bad"])
def test_foundry_resource_must_be_a_name(monkeypatch, value):
    from pydantic import ValidationError

    from dbaops.config import Settings

    monkeypatch.setenv("ANTHROPIC_FOUNDRY_RESOURCE", value)
    with pytest.raises(ValidationError, match="resource name only"):
        Settings()
