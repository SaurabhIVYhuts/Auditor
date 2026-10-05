"""Tests for the procurement trail builder (AUD-005)."""
import uuid

from agents.audit.services.snapshot_service import capture_snapshot
from agents.audit.services.trail_service import get_po_chain, get_record_history


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def save(db, tenant_id, entity_type, data, entity_id=None):
    return capture_snapshot(
        db,
        tenant_id=tenant_id,
        source_system="procurement",
        entity_type=entity_type,
        entity_id=entity_id or uuid.uuid4(),
        data=data,
    )


def test_po_chain_links_documents_in_p2p_order(db_session):
    tenant = uuid.uuid4()
    po, inv = unique("PO"), unique("INV")
    # Saved in mixed order on purpose; the chain must still come back in P2P order.
    save(db_session, tenant, "payment", {"payment_ref": unique("PAY"), "invoice_number": inv, "amount": 100})
    save(db_session, tenant, "invoice", {"invoice_number": inv, "po_number": po, "amount": 100})
    save(db_session, tenant, "grn", {"grn_number": unique("GRN"), "po_number": po})
    save(db_session, tenant, "purchase_order", {"po_number": po, "grand_total": 100})
    save(db_session, tenant, "grn", {"grn_number": unique("GRN"), "po_number": unique("PO")})  # other PO

    chain = get_po_chain(db_session, tenant_id=tenant, po_number=po)

    assert [e.entity_type for e in chain] == ["purchase_order", "grn", "invoice", "payment"]
    assert all(e.checksum_ok for e in chain)


def test_po_chain_never_shows_another_tenants_data(db_session):
    my_tenant, other_tenant = uuid.uuid4(), uuid.uuid4()
    po = unique("PO")
    save(db_session, my_tenant, "purchase_order", {"po_number": po, "grand_total": 100})
    save(db_session, other_tenant, "grn", {"grn_number": unique("GRN"), "po_number": po})

    chain = get_po_chain(db_session, tenant_id=my_tenant, po_number=po)

    assert [e.entity_type for e in chain] == ["purchase_order"]


def test_unknown_po_gives_empty_chain(db_session):
    assert get_po_chain(db_session, tenant_id=uuid.uuid4(), po_number=unique("PO")) == []


def test_record_history_returns_every_snapshot_of_one_record(db_session):
    tenant, po_id = uuid.uuid4(), uuid.uuid4()
    po = unique("PO")
    save(db_session, tenant, "purchase_order", {"po_number": po, "grand_total": 100}, entity_id=po_id)
    save(db_session, tenant, "purchase_order", {"po_number": po, "grand_total": 120}, entity_id=po_id)  # amended
    save(db_session, tenant, "purchase_order", {"po_number": unique("PO"), "grand_total": 5})        # other PO

    history = get_record_history(
        db_session, tenant_id=tenant, entity_type="purchase_order", entity_id=po_id
    )

    assert sorted(e.snapshot["grand_total"] for e in history) == [100, 120]


def test_tampered_snapshot_is_flagged_in_the_trail(db_session):
    tenant = uuid.uuid4()
    po = unique("PO")
    record = save(db_session, tenant, "purchase_order", {"po_number": po, "grand_total": 100})
    record.snapshot = {**record.snapshot, "grand_total": 1}  # simulate tampering

    chain = get_po_chain(db_session, tenant_id=tenant, po_number=po)

    assert chain[0].checksum_ok is False
