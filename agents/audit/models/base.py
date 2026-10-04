"""Parent class for every Auditor Agent table. All tables go in schema 'audit'."""
from sqlalchemy.orm import DeclarativeBase

from shared.models import make_metadata

AUDIT_SCHEMA = "audit"


class AuditBase(DeclarativeBase):
    metadata = make_metadata(AUDIT_SCHEMA)
