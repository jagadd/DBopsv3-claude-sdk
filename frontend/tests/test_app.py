from conftest import API_TOKEN

AUTH = {"Authorization": f"Bearer {API_TOKEN}"}


def _create(client, form) -> str:
    resp = client.post("/incidents", data=form)
    assert resp.status_code == 303
    return resp.headers["location"].rsplit("/", 1)[-1]


def test_create_incident_assigned_to_agent_dispatches(client, form, dispatch):
    number = _create(client, form)
    assert number == "INC0010001"
    dispatch.assert_awaited_once()
    assert dispatch.await_args.args[0] == number
    assert number in client.get("/").text


def test_create_incident_for_human_group_does_not_dispatch(client, form, dispatch):
    _create(client, form | {"assignment_group": "DBA Team"})
    dispatch.assert_not_awaited()


def test_reassigning_to_agent_dispatches(client, form, dispatch):
    number = _create(client, form | {"assignment_group": "DBA Team"})
    resp = client.post(f"/incidents/{number}", data={"assignment_group": "DBAopsv3", "state": "New", "priority": "2"})
    assert resp.status_code == 303
    dispatch.assert_awaited_once()


def test_invalid_form_is_rejected(client, form, dispatch):
    resp = client.post("/incidents", data=form | {"configuration_item": "SQL01; DROP TABLE x"})
    assert resp.status_code == 422
    dispatch.assert_not_awaited()


def test_html_is_escaped(client, form):
    number = _create(client, form | {"short_description": "<script>alert(1)</script>"})
    page = client.get(f"/incidents/{number}").text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_agent_posts_work_note_and_state(client, form):
    number = _create(client, form)
    assert client.post(f"/api/incidents/{number}/work_notes", json={"kind": "progress", "text": "x"}).status_code in (
        401,
        403,
    )

    resp = client.post(
        f"/api/incidents/{number}/work_notes",
        json={"ticket_number": number, "kind": "progress", "text": "Checking tempdb", "created_at": None},
        headers=AUTH,
    )
    assert resp.status_code == 201
    assert client.patch(f"/api/incidents/{number}", json={"state": "In Progress"}, headers=AUTH).status_code == 200

    data = client.get(f"/api/incidents/{number}").json()
    assert data["state"] == "In Progress"
    assert data["work_notes"][0]["text"] == "Checking tempdb"
    assert data["work_notes"][0]["author"] == "DBAopsv3 Agent"


def test_rejects_unknown_state_and_incident(client, form):
    number = _create(client, form)
    assert client.patch(f"/api/incidents/{number}", json={"state": "Bogus"}, headers=AUTH).status_code == 422
    assert client.patch("/api/incidents/INC9999999", json={"state": "Resolved"}, headers=AUTH).status_code == 404


def test_agent_note_is_attributed_to_subagent(client, form):
    number = _create(client, form)
    note = {"kind": "result", "text": "tempdb 99% full", "agent": "health-performance"}
    assert client.post(f"/api/incidents/{number}/work_notes", json=note, headers=AUTH).status_code == 201
    assert client.get(f"/api/incidents/{number}").json()["work_notes"][0]["author"] == "DBAopsv3 · health-performance"


def test_approvals_are_proxied_and_decided(client, form, monkeypatch):
    from unittest.mock import AsyncMock

    from itsm_mimic import backend

    number = _create(client, form)
    pending = [{"id": "abcdef123456", "agent": "build-config", "tool_name": "t", "tool_input": {"confirm": True}}]
    monkeypatch.setattr(backend, "pending_approvals", AsyncMock(return_value=pending))
    decide = AsyncMock(return_value={})
    monkeypatch.setattr(backend, "decide_approval", decide)

    assert client.get(f"/api/incidents/{number}/approvals").json() == pending
    resp = client.post(
        f"/incidents/{number}/approvals/abcdef123456",
        data={"decision": "approve", "approver": "alice", "comment": "CHG001"},
    )
    assert resp.status_code == 303
    assert decide.await_args.args[1:] == ("abcdef123456", "approve", "alice", "CHG001")
    assert (
        client.post(f"/incidents/{number}/approvals/bad-id", data={"decision": "approve", "approver": "a"}).status_code
        == 422
    )


def test_backend_down_is_reported_not_crashing(client, form, monkeypatch):
    from unittest.mock import AsyncMock

    from itsm_mimic import backend

    number = _create(client, form)
    monkeypatch.setattr(backend, "pending_approvals", AsyncMock(side_effect=backend.BackendError("down")))
    monkeypatch.setattr(backend, "runs", AsyncMock(side_effect=backend.BackendError("down")))
    assert client.get(f"/api/incidents/{number}/approvals").status_code == 502
    page = client.get(f"/incidents/{number}/trace")
    assert page.status_code == 200 and "down" in page.text


def test_trace_page_renders_escaped_events(client, form, monkeypatch):
    from unittest.mock import AsyncMock

    from itsm_mimic import backend

    number = _create(client, form)
    runs = [
        {
            "run_id": "r" * 32,
            "status": "resolved",
            "started_at": "t",
            "ended_at": None,
            "num_turns": 3,
            "cost_usd": 0.01,
            "session_id": "s1",
        }
    ]
    events = [
        {
            "id": 1,
            "ts": "2026-10-29T10:00:00.000+00:00",
            "agent": "health-performance",
            "kind": "tool_call",
            "data": {"tool": "<b>x</b>", "verdict": "allow"},
        }
    ]
    monkeypatch.setattr(backend, "runs", AsyncMock(return_value=runs))
    monkeypatch.setattr(backend, "trace", AsyncMock(return_value=events))
    page = client.get(f"/incidents/{number}/trace").text
    assert "health-performance" in page and "&lt;b&gt;x&lt;/b&gt;" in page and "<b>x</b>" not in page
