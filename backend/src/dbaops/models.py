from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ASSIGNMENT_GROUP = "DBopsv3"


class Ticket(BaseModel):
    """Incident or request payload pushed by the pipeline."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    number: str = Field(pattern=r"^[A-Z]{3,4}\d{4,12}$", examples=["INC0012345"])
    short_description: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=8000)
    # Target SQL Server instance, e.g. SQLPROD01, SQLPROD01\INST1, sqlprod01.corp.local,1433
    configuration_item: str = Field(pattern=r"^[A-Za-z0-9_.\-\\,]{1,255}$")
    assignment_group: Literal["DBopsv3"]
    priority: int = Field(default=4, ge=1, le=5)
    category: str | None = Field(default=None, max_length=100)


class TicketState(StrEnum):
    IN_PROGRESS = "In Progress"
    ON_HOLD = "On Hold"
    RESOLVED = "Resolved"
    ESCALATED = "Escalated"


class WorkNoteKind(StrEnum):
    PROGRESS = "progress"
    ACTION = "action"
    RESULT = "result"
    APPROVAL = "approval"
    RESOLUTION = "resolution"
    ERROR = "error"


class WorkNote(BaseModel):
    ticket_number: str
    kind: WorkNoteKind
    text: str
    agent: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RunStatus(StrEnum):
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    RESOLVED = "resolved"
    NEEDS_HUMAN = "needs_human"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"


ACTIVE_RUN_STATUSES = (RunStatus.RUNNING, RunStatus.AWAITING_APPROVAL)


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class Approval(BaseModel):
    id: str
    run_id: str
    ticket_number: str
    agent: str
    tool_name: str
    tool_input: dict[str, Any]
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None
    approver: str | None = None
    comment: str | None = None


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "deny"]
    approver: str = Field(min_length=1, max_length=100)
    comment: str = Field(default="", max_length=2000)
