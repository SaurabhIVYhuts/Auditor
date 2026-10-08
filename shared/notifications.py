"""In-app notifications: short messages for one user or for everyone with a role.

Placeholder until the platform notification service exists; keep the function signatures.
When the platform service is available, replace the bodies of these functions with calls
to it; callers do not change.

Messages carry a title, a short body and a link target (entity_type + entity_id), never
evidence content. Wording is neutral. Functions flush, they never commit.
"""
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, Identity, Index, String, Text, func, or_, select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from shared.models import SharedBase


class Notification(SharedBase):
    __tablename__ = "notifications"
    __table_args__ = (
        # Exactly one recipient: one user, or everyone with one role.
        CheckConstraint("(recipient_id IS NULL) <> (recipient_role IS NULL)", name="one_recipient"),
        Index("ix_notifications_user", "tenant_id", "recipient_id"),
        Index("ix_notifications_role", "tenant_id", "recipient_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Insertion order (timestamps can tie inside one transaction), used for "newest first".
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    tenant_id: Mapped[uuid.UUID]
    recipient_id: Mapped[uuid.UUID | None]
    recipient_role: Mapped[str | None] = mapped_column(String(10))   # e.g. "AM"
    kind: Mapped[str] = mapped_column(String(60))                    # e.g. "case.assigned"
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(String(60))      # what the notification links to
    entity_id: Mapped[uuid.UUID | None]
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def _add(db: Session, **fields) -> Notification:
    notification = Notification(**fields)
    db.add(notification)
    db.flush()
    return notification


def notify_user(
    db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, kind: str, title: str, body: str,
    entity_type: str | None = None, entity_id: uuid.UUID | None = None,
) -> Notification:
    """Notify one user."""
    return _add(db, tenant_id=tenant_id, recipient_id=user_id, kind=kind, title=title, body=body,
                entity_type=entity_type, entity_id=entity_id)


def notify_role(
    db: Session, tenant_id: uuid.UUID, role: str, kind: str, title: str, body: str,
    entity_type: str | None = None, entity_id: uuid.UUID | None = None,
) -> Notification:
    """Notify everyone in this hospital who has the role (one shared notification)."""
    return _add(db, tenant_id=tenant_id, recipient_role=role, kind=kind, title=title, body=body,
                entity_type=entity_type, entity_id=entity_id)


def _visible_to(tenant_id: uuid.UUID, user_id: uuid.UUID, roles: Iterable[str]):
    return (Notification.tenant_id == tenant_id) & or_(
        Notification.recipient_id == user_id,
        Notification.recipient_role.in_(sorted(roles)),
    )


def list_for_user(
    db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, roles: Iterable[str], unread_only: bool = False,
) -> list[Notification]:
    """The user's own notifications plus those for their roles, newest first."""
    stmt = select(Notification).where(_visible_to(tenant_id, user_id, roles))
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return list(db.scalars(stmt.order_by(Notification.seq.desc())))


def mark_read(
    db: Session, tenant_id: uuid.UUID, notification_id: uuid.UUID, user_id: uuid.UUID, roles: Iterable[str],
) -> Notification | None:
    """Mark one of the user's notifications as read. None if it is not theirs (or does not exist).

    A role notification is shared, so reading it marks it read for everyone in that role.
    """
    notification = db.scalar(select(Notification).where(
        Notification.id == notification_id, _visible_to(tenant_id, user_id, roles),
    ))
    if notification is None:
        return None
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        db.flush()
    return notification
