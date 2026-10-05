"""Response shapes for the trail endpoints."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class TrailEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_record_id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    captured_at: datetime
    checksum_ok: bool
    snapshot: dict[str, Any]
