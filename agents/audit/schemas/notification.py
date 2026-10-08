"""Response shape for in-app notifications."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    body: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    for_role: str | None = None            # set when the notification is for a role, not just this user
    read_at: datetime | None
    created_at: datetime
