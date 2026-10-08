"""Case numbers (AUD-020): AUD-<year>-<5 digits>, counting from 00001 per hospital and per year.

One atomic INSERT ... ON CONFLICT DO UPDATE ... RETURNING both creates the counter row (first
case of the year) and increments it. PostgreSQL locks the row while it does this, so two cases
created at the same moment can never get the same number. Does NOT commit: the caller does.
"""
import uuid

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from agents.audit.models import AuditCaseCounter


def format_case_number(year: int, number: int) -> str:
    return f"AUD-{year}-{number:05d}"


def next_case_number(db: Session, tenant_id: uuid.UUID, year: int) -> str:
    counters = AuditCaseCounter.__table__
    stmt = (
        insert(counters)
        .values(id=uuid.uuid4(), tenant_id=tenant_id, year=year, last_number=1)
        .on_conflict_do_update(
            index_elements=[counters.c.tenant_id, counters.c.year],
            set_={"last_number": counters.c.last_number + 1, "updated_at": func.now()},
        )
        .returning(counters.c.last_number)
    )
    number = db.execute(stmt).scalar_one()
    return format_case_number(year, number)
