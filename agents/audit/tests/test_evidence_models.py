"""Tests for the evidence tables (AUD-030)."""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from agents.audit.models import AuditEvidence, AuditEvidenceLink
from agents.audit.tests.test_documents import store, temp_storage  # noqa: F401  (fixture: files go to tmp)

HASH = "0" * 64


def evidence(db, tenant, **fields):
    values = {"title": "Purchase order PO-1", "evidence_type": "TRANSACTION",
              "source_system": "procurement", "sha256": HASH, **fields}
    item = AuditEvidence(tenant_id=tenant, **values)
    db.add(item)
    db.flush()
    return item


def test_document_evidence_is_saved(db_session):
    doc = store(db_session)
    item = evidence(db_session, doc.tenant_id, document_id=doc.id, evidence_type="DOCUMENT")
    assert item.document_id == doc.id and item.snapshot is None


def test_snapshot_evidence_gets_defaults(db_session):
    item = evidence(db_session, uuid.uuid4(), snapshot={"po_number": "PO-1", "grand_total": 200000})
    db_session.refresh(item)
    assert (item.status, item.contains_phi) == ("ACTIVE", False)
    assert item.captured_at is not None


@pytest.mark.parametrize("both", [True, False], ids=["both", "neither"])
def test_exactly_one_of_document_or_snapshot(db_session, both):
    tenant = uuid.uuid4()
    fields = {}
    if both:
        fields = {"document_id": store(db_session, tenant).id, "snapshot": {"po_number": "PO-1"}}
    with pytest.raises(IntegrityError):
        evidence(db_session, tenant, **fields)


def test_unknown_evidence_type_is_refused(db_session):
    with pytest.raises(IntegrityError):
        evidence(db_session, uuid.uuid4(), snapshot={"a": 1}, evidence_type="RUMOUR")


def test_same_link_twice_is_refused(db_session):
    tenant, case_id = uuid.uuid4(), uuid.uuid4()
    item = evidence(db_session, tenant, snapshot={"po_number": "PO-1"})
    db_session.add(AuditEvidenceLink(tenant_id=tenant, evidence_id=item.id, target_type="CASE", target_id=case_id))
    db_session.flush()
    db_session.add(AuditEvidenceLink(tenant_id=tenant, evidence_id=item.id, target_type="CASE", target_id=case_id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_one_item_can_link_to_several_targets(db_session):
    tenant = uuid.uuid4()
    item = evidence(db_session, tenant, snapshot={"po_number": "PO-1"})
    for target_type in ("CASE", "FINDING", "ACTION"):
        db_session.add(AuditEvidenceLink(tenant_id=tenant, evidence_id=item.id, target_type=target_type,
                                         target_id=uuid.uuid4()))
    db_session.flush()
