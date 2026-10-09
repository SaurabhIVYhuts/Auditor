"""Request and response shapes for the corrective action API."""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from agents.audit.actions.state_machine import allowed_next as next_statuses
from agents.audit.schemas.case import EvidenceOut


class ActionCreate(BaseModel):
    """Missing description / owner / due date are reported together by the service (422)."""

    description: str | None = Field(default=None, max_length=5000)
    owner_user_id: uuid.UUID | None = None
    due_date: date | None = None
    owner_department_id: uuid.UUID | None = None
    required_evidence_type: str | None = Field(default=None, max_length=15)


class ActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action_number: str
    finding_id: uuid.UUID
    finding_number: str
    case_id: uuid.UUID
    case_number: str
    description: str
    owner_user_id: uuid.UUID
    owner_department_id: uuid.UUID | None
    due_date: date
    required_evidence_type: str | None
    status: str
    submitted_at: datetime | None
    verified_by: uuid.UUID | None
    verified_at: datetime | None
    verification_note: str | None
    return_note: str | None
    extension_count: int
    reminders_sent: list[str]
    closed_at: datetime | None
    created_by: uuid.UUID | None
    created_at: datetime

    @computed_field
    @property
    def allowed_next(self) -> list[str]:
        """Statuses the action may move to next (for buttons); the server still checks every move."""
        return [str(s) for s in next_statuses(self.status)]


class ActionDetailOut(ActionOut):
    evidence: list[EvidenceOut]


class VerifyIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
