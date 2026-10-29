import pytest

from dbaops.agents import BUILD, HEALTH, INVOKE_TOOL, LIST_TOOL, RECOVERY
from dbaops.policy import Verdict, decide

READ = {"commandName": "Get-DbaDatabase"}
CHANGE = {"commandName": "Set-DbaMaxMemory", "confirm": True}


@pytest.mark.parametrize("agent", [None, "coordinator", "general-purpose"])
def test_coordinator_may_only_delegate(agent):
    assert decide(agent, "Agent", {"subagent_type": HEALTH}).verdict is Verdict.ALLOW
    assert decide(agent, "Agent", {"subagent_type": "general-purpose"}).verdict is Verdict.DENY
    assert decide(agent, "Agent", {}).verdict is Verdict.DENY
    assert decide(agent, "StructuredOutput", {}).verdict is Verdict.ALLOW
    assert decide(agent, INVOKE_TOOL, READ).verdict is Verdict.DENY
    assert decide(agent, "Bash", {}).verdict is Verdict.DENY


@pytest.mark.parametrize("agent", [HEALTH, BUILD, RECOVERY])
def test_specialists_read_freely_and_cannot_use_other_tools(agent):
    assert decide(agent, LIST_TOOL, {}).verdict is Verdict.ALLOW
    assert decide(agent, INVOKE_TOOL, READ).verdict is Verdict.ALLOW
    assert decide(agent, "Bash", {}).verdict is Verdict.DENY
    assert decide(agent, "Agent", {}).verdict is Verdict.DENY


def test_health_cannot_change():
    assert decide(HEALTH, INVOKE_TOOL, CHANGE).verdict is Verdict.DENY
    assert decide(HEALTH, INVOKE_TOOL, {**CHANGE, "confirm": "true"}).verdict is Verdict.DENY


@pytest.mark.parametrize("agent", [BUILD, RECOVERY])
def test_changes_need_approval(agent):
    assert decide(agent, INVOKE_TOOL, CHANGE).verdict is Verdict.NEEDS_APPROVAL


@pytest.mark.parametrize("command", ["Set-DbaMaxMemory", "Invoke-DbaQuery", "Export-DbaLogin", "Watch-DbaDbLogin", ""])
def test_non_read_verbs_are_changes_even_without_confirm(command):
    assert decide(BUILD, INVOKE_TOOL, {"commandName": command}).verdict is Verdict.NEEDS_APPROVAL
    assert decide(HEALTH, INVOKE_TOOL, {"commandName": command}).verdict is Verdict.DENY


@pytest.mark.parametrize(
    "command",
    [
        "Get-DbaDatabase",
        "Test-DbaConnection",
        "Find-DbaInstance",
        "Measure-DbaDiskSpaceRequirement",
        "Compare-DbaAgReplicaSync",
    ],
)
def test_read_verbs_are_allowed(command):
    assert decide(HEALTH, INVOKE_TOOL, {"commandName": command}).verdict is Verdict.ALLOW


def test_target_violation():
    from dbaops.policy import target_violation

    refs_ok = {"SqlCredential": "reader", "Credential": "admin"}
    ok = {"commandName": "Get-DbaDatabase", "parameters": {"SqlInstance": "LOCALHOST"}}
    assert target_violation(ok, {"localhost", "10.10.0.5"}, {}) is None
    other = {"commandName": "Get-DbaDatabase", "parameters": {"SqlInstance": ["localhost", "10.10.0.9"]}}
    assert "outside" in target_violation(other, {"localhost"}, {})
    migrate = {"commandName": "Copy-DbaDatabase", "parameters": {"Source": "localhost", "Destination": "10.10.0.9"}}
    assert target_violation(migrate, {"localhost"}, {})
    raw_cred = {"commandName": "Get-DbaDatabase", "parameters": {"SqlInstance": "localhost", "SqlCredential": "sa"}}
    assert "credentialRefs" in target_violation(raw_cred, {"localhost"}, {})
    sql = {"parameters": {"SqlInstance": "10.70.1.5,1433"}, "credentialRefs": {"SqlCredential": "reader"}}
    assert target_violation(sql, {"10.70.1.5,1433"}, refs_ok) is None
    win = {"parameters": {"ComputerName": "10.70.1.5"}, "credentialRefs": {"Credential": "admin"}}
    assert target_violation(win, {"10.70.1.5"}, refs_ok) is None
    swapped = {"parameters": {"SqlInstance": "10.70.1.5,1433"}, "credentialRefs": {"SqlCredential": "admin"}}
    assert "not authorised" in target_violation(swapped, {"10.70.1.5,1433"}, refs_ok)
    assert "not authorised" in target_violation(sql, {"10.70.1.5,1433"}, {})
