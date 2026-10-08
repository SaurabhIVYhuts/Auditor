"""Append-only audit log: who did what, to which record, when.

Placeholder until the platform audit_logs service exists; keep the function signature.
When the platform service is available, replace the body of log_action / list_for_entity
with calls to it; callers do not change.

Append-only: there are deliberately NO update or delete functions. Rows are only added.
Lives in the "audit" schema for now (the platform version will live in its own schema).
"""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Index, String, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from shared.models import SharedBase


class AuditLog(SharedBase):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_entity", "tenant_id", "entity_type", "entity_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Insertion order. Timestamps can tie inside one transaction, so ordering uses this instead.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    tenant_id: Mapped[uuid.UUID]
    actor_id: Mapped[uuid.UUID | None]                      # None = done by the system
    action: Mapped[str] = mapped_column(String(60))         # e.g. "rule.activated", "case.assigned"
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[uuid.UUID]
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def log_action(
    db: Session, tenant_id: uuid.UUID, actor_id: uuid.UUID | None, action: str,
    entity_type: str, entity_id: uuid.UUID, details: dict[str, Any] | None = None,
) -> AuditLog:
    """Add one audit log row. Flushes, does NOT commit: it is saved with the caller's change."""
    row = AuditLog(tenant_id=tenant_id, actor_id=actor_id, action=action,
                   entity_type=entity_type, entity_id=entity_id, details=details or {})
    db.add(row)
    db.flush()
    return row


def list_for_entity(
    db: Session, tenant_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID,
) -> list[AuditLog]:
    """All log rows for one record of one hospital, oldest first."""
    return list(db.scalars(
        select(AuditLog).where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_id,
        ).order_by(AuditLog.seq)
    ))
