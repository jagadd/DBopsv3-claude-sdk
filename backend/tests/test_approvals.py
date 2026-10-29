import asyncio

import pytest

from dbaops.approvals import ApprovalError
from dbaops.models import ApprovalStatus


async def test_wait_returns_human_decision(broker, store):
    a = broker.open("run1", "INC0012345", "build-config", "tool", {"confirm": True})
    waiter = asyncio.create_task(broker.wait(a.id, timeout=5))
    await asyncio.sleep(0)
    broker.decide(a.id, approve=True, approver="alice", comment="ok")
    result = await waiter
    assert result.status is ApprovalStatus.APPROVED
    assert result.approver == "alice"
    assert store.list_approvals("INC0012345")[0].status is ApprovalStatus.APPROVED


async def test_wait_expires(broker, store):
    a = broker.open("run1", "INC0012345", "build-config", "tool", {})
    result = await broker.wait(a.id, timeout=0.01)
    assert result.status is ApprovalStatus.EXPIRED
    with pytest.raises(ApprovalError):
        broker.decide(a.id, approve=True, approver="late")


async def test_cannot_decide_twice(broker):
    a = broker.open("run1", "INC0012345", "build-config", "tool", {})
    waiter = asyncio.create_task(broker.wait(a.id, timeout=5))
    await asyncio.sleep(0)
    broker.decide(a.id, approve=False, approver="bob")
    await waiter
    with pytest.raises(ApprovalError):
        broker.decide(a.id, approve=True, approver="bob")


async def test_decision_before_wait_is_not_lost(broker):
    a = broker.open("run1", "INC0012345", "build-config", "tool", {})
    broker.decide(a.id, approve=True, approver="fast")
    result = await broker.wait(a.id, timeout=1)
    assert result.status is ApprovalStatus.APPROVED
