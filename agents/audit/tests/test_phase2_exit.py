"""Phase 2 exit check: rules produce exceptions from procurement events."""
import uuid

from sqlalchemy import select

from agents.audit.demo.phase2_scenario import run_phase2_scenario
from agents.audit.models import AuditException, AuditSourceRecord
from agents.audit.rules.procurement_pack import PACK
from agents.audit.services.pack_seeder import activate_pack, seed_procurement_pack

AUTHOR, APPROVER = uuid.uuid4(), uuid.uuid4()
EXPECTED_HITS = {"PRC-APR-01", "PRC-SPL-01", "PRC-INVPO-01", "PRC-INVGRN-01",
                 "PRC-MATCH-01", "PRC-PAYINV-01", "PRC-VBANK-01"}


def hospital_with_active_pack(db):
    tenant = uuid.uuid4()
    seed_procurement_pack(db, tenant, created_by=AUTHOR)
    activate_pack(db, tenant, approved_by=APPROVER)
    return tenant


def test_scenario_triggers_expected_rules_once_each_then_nothing(db_session):
    tenant = hospital_with_active_pack(db_session)

    first = run_phase2_scenario(db_session, tenant)
    assert first == {rule["rule_code"]: (1 if rule["rule_code"] in EXPECTED_HITS else 0) for rule in PACK}

    second = run_phase2_scenario(db_session, tenant)
    assert second == {rule["rule_code"]: 0 for rule in PACK}


def test_clean_po_has_no_exceptions(db_session):
    tenant = hospital_with_active_pack(db_session)
    run_phase2_scenario(db_session, tenant)

    clean_po = db_session.scalar(select(AuditSourceRecord).where(
        AuditSourceRecord.tenant_id == tenant,
        AuditSourceRecord.entity_type == "purchase_order",
        AuditSourceRecord.snapshot["po_number"].astext == "PO-DEMO-6",
    ))
    assert clean_po is not None
    assert db_session.scalars(select(AuditException).where(
        AuditException.entity_id == clean_po.entity_id)).all() == []
