"""Tests for the case tables and case numbering (AUD-020)."""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from agents.audit.cases.numbering import next_case_number
from agents.audit.models import AuditCase, AuditCaseException, AuditException
from agents.audit.services.snapshot_service import capture_snapshot


def test_numbers_start_at_00001_and_go_up(db_session):
    tenant = uuid.uuid4()
    assert next_case_number(db_session, tenant, 2026) == "AUD-2026-00001"
    assert next_case_number(db_session, tenant, 2026) == "AUD-2026-00002"


def test_each_hospital_and_each_year_starts_at_00001(db_session):
    hospital_a, hospital_b = uuid.uuid4(), uuid.uuid4()
    next_case_number(db_session, hospital_a, 2026)
    assert next_case_number(db_session, hospital_b, 2026) == "AUD-2026-00001"
    assert next_case_number(db_session, hospital_a, 2027) == "AUD-2027-00001"


def make_case(db, tenant, number="AUD-2026-00001"):
    case = AuditCase(tenant_id=tenant, case_number=number, domain="PROCUREMENT", title="Test case",
                     source="RULE", primary_entity_type="purchase_order", primary_entity_id=uuid.uuid4(),
                     priority="HIGH")
    db.add(case)
    db.flush()
    return case


def make_exception(db, tenant):
    snap = capture_snapshot(db, tenant_id=tenant, source_system="procurement", entity_type="purchase_order",
                            entity_id=uuid.uuid4(), data={"po_number": "PO-C1"})
    exc = AuditException(tenant_id=tenant, source="ANOMALY", anomaly_model="test", severity="HIGH",
                         entity_type="purchase_order", entity_id=snap.entity_id,
                         source_record_id=snap.id, details={}, dedup_key=f"test-{uuid.uuid4()}")
    db.add(exc)
    db.flush()
    return exc


def test_new_case_defaults(db_session):
    case = make_case(db_session, uuid.uuid4())
    db_session.refresh(case)
    assert (case.status, case.is_restricted) == ("OPEN", False)
    assert case.opened_at is not None and case.closed_at is None


def test_same_exception_cannot_join_two_cases(db_session):
    tenant = uuid.uuid4()
    exc = make_exception(db_session, tenant)
    first, second = make_case(db_session, tenant), make_case(db_session, tenant, "AUD-2026-00002")
    db_session.add(AuditCaseException(tenant_id=tenant, case_id=first.id, exception_id=exc.id))
    db_session.flush()
    db_session.add(AuditCaseException(tenant_id=tenant, case_id=second.id, exception_id=exc.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_case_number_is_unique_per_hospital_only(db_session):
    hospital_a, hospital_b = uuid.uuid4(), uuid.uuid4()
    make_case(db_session, hospital_a)
    make_case(db_session, hospital_b)                       # same number, other hospital: allowed
    with pytest.raises(IntegrityError):
        make_case(db_session, hospital_a)                   # same number, same hospital: refused
