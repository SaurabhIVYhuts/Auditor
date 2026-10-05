"""Phase 1 exit check: send mock procurement events through the real consumer.

Run:  .venv\\Scripts\\python -m scripts.seed_mock_procurement_events
Development only. Uses fixed IDs, so running it a second time reports
"duplicate" for every event (proves idempotency) and adds nothing.
"""
import uuid

from agents.audit.events.envelope import EventEnvelope
from agents.audit.events.procurement_event_consumer import handle_procurement_event
from agents.audit.events.procurement_reader import MockProcurementReader
from shared.config import settings
from shared.db import SessionLocal

DEMO_TENANT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
_DEMO_NAMESPACE = uuid.UUID("6f1d2c1e-0000-4000-8000-000000000001")  # for repeatable IDs

DEMO_EVENTS = [
    ("procurement.po.approved", "purchase_order"),
    ("procurement.grn.posted", "grn"),
    ("procurement.invoice.matched", "invoice"),
    ("procurement.payment.status_changed", "payment"),
]


def _demo_id(name: str) -> uuid.UUID:
    return uuid.uuid5(_DEMO_NAMESPACE, name)


def build_event(event_type: str, entity_type: str) -> EventEnvelope:
    return EventEnvelope.model_validate({
        "event_id": str(_demo_id(f"event:{event_type}")),
        "event_type": event_type,
        "version": 1,
        "occurred_at": "2026-10-05T10:00:00+05:30",
        "tenant_id": str(DEMO_TENANT_ID),
        "actor": {"type": "system"},
        "entity": {"type": entity_type, "id": str(_demo_id(f"entity:{entity_type}"))},
    })


def main() -> None:
    if settings.environment not in {"development", "test"}:
        raise SystemExit("Refusing to load mock data: ENVIRONMENT is not development or test.")

    reader = MockProcurementReader()
    db = SessionLocal()
    try:
        for event_type, entity_type in DEMO_EVENTS:
            result = handle_procurement_event(db, build_event(event_type, entity_type), reader)
            print(f"{event_type:40} -> {result.status}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(f"Demo tenant: {DEMO_TENANT_ID}   PO chain to view: PO-MOCK-00001")


if __name__ == "__main__":
    main()
