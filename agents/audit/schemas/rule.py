"""Request and response shapes for the rule API."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

RULE_CODE_PATTERN = r"^[A-Z]{2,5}-[A-Z0-9]{2,6}-\d{2,3}$"   # DOMAIN-TOPIC-NN, e.g. PRC-APR-01


class RuleCreate(BaseModel):
    rule_code: str = Field(pattern=RULE_CODE_PATTERN)
    name: str = Field(min_length=3, max_length=200)
    description: str | None = None
    domain: str
    severity: str
    definition: dict[str, Any]


class RuleUpdate(BaseModel):
    definition: dict[str, Any]
    severity: str | None = None
    change_note: str | None = Field(default=None, max_length=500)


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_code: str
    name: str
    description: str | None
    domain: str
    severity: str
    status: str
    current_version: int
    definition: dict[str, Any]
    department_scope: list[uuid.UUID] | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None


class RuleRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_version: int
    trigger_type: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    records_checked: int
    exceptions_created: int
    duplicates_skipped: int
    warnings: list[str]
    error: str | None
