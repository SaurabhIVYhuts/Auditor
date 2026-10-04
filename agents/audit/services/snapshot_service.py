"""Snapshot service: saves frozen, tamper-evident copies of source records.

- The Auditor is read-only on source systems; it only stores copies here.
- Every snapshot gets a SHA-256 checksum, computed the same way everywhere,
  so any later change to the stored snapshot can be detected.
- This service does NOT commit. The caller decides when to commit, so related
  writes (snapshot + exception, later) succeed or fail together.
"""
import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from agents.audit.models import AuditSourceRecord

# Source systems listed in the architecture (evidence source_system values).
ALLOWED_SOURCE_SYSTEMS = frozenset({"procurement", "insurance", "erp", "his", "manual"})


def _normalise(data: dict[str, Any]) -> dict[str, Any]:
    """Return an independent copy using plain JSON types (dates/decimals become strings)."""
    return json.loads(json.dumps(data, default=str))


def compute_checksum(data: dict[str, Any]) -> str:
    """SHA-256 of the data in canonical form (sorted keys, no extra spaces)."""
    canonical = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def capture_snapshot(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    source_system: str,
    entity_type: str,
    entity_id: uuid.UUID,
    data: dict[str, Any],
    captured_by: uuid.UUID | None = None,
) -> AuditSourceRecord:
    """Store a frozen copy of one source record. Does not commit."""
    if source_system not in ALLOWED_SOURCE_SYSTEMS:
        raise ValueError(f"Unknown source_system: {source_system!r}")
    if not isinstance(data, dict) or not data:
        raise ValueError("Snapshot data must be a non-empty dictionary")

    snapshot = _normalise(data)
    record = AuditSourceRecord(
        tenant_id=tenant_id,
        source_system=source_system,
        entity_type=entity_type,
        entity_id=entity_id,
        snapshot=snapshot,
        checksum=compute_checksum(snapshot),
        created_by=captured_by,
    )
    db.add(record)
    db.flush()  # sends the INSERT inside the caller's transaction
    return record


def verify_snapshot(record: AuditSourceRecord) -> bool:
    """True if the stored snapshot still matches its checksum (not tampered)."""
    return compute_checksum(record.snapshot) == record.checksum
