"""Shared database building blocks used by every agent's tables.

Architecture convention: every business table has a UUID primary key plus
tenant_id, created_at, created_by, updated_at, updated_by and is_deleted.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, false, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Predictable names for indexes and constraints, so migrations stay stable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def make_metadata(schema: str) -> MetaData:
    """MetaData for one agent's schema (e.g. 'audit')."""
    return MetaData(schema=schema, naming_convention=NAMING_CONVENTION)


class SharedBase(DeclarativeBase):
    """Base for placeholder platform tables (audit_logs, notifications).

    Kept separate from agent bases so shared/ never imports agents/. Lives in the "audit"
    schema for now; the platform versions will live in their own schema.
    """

    metadata = make_metadata("audit")


class CommonColumns:
    """Columns every business table must have. Add this as a parent class."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by: Mapped[uuid.UUID | None]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[uuid.UUID | None]
    # Soft delete: rows are never physically removed, so audit history is kept.
    is_deleted: Mapped[bool] = mapped_column(default=False, server_default=false())
