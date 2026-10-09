"""Business numbers: PREFIX-<year>-<5 digits>, counting from 00001 per hospital, prefix and year.

AUD = cases (AUD-2026-00031), FND = findings (FND-2026-00007).
One atomic INSERT ... ON CONFLICT DO UPDATE ... RETURNING both creates the counter row (first
number of the year) and increments it. PostgreSQL locks the row while it does this, so two
records created at the same moment can never get the same number. Does NOT commit: the caller does.
"""
import uuid

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from agents.audit.models import AuditCaseCounter

CASE_PREFIX = "AUD"


def format_number(prefix: str, year: int, number: int) -> str:
    return f"{prefix}-{year}-{number:05d}"


def next_number(db: Session, tenant_id: uuid.UUID, prefix: str, year: int) -> str:
    counters = AuditCaseCounter.__table__
    stmt = (
        insert(counters)
        .values(id=uuid.uuid4(), tenant_id=tenant_id, prefix=prefix, year=year, last_number=1)
        .on_conflict_do_update(
            index_elements=[counters.c.tenant_id, counters.c.prefix, counters.c.year],
            set_={"last_number": counters.c.last_number + 1, "updated_at": func.now()},
        )
        .returning(counters.c.last_number)
    )
    return format_number(prefix, year, db.execute(stmt).scalar_one())


def next_case_number(db: Session, tenant_id: uuid.UUID, year: int) -> str:
    return next_number(db, tenant_id, CASE_PREFIX, year)
