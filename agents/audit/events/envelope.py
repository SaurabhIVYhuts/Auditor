"""Standard event envelope shared by all Konnective Tissue agents (architecture section 7).

Events carry IDs and minimal data only; the Auditor fetches full records itself.
Unknown extra fields are ignored, so producers can add fields without breaking us.
"""
import uuid
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class EventActor(BaseModel):
    type: Literal["user", "system", "ai"]
    id: uuid.UUID | None = None


class EventEntity(BaseModel):
    type: str = Field(min_length=1)
    id: uuid.UUID
    number: str | None = None  # human-readable number, e.g. PO-2026-00042


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: uuid.UUID
    event_type: str = Field(min_length=3)
    version: int = Field(ge=1)
    occurred_at: AwareDatetime          # must include a timezone
    tenant_id: uuid.UUID
    actor: EventActor
    entity: EventEntity
    data: dict[str, Any] = Field(default_factory=dict)
    correlation_id: uuid.UUID | None = None
