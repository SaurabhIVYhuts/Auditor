"""Tests for the evidence service (AUD-030): capture, link, read, verify, supersede."""
import hashlib
import uuid

import pytest

from agents.audit.events.procurement_event_consumer import handle_procurement_event
from agents.audit.models import AuditSourceRecord
from agents.audit.services.case_service import list_cases, open_case
from agents.audit.services.evidence_service import (
    EvidenceIntegrityError, evidence_for, link_evidence, read_evidence, snapshot_evidence, supersede_evidence,
    upload_evidence, verify_evidence,
)
from agents.audit.services.snapshot_service import capture_snapshot
from agents.audit.tests.test_documents import PDF, temp_storage  # noqa: F401  (fixture: files go to tmp)
from agents.audit.tests.test_rule_engine import PoReader, add_rule, hospital, make_event
from shared.audit_log import list_for_entity
from shared.notifications import list_for_user

ACTOR = uuid.uuid4()


def upload(db, tenant=None, data=PDF):
    return upload_evidence(db, tenant or uuid.uuid4(), title="Signed approval email", filename="approval.pdf",
                           content_type="application/pdf", data=data, actor_id=ACTOR)


def a_case(db, tenant):
    return open_case(db, tenant, domain="PROCUREMENT", title="Test case", source="MANUAL",
                     primary_entity_type="purchase_order", primary_entity_id=uuid.uuid4(), priority="HIGH",
                     actor_id=ACTOR)


def evidence_log(db, evidence):
    return [row.action for row in list_for_entity(db, evidence.tenant_id, "audit_evidence", evidence.id)]


def test_upload_then_read_back_with_same_hash(db_session):
    evidence = upload(db_session)
    assert evidence.sha256 == hashlib.sha256(PDF).hexdigest() and evidence.status == "ACTIVE"
    assert read_evidence(db_session, evidence, ACTOR) == PDF
    assert verify_evidence(db_session, evidence, ACTOR) is True
    assert evidence_log(db_session, evidence) == ["evidence.uploaded", "evidence.viewed", "evidence.verified"]


def test_tampered_file_raises_alerts_audit_managers_and_is_logged(db_session, temp_storage):
    evidence = upload(db_session)
    (temp_storage / f"{evidence.tenant_id}/{evidence.document_id}").write_bytes(b"replaced content")
    with pytest.raises(EvidenceIntegrityError):
        read_evidence(db_session, evidence, ACTOR)
    assert "evidence.integrity_failed" in evidence_log(db_session, evidence)
    [note] = list_for_user(db_session, evidence.tenant_id, uuid.uuid4(), ["AM"])
    assert (note.kind, note.entity_id) == ("evidence.integrity_failed", evidence.id)
    assert verify_evidence(db_session, evidence, ACTOR) is False


def test_snapshot_evidence_matches_the_source_record(db_session):
    record = capture_snapshot(db_session, tenant_id=uuid.uuid4(), source_system="procurement",
                              entity_type="purchase_order", entity_id=uuid.uuid4(),
                              data={"po_number": "PO-E1", "grand_total": 200000})
    evidence = snapshot_evidence(db_session, record, "PO snapshot")
    assert (evidence.snapshot, evidence.sha256) == (record.snapshot, record.checksum)
    assert evidence.source_ref["source_record_id"] == str(record.id)
    assert read_evidence(db_session, evidence, ACTOR) == record.snapshot


def test_tampered_source_record_cannot_become_evidence(db_session):
    record = capture_snapshot(db_session, tenant_id=uuid.uuid4(), source_system="procurement",
                              entity_type="purchase_order", entity_id=uuid.uuid4(), data={"grand_total": 1})
    record.snapshot = {"grand_total": 2}
    with pytest.raises(EvidenceIntegrityError):
        snapshot_evidence(db_session, record, "PO snapshot")


def test_link_to_case_twice_returns_the_same_link(db_session):
    evidence = upload(db_session)
    case = a_case(db_session, evidence.tenant_id)
    first = link_evidence(db_session, evidence, "CASE", case.id, ACTOR)
    second = link_evidence(db_session, evidence, "CASE", case.id, ACTOR)
    assert first.id == second.id
    assert evidence_for(db_session, evidence.tenant_id, "CASE", case.id) == [evidence]
    assert evidence_log(db_session, evidence).count("evidence.linked") == 1


def test_other_hospitals_case_is_refused(db_session):
    evidence = upload(db_session)
    other_case = a_case(db_session, uuid.uuid4())
    with pytest.raises(ValueError):
        link_evidence(db_session, evidence, "CASE", other_case.id, ACTOR)


def test_unknown_action_is_refused(db_session):
    evidence = upload(db_session)
    with pytest.raises(ValueError, match="Action not found"):
        link_evidence(db_session, evidence, "ACTION", uuid.uuid4(), ACTOR)


def test_superseded_evidence_cannot_be_linked(db_session):
    evidence = upload(db_session)
    supersede_evidence(db_session, evidence, "Wrong file uploaded", ACTOR, ["AUD"])
    assert (evidence.status, evidence.superseded_reason) == ("SUPERSEDED", "Wrong file uploaded")
    with pytest.raises(ValueError):
        link_evidence(db_session, evidence, "CASE", a_case(db_session, evidence.tenant_id).id, ACTOR)


def test_supersede_needs_a_reason_and_records_the_replacement(db_session):
    old, new = upload(db_session), None
    with pytest.raises(ValueError):
        supersede_evidence(db_session, old, "   ", ACTOR, ["AUD"])
    new = upload_evidence(db_session, old.tenant_id, title="Corrected approval", filename="approval2.pdf",
                          content_type="application/pdf", data=PDF + b"2", actor_id=ACTOR)
    supersede_evidence(db_session, old, "Corrected copy received", ACTOR, ["AUD"], replaced_by=new)
    assert old.superseded_by == new.id


def test_event_to_case_links_one_snapshot_evidence(db_session):
    tenant = hospital(db_session)
    add_rule(db_session, tenant)
    result = handle_procurement_event(db_session, make_event(tenant), PoReader())
    [case] = list_cases(db_session, tenant)
    [evidence] = evidence_for(db_session, tenant, "CASE", case.id)
    record = db_session.get(AuditSourceRecord, result.source_record_id)
    assert (evidence.snapshot, evidence.sha256, evidence.captured_by) == (record.snapshot, record.checksum, None)
    assert verify_evidence(db_session, evidence, None) is True
