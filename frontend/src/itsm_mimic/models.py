from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AGENT_GROUP = "DBopsv3"
ASSIGNMENT_GROUPS = [AGENT_GROUP, "DBA Team", "Windows Server", "Network"]
STATES = ["New", "In Progress", "On Hold", "Resolved", "Closed", "Escalated"]
CATEGORIES = ["Database", "Performance", "Backup", "Security", "Inquiry"]
NUMBER_PATTERN = r"^INC\d{7}$"
APPROVAL_ID_PATTERN = r"^[a-f0-9]{12}$"

State = Literal["New", "In Progress", "On Hold", "Resolved", "Closed", "Escalated"]
Group = Literal["DBopsv3", "DBA Team", "Windows Server", "Network"]


class IncidentIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    short_description: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=8000)
    configuration_item: str = Field(pattern=r"^[A-Za-z0-9_.\-\\,]{1,255}$")
    assignment_group: Group
    priority: int = Field(default=4, ge=1, le=5)
    category: str | None = Field(default=None, max_length=100)


class IncidentUpdate(BaseModel):
    assignment_group: Group
    state: State
    priority: int = Field(ge=1, le=5)


class AgentWorkNote(BaseModel):
    """Work note as posted by the DBopsv3 backend."""

    kind: str = Field(max_length=30)
    text: str = Field(min_length=1, max_length=20000)
    agent: str | None = Field(default=None, max_length=50)
    created_at: datetime | None = None


class StatePatch(BaseModel):
    state: State
