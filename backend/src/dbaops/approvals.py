"""Human-in-the-loop: agent runs block on a future until a human approves or denies in the frontend."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from .models import Approval, ApprovalStatus
from .store import Store


class ApprovalError(Exception):
    pass


class ApprovalBroker:
    def __init__(self, store: Store):
        self._store = store
        self._undecided: dict[str, Approval] = {}
        self._futures: dict[str, asyncio.Future[Approval]] = {}

    def open(self, run_id: str, ticket_number: str, agent: str, tool_name: str, tool_input: dict[str, Any]) -> Approval:
        approval = Approval(
            id=uuid.uuid4().hex[:12],
            run_id=run_id,
            ticket_number=ticket_number,
            agent=agent,
            tool_name=tool_name,
            tool_input=tool_input,
        )
        self._undecided[approval.id] = approval
        self._futures[approval.id] = asyncio.get_running_loop().create_future()
        self._store.save_approval(approval)
        return approval

    async def wait(self, approval_id: str, timeout: float) -> Approval:
        future = self._futures[approval_id]
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout)
        except TimeoutError:
            return self._resolve(approval_id, ApprovalStatus.EXPIRED, None, "No decision before the approval timeout.")
        except asyncio.CancelledError:
            if approval_id in self._undecided:
                self._resolve(approval_id, ApprovalStatus.EXPIRED, None, "Agent run ended before a decision.")
            raise
        finally:
            self._futures.pop(approval_id, None)

    def decide(self, approval_id: str, approve: bool, approver: str, comment: str = "") -> Approval:
        status = ApprovalStatus.APPROVED if approve else ApprovalStatus.DENIED
        return self._resolve(approval_id, status, approver, comment)

    def _resolve(self, approval_id: str, status: ApprovalStatus, approver: str | None, comment: str) -> Approval:
        approval = self._undecided.pop(approval_id, None)
        if approval is None:
            raise ApprovalError(f"Approval {approval_id} is not pending")
        decided = approval.model_copy(
            update={"status": status, "approver": approver, "comment": comment, "decided_at": datetime.now(UTC)}
        )
        self._store.save_approval(decided)
        future = self._futures.get(approval_id)
        if future is not None and not future.done():
            future.set_result(decided)
        return decided
