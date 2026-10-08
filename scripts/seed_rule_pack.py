"""Development: seed the procurement rule pack into the demo hospital and activate it.

Run:  .venv\\Scripts\\python -m scripts.seed_rule_pack
Development/test only. Safe to run again: existing rules are kept, ACTIVE rules are skipped.
"""
import sys
import uuid

from sqlalchemy import select

from agents.audit.models import AuditRule, RuleStatus
from agents.audit.rules.procurement_pack import PACK
from agents.audit.services.pack_seeder import seed_procurement_pack
from agents.audit.services.rule_registry import activate_rule
from shared.config import settings
from shared.db import SessionLocal

DEMO_TENANT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
# Two different dev users, so maker-checker allows activating HIGH/CRITICAL rules.
AUTHOR_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
APPROVER_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


def main() -> None:
    if settings.environment not in {"development", "test"}:
        print("Refusing to seed rules: ENVIRONMENT is not development or test.")
        sys.exit(1)

    pack_codes = {rule["rule_code"] for rule in PACK}
    db = SessionLocal()
    try:
        result = seed_procurement_pack(db, DEMO_TENANT_ID, created_by=AUTHOR_ID)
        drafts = db.scalars(select(AuditRule).where(
            AuditRule.tenant_id == DEMO_TENANT_ID,
            AuditRule.rule_code.in_(sorted(pack_codes)),
            AuditRule.status == RuleStatus.DRAFT.value,
            AuditRule.is_deleted.is_(False),
        ).order_by(AuditRule.rule_code)).all()
        for rule in drafts:
            activate_rule(db, rule, approved_by=APPROVER_ID)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(f"created:    {result['created']}")
    print(f"skipped:    {result['skipped']}")
    print(f"config_set: {result['config_set']}")
    print(f"activated:  {len(drafts)}")
    print(f"Demo tenant: {DEMO_TENANT_ID}")


if __name__ == "__main__":
    main()
