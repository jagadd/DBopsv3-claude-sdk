from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .agents import AGENT_TOOL, CHANGE_CAPABLE, COORDINATOR_TOOLS, DBATOOLS_PREFIX, HEALTH, INVOKE_TOOL, SUBAGENTS

# dbatools verbs that never change state. Everything else (Set, New, Copy, Invoke, Export, Watch, …) is a change.
READ_ONLY_VERBS = frozenset({"get", "test", "find", "measure", "compare"})
INSTANCE_PARAMS = ("sqlinstance", "source", "destination", "computername", "primary", "secondary")


class Verdict(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    NEEDS_APPROVAL = "needs_approval"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str = ""


def is_change(tool_name: str, tool_input: dict[str, Any]) -> bool:
    if tool_name != INVOKE_TOOL:
        return False
    if tool_input.get("confirm") not in (None, False):
        return True
    verb = str(tool_input.get("commandName", "")).split("-", 1)[0].lower()
    return verb not in READ_ONLY_VERBS


def decide(agent_type: str | None, tool_name: str, tool_input: dict[str, Any]) -> Decision:
    """Server-side policy for every tool call. Unknown agent types get the coordinator's (narrowest) rights."""
    if agent_type not in SUBAGENTS:
        if tool_name == AGENT_TOOL and tool_input.get("subagent_type") not in SUBAGENTS:
            return Decision(Verdict.DENY, f"Delegate only to the DBAops specialists: {', '.join(SUBAGENTS)}.")
        if tool_name in COORDINATOR_TOOLS:
            return Decision(Verdict.ALLOW)
        return Decision(Verdict.DENY, "The coordinator only delegates to specialist subagents via the Agent tool.")

    if not tool_name.startswith(DBATOOLS_PREFIX):
        return Decision(Verdict.DENY, f"{agent_type} may only use dbatools tools.")
    if not is_change(tool_name, tool_input):
        return Decision(Verdict.ALLOW)
    if agent_type == HEALTH:
        return Decision(
            Verdict.DENY,
            f"{HEALTH} is read-only. Report the exact change you recommend to the coordinator instead.",
        )
    if agent_type in CHANGE_CAPABLE:
        return Decision(Verdict.NEEDS_APPROVAL, "State-changing command requires human approval.")
    return Decision(Verdict.DENY, "Not permitted.")


def _values(value: Any) -> Iterable[str]:
    if isinstance(value, list | tuple):
        return [str(v) for v in value]
    return [str(value)]


def target_violation(
    tool_input: dict[str, Any], allowed_instances: Iterable[str], allowed_credential_refs: dict[str, str]
) -> str | None:
    """Reason a dbatools call reaches outside the ticket's instance or credentials, else None."""
    allowed = {i.lower() for i in allowed_instances}
    parameters = tool_input.get("parameters") or {}
    for name, value in parameters.items():
        key = name.lower()
        if "credential" in key:
            return f"Credentials must be passed via credentialRefs, not parameters ({name})."
        if key in INSTANCE_PARAMS and any(v.lower() not in allowed for v in _values(value)):
            return f"{name}={value!r} is outside this ticket's instance; only {sorted(allowed)} is permitted."
    permitted = {k.lower(): v for k, v in allowed_credential_refs.items()}
    for name, alias in (tool_input.get("credentialRefs") or {}).items():
        if permitted.get(name.lower()) != alias:
            return f"Credential profile {alias!r} for {name} is not authorised for this ticket's instance."
    return None
