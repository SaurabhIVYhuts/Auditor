"""Request and response shapes for the finding API."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from agents.audit.findings.state_machine import allowed_next as next_statuses
from agents.audit.schemas.case import EvidenceOut


class FindingFields(BaseModel):
    """The editable parts of a finding; only the fields that are sent are applied."""

    condition: str | None = Field(default=None, max_length=10000)
    criteria: str | None = Field(default=None, max_length=10000)
    cause: str | None = Field(default=None, max_length=10000)
    effect: str | None = Field(default=None, max_length=10000)
    recommendation: str | None = Field(default=None, max_length=10000)
    financial_impact: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    risk_level: str | None = None
    owner_user_id: uuid.UUID | None = None
    owner_department_id: uuid.UUID | None = None
    due_date: date | None = None


class FindingCreate(FindingFields):
    title: str = Field(min_length=3, max_length=200)


class FindingUpdate(FindingFields):
    title: str | None = Field(default=None, min_length=3, max_length=200)


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    finding_number: str
    case_id: uuid.UUID
    case_number: str
    title: str
    condition: str | None
    criteria: str | None
    cause: str | None
    effect: str | None
    recommendation: str | None
    financial_impact: Decimal | None
    risk_level: str | None
    owner_user_id: uuid.UUID | None
    owner_department_id: uuid.UUID | None
    due_date: date | None
    status: str
    management_response: str | None
    ai_drafted_fields: list[str]
    dismiss_reason: str | None
    created_by: uuid.UUID | None
    created_at: datetime
    submitted_by: uuid.UUID | None
    submitted_at: datetime | None
    confirmed_by: uuid.UUID | None
    confirmed_at: datetime | None

    @computed_field
    @property
    def allowed_next(self) -> list[str]:
        """Statuses the finding may move to next (for buttons); the server still checks every move."""
        return [str(s) for s in next_statuses(self.status)]


class FindingDetailOut(FindingOut):
    evidence: list[EvidenceOut]                 # empty for users without evidence:read (e.g. auditees)


class ConfirmIn(BaseModel):
    owner_user_id: uuid.UUID | None = None
    due_date: date | None = None


class NoteIn(BaseModel):
    note: str = Field(max_length=2000)


class ReasonIn(BaseModel):
    reason: str = Field(max_length=2000)


class EvidenceLinkIn(BaseModel):
    evidence_id: uuid.UUID
