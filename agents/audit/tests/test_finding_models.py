"""Tests for the finding table and FND numbering (AUD-031)."""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from agents.audit.cases.numbering import next_case_number, next_number
from agents.audit.models import AuditFinding
from agents.audit.services.case_service import open_case


def a_case(db, tenant):
    return open_case(db, tenant, domain="PROCUREMENT", title="Test case", source="MANUAL",
                     primary_entity_type="purchase_order", primary_entity_id=uuid.uuid4(), priority="HIGH",
                     actor_id=None)


def test_finding_and_case_numbers_count_separately(db_session):
    tenant = uuid.uuid4()
    assert next_number(db_session, tenant, "FND", 2026) == "FND-2026-00001"
    assert next_case_number(db_session, tenant, 2026) == "AUD-2026-00001"
    assert next_number(db_session, tenant, "FND", 2026) == "FND-2026-00002"
    assert next_case_number(db_session, tenant, 2026) == "AUD-2026-00002"


def finding(db, case, number="FND-2026-00001", **fields):
    item = AuditFinding(tenant_id=case.tenant_id, finding_number=number, case_id=case.id,
                        title="High-value PO approved without level-2 approval", **fields)
    db.add(item)
    db.flush()
    return item


def test_new_finding_defaults(db_session):
    item = finding(db_session, a_case(db_session, uuid.uuid4()))
    db_session.refresh(item)
    assert (item.status, item.ai_drafted_fields, item.risk_level, item.due_date) == ("DRAFT", [], None, None)


def test_finding_number_is_unique_per_hospital(db_session):
    case = a_case(db_session, uuid.uuid4())
    finding(db_session, case)
    with pytest.raises(IntegrityError):
        finding(db_session, case)


def test_unknown_risk_level_is_refused(db_session):
    with pytest.raises(IntegrityError):
        finding(db_session, a_case(db_session, uuid.uuid4()), risk_level="EXTREME")
