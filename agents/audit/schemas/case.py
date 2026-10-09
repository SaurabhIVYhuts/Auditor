"""Request and response shapes for the case API."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from agents.audit.cases.state_machine import allowed_next as next_statuses


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_number: str
    domain: str
    title: str
    source: str
    status: str
    priority: str
    primary_entity_type: str
    primary_entity_id: uuid.UUID
    department_id: uuid.UUID | None
    assigned_to: uuid.UUID | None
    is_restricted: bool
    closure_reason: str | None
    opened_at: datetime
    closed_at: datetime | None

    @computed_field
    @property
    def allowed_next(self) -> list[str]:
        """Statuses the case may move to next (for buttons); the server still checks every move."""
        return [str(status) for status in next_statuses(self.status)]


class CaseExceptionOut(BaseModel):
    id: uuid.UUID
    rule_code: str | None                  # None for exceptions not made by a rule (anomalies, later)
    severity: str
    entity_type: str
    entity_id: uuid.UUID
    created_at: datetime


class CaseDetailOut(CaseOut):
    ai_summary: str | None
    exceptions: list[CaseExceptionOut]


class ManualCaseCreate(BaseModel):
    domain: str
    title: str = Field(min_length=3, max_length=200)
    priority: str
    primary_entity_type: str = Field(min_length=1, max_length=60)
    primary_entity_id: uuid.UUID
    department_id: uuid.UUID | None = None


class AssignIn(BaseModel):
    assignee_id: uuid.UUID


class StatusIn(BaseModel):
    status: str
    reason: str | None = Field(default=None, max_length=2000)


class CloseIn(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class CommentIn(BaseModel):
    body: str = Field(max_length=5000)


class CaseUpdate(BaseModel):
    """Only the fields sent are changed. Sending department_id: null clears the department."""

    title: str | None = Field(default=None, min_length=3, max_length=200)
    priority: str | None = None
    is_restricted: bool | None = None
    department_id: uuid.UUID | None = None


class EvidenceOut(BaseModel):
    id: uuid.UUID
    title: str
    evidence_type: str
    source_system: str
    sha256: str
    status: str
    superseded_reason: str | None
    contains_phi: bool
    captured_by: uuid.UUID | None
    captured_at: datetime
    filename: str | None          # set for uploaded documents
    is_snapshot: bool             # True for frozen copies of system records


class SupersedeIn(BaseModel):
    reason: str = Field(max_length=2000)
    replaced_by: uuid.UUID | None = None


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    author_id: uuid.UUID
    body: str
    created_at: datetime


class TimelineEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    action: str
    actor_id: uuid.UUID | None
    details: dict[str, Any]
    created_at: datetime
