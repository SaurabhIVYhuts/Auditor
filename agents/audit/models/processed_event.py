"""Register of events the Auditor has already handled (idempotency).

Events can be delivered more than once (retries, restarts). Before handling an
event we check this table; the UNIQUE event_id makes a second copy harmless.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from agents.audit.models.base import AuditBase
from shared.models import CommonColumns


class AuditProcessedEvent(CommonColumns, AuditBase):
    __tablename__ = "audit_processed_events"

    event_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    event_type: Mapped[str] = mapped_column(String(100))
    correlation_id: Mapped[uuid.UUID | None]
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("audit.audit_source_records.id")
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
