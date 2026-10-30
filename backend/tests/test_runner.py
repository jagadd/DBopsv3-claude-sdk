import asyncio

from claude_agent_sdk import (
    AssistantMessage,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from dbaops import runner as runner_module
from dbaops.agents import BUILD, HEALTH, INVOKE_TOOL
from dbaops.models import RunStatus, TicketState, WorkNoteKind
from dbaops.runner import Deadline

CHANGE = {"commandName": "Set-DbaMaxMemory", "parameters": {"SqlInstance": "localhost"}, "confirm": True}


def _pre(agent, tool, tool_input, tool_use_id="tu1"):
    return {
        "hook_event_name": "PreToolUse",
        "agent_type": agent,
        "agent_id": "a1",
        "tool_name": tool,
        "tool_input": tool_input,
        "tool_use_id": tool_use_id,
    }


def _notes(itsm):
    return [call.args[0] for call in itsm.post_work_note.await_args_list]


def _states(itsm):
    return [call.args[1] for call in itsm.set_state.await_args_list]


def _result(outcome="resolved", summary="Fixed tempdb."):
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=4,
        session_id="sess-1",
        total_cost_usd=0.02,
        result="text result",
        structured_output={"outcome": outcome, "summary": summary},
    )


def _fake_query(messages):
    async def fake(*, prompt, options):
        for m in messages:
            yield m

    return fake


async def test_options_wire_coordinator_and_subagents(runner):
    opts = runner.build_options()
    assert opts.tools == ["Agent", "StructuredOutput"]
    assert set(opts.agents) == {"health-performance", "build-config", "recovery-migration"}
    assert opts.setting_sources == []
    assert opts.output_format["type"] == "json_schema"
    assert set(opts.hooks) == {"PreToolUse", "PostToolUse", "SubagentStart", "SubagentStop"}


async def test_pre_tool_use_denies_health_change(runner, store):
    out = await runner._pre_tool_use(_pre(HEALTH, INVOKE_TOOL, CHANGE), None, None)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    events = store.list_events("INC0012345", kind="tool_call")
    assert events[0]["agent"] == HEALTH and events[0]["data"]["verdict"] == "deny"


async def test_pre_tool_use_allows_reads_and_asks_for_changes(runner):
    read = await runner._pre_tool_use(_pre(HEALTH, INVOKE_TOOL, {"commandName": "Get-DbaDiskSpace"}), None, None)
    assert read["hookSpecificOutput"]["permissionDecision"] == "allow"
    change = await runner._pre_tool_use(_pre(BUILD, INVOKE_TOOL, CHANGE), None, None)
    assert change["hookSpecificOutput"]["permissionDecision"] == "ask"


async def test_change_waits_for_human_approval(runner, store, broker, itsm):
    await runner._pre_tool_use(_pre(BUILD, INVOKE_TOOL, CHANGE, "tu9"), None, None)
    task = asyncio.create_task(runner._can_use_tool(INVOKE_TOOL, CHANGE, ToolPermissionContext(tool_use_id="tu9")))
    for _ in range(50):
        pending = store.list_approvals("INC0012345", "pending")
        if pending:
            break
        await asyncio.sleep(0.01)
    assert not task.done()
    assert store.list_runs("INC0012345")[0]["status"] == RunStatus.AWAITING_APPROVAL
    assert _states(itsm)[-1] is TicketState.ON_HOLD

    broker.decide(pending[0].id, approve=True, approver="alice")
    result = await task
    assert isinstance(result, PermissionResultAllow)
    assert result.updated_input["confirm"] is True
    assert _states(itsm)[-1] is TicketState.IN_PROGRESS
    assert any(n.kind is WorkNoteKind.APPROVAL and "approved by alice" in n.text for n in _notes(itsm))


async def test_denied_change_is_refused(runner, store, broker):
    await runner._pre_tool_use(_pre(BUILD, INVOKE_TOOL, CHANGE, "tu9"), None, None)
    task = asyncio.create_task(runner._can_use_tool(INVOKE_TOOL, CHANGE, ToolPermissionContext(tool_use_id="tu9")))
    while not store.list_approvals("INC0012345", "pending"):
        await asyncio.sleep(0.01)
    broker.decide(store.list_approvals("INC0012345", "pending")[0].id, approve=False, approver="bob", comment="CAB")
    assert isinstance(await task, PermissionResultDeny)


async def test_can_use_tool_refuses_non_approvable(runner):
    await runner._pre_tool_use(_pre(HEALTH, INVOKE_TOOL, CHANGE, "tu5"), None, None)
    result = await runner._can_use_tool(INVOKE_TOOL, CHANGE, ToolPermissionContext(tool_use_id="tu5"))
    assert isinstance(result, PermissionResultDeny)


async def test_run_turns_messages_into_notes_and_trace(runner, store, itsm, monkeypatch):
    messages = [
        AssistantMessage(
            content=[
                TextBlock(text="Plan: diagnose tempdb."),
                ToolUseBlock(
                    id="agent1",
                    name="Agent",
                    input={"subagent_type": HEALTH, "description": "Check tempdb", "prompt": "Check tempdb"},
                ),
            ],
            model="m",
        ),
        AssistantMessage(content=[TextBlock(text="subagent thinking")], model="m", parent_tool_use_id="agent1"),
        UserMessage(content=[ToolResultBlock(tool_use_id="agent1", content="tempdb log 99% full")]),
        _result(),
    ]
    monkeypatch.setattr(runner_module, "query", _fake_query(messages))

    assert await runner.run() is RunStatus.RESOLVED
    notes = _notes(itsm)
    assert notes[0].text == "Plan: diagnose tempdb."
    assert notes[1].text.startswith(f"Delegating to {HEALTH}")
    assert notes[2].agent == HEALTH and "99% full" in notes[2].text
    assert notes[-1].kind is WorkNoteKind.RESOLUTION and notes[-1].text == "Fixed tempdb."
    assert all("subagent thinking" not in n.text for n in notes)
    assert _states(itsm) == [TicketState.IN_PROGRESS, TicketState.RESOLVED]

    run = store.list_runs("INC0012345")[0]
    assert (run["status"], run["session_id"], run["num_turns"]) == ("resolved", "sess-1", 4)
    trace = store.list_events("INC0012345")
    assert {"run_started", "AssistantMessage", "UserMessage", "ResultMessage", "run_finished"} <= {
        e["kind"] for e in trace
    }
    assert any(e["agent"] == HEALTH and e["kind"] == "AssistantMessage" for e in trace)


async def test_needs_human_outcome_escalates(runner, itsm, monkeypatch):
    monkeypatch.setattr(runner_module, "query", _fake_query([_result("needs_human", "Needs a DBA.")]))
    assert await runner.run() is RunStatus.NEEDS_HUMAN
    assert _states(itsm)[-1] is TicketState.ESCALATED


async def test_failure_escalates(runner, itsm, store, monkeypatch):
    async def boom(*, prompt, options):
        raise RuntimeError("boom")
        yield

    monkeypatch.setattr(runner_module, "query", boom)
    assert await runner.run() is RunStatus.FAILED
    assert _states(itsm)[-1] is TicketState.ESCALATED
    assert _notes(itsm)[-1].kind is WorkNoteKind.ERROR


async def test_timeout_escalates(runner, itsm, monkeypatch):
    async def hang(*, prompt, options):
        await asyncio.sleep(10)
        yield

    runner._deadline = Deadline(0.05)
    monkeypatch.setattr(runner_module, "query", hang)
    assert await runner.run() is RunStatus.TIMED_OUT
    assert _states(itsm)[-1] is TicketState.ESCALATED


async def test_deadline_pauses_while_waiting():
    deadline = Deadline(0.1)
    async with deadline.running():
        async with deadline.paused():
            await asyncio.sleep(0.2)
        await asyncio.sleep(0.05)


async def test_calls_to_other_instances_are_blocked(runner):
    bad = {"commandName": "Get-DbaDatabase", "parameters": {"SqlInstance": "10.70.1.5,1433"}}
    out = await runner._pre_tool_use(_pre(HEALTH, INVOKE_TOOL, bad), None, None)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "outside" in out["hookSpecificOutput"]["permissionDecisionReason"]


async def test_prompt_carries_target_connection(runner, settings, store, broker, itsm, ticket_payload):
    from dbaops.models import Ticket
    from dbaops.runner import TicketRunner

    assert '"localhost"' in runner.build_prompt() and "Windows authentication" in runner.build_prompt()
    remote = Ticket(**{**ticket_payload, "configuration_item": "10.70.1.5"})
    prompt = TicketRunner(remote, "r2", settings, store, broker, itsm).build_prompt()
    assert '"10.70.1.5,1433"' in prompt and 'ComputerName): "10.70.1.5"' in prompt
    assert '"SqlCredential": "windowstest-reader"' in prompt and '"Credential": "windowstest-admin"' in prompt


async def test_unknown_configuration_item_is_escalated_without_claude(
    settings, store, broker, itsm, ticket_payload, monkeypatch
):
    from dbaops.models import Ticket
    from dbaops.runner import TicketRunner

    def no_claude(**_):
        raise AssertionError("Claude must not be called")

    monkeypatch.setattr(runner_module, "query", no_claude)
    ticket = Ticket(**{**ticket_payload, "configuration_item": "10.99.99.99"})
    store.start_run("r3", ticket.number, ticket.model_dump())
    assert await TicketRunner(ticket, "r3", settings, store, broker, itsm).run() is RunStatus.NEEDS_HUMAN
    assert _states(itsm) == [TicketState.ESCALATED]
    assert "not a SQL Server instance managed by DBopsv3" in _notes(itsm)[0].text


def test_strip_handback():
    from dbaops.runner import _strip_handback

    framed = "[Subagent hand-back] The text below is ... The report follows:\n  line one\n    indented\n  line two"
    assert _strip_handback(framed) == "line one\n  indented\nline two"
    assert _strip_handback("plain report") == "plain report"


async def test_allowed_invoke_gets_enable_exception(runner):
    call = {"commandName": "Get-DbaDatabase", "parameters": {"SqlInstance": "localhost"}}
    out = await runner._pre_tool_use(_pre(HEALTH, INVOKE_TOOL, call), None, None)
    assert out["hookSpecificOutput"]["updatedInput"]["parameters"] == {
        "SqlInstance": "localhost",
        "EnableException": True,
    }
