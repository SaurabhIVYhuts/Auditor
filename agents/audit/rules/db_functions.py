"""Database functions for rules (AUD-011): duplicate_of and sum_over_window.

They compare the record being checked with OTHER records in the Audit Data Hub
(read-only, same hospital only). make_db_functions() builds them for one record and
they are given to the evaluator through EvaluationContext.functions.
Only the latest snapshot of each other record counts. The time window currently uses
captured_at (when the snapshot was taken), not the document's own date.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.audit.models import AuditSourceRecord
from agents.audit.rules import dsl_spec as spec
from agents.audit.rules.evaluator import _MISSING, EvaluationContext, _as_number, _read_field


def _latest_per_entity(rows: list[AuditSourceRecord]) -> list[AuditSourceRecord]:
    latest: dict[uuid.UUID, AuditSourceRecord] = {}
    for row in rows:
        current = latest.get(row.entity_id)
        if current is None or row.captured_at > current.captured_at:
            latest[row.entity_id] = row
    return list(latest.values())


def _matches(snapshot: dict[str, Any], wanted: dict[str, Any]) -> bool:
    return all(name in snapshot and _as_number(snapshot[name]) == _as_number(value)
               for name, value in wanted.items())


def _other_latest(
    db: Session, *, tenant_id: uuid.UUID, current_entity_id: uuid.UUID, prefix: str,
    window_days: int, as_of: datetime, wanted: dict[str, Any],
) -> list[AuditSourceRecord]:
    """Latest snapshot of every OTHER record of this type that matches `wanted` in the window."""
    same_scope = (
        AuditSourceRecord.tenant_id == tenant_id,
        AuditSourceRecord.source_system == "procurement",
        AuditSourceRecord.entity_type == spec.ENTITY_TYPES[prefix],
        AuditSourceRecord.entity_id != current_entity_id,
        AuditSourceRecord.is_deleted.is_(False),
    )
    since = as_of - timedelta(days=window_days)
    in_window = AuditSourceRecord.captured_at >= since   # safe: a record's latest version is its newest
    # Pre-filter in PostgreSQL only on plain text values (e.g. vendor_id). Numbers, and numbers
    # written as text, are compared in Python (_matches), so 150000 and "150000" count as equal.
    text_only = {k: v for k, v in wanted.items() if isinstance(v, str) and _as_number(v) == v}
    candidates = select(AuditSourceRecord.entity_id).where(*same_scope, in_window)
    if text_only:
        candidates = candidates.where(AuditSourceRecord.snapshot.contains(text_only))
    rows = db.scalars(
        select(AuditSourceRecord).where(*same_scope, in_window, AuditSourceRecord.entity_id.in_(candidates))
    ).all()
    return [r for r in _latest_per_entity(rows)
            if r.captured_at >= since and _matches(r.snapshot, wanted)]


def make_db_functions(
    db: Session, *, tenant_id: uuid.UUID, current_entity_id: uuid.UUID,
    as_of: datetime | None = None,
) -> dict[str, Callable[[EvaluationContext, dict[str, Any]], Any]]:
    """Build duplicate_of and sum_over_window for the one record being checked."""
    as_of = as_of or datetime.now(timezone.utc)

    def duplicate_of(ctx: EvaluationContext, args: dict[str, Any]) -> Any:
        """True if ANOTHER record of the same type has the same values in the window."""
        prefix = args["entity"]
        wanted: dict[str, Any] = {}
        for ref in args["match_fields"]:
            ref_prefix, name = ref.split(".", 1)
            if ref_prefix != prefix:
                raise ValueError("match_fields must belong to the same entity")
            value = _read_field(ctx, ref)
            if value is _MISSING:
                return _MISSING
            wanted[name] = value
        others = _other_latest(
            db, tenant_id=tenant_id, current_entity_id=current_entity_id, prefix=prefix,
            window_days=args["window_days"], as_of=as_of, wanted=wanted,
        )
        return len(others) > 0

    def sum_over_window(ctx: EvaluationContext, args: dict[str, Any]) -> Any:
        """This record's value plus the same field of other records in the same group and window."""
        prefix, name = args["field"].split(".", 1)
        group_prefix, group_name = args["group_by"].split(".", 1)
        if group_prefix != prefix:
            raise ValueError("field and group_by must belong to the same entity")
        own_value = _read_field(ctx, args["field"])
        group_value = _read_field(ctx, args["group_by"])
        if own_value is _MISSING or group_value is _MISSING:
            return _MISSING
        total = float(_as_number(own_value))
        others = _other_latest(
            db, tenant_id=tenant_id, current_entity_id=current_entity_id, prefix=prefix,
            window_days=args["window_days"], as_of=as_of, wanted={group_name: group_value},
        )
        for record in others:
            value = _as_number(record.snapshot.get(name))
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                total += value
        return total

    return {"duplicate_of": duplicate_of, "sum_over_window": sum_over_window}
