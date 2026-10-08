"""Development: put exceptions made before case grouping existed into cases.

Run:  .venv\\Scripts\\python -m scripts.backfill_cases [tenant-uuid]
Development/test only. Uses the demo hospital unless a tenant id is given.
Safe to run again: the second run finds no NEW exceptions and changes nothing.
"""
import sys
import uuid

from agents.audit.services.case_grouping_service import backfill_cases
from scripts.seed_rule_pack import DEMO_TENANT_ID
from shared.config import settings
from shared.db import SessionLocal


def main() -> None:
    if settings.environment not in {"development", "test"}:
        print("Refusing to backfill cases: ENVIRONMENT is not development or test.")
        sys.exit(1)
    tenant_id = uuid.UUID(sys.argv[1]) if len(sys.argv) > 1 else DEMO_TENANT_ID

    db = SessionLocal()
    try:
        counts = backfill_cases(db, tenant_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(f"exceptions:    {counts['exceptions']}")
    print(f"cases_created: {counts['cases_created']}")
    print(f"joined:        {counts['joined']}")
    print(f"skipped:       {counts['skipped']}  (no rule)")
    print(f"Tenant: {tenant_id}")


if __name__ == "__main__":
    main()
