"""Phase 2 demo: seed + activate the procurement pack, then send the demo procurement events.

Run:  .venv\\Scripts\\python -m scripts.run_phase2_demo
Development/test only. Safe to run again: the second run reports every event as a duplicate
and creates no new exceptions.
"""
import sys

from agents.audit.demo.phase2_scenario import run_phase2_scenario
from agents.audit.services.pack_seeder import activate_pack, seed_procurement_pack
from scripts.seed_rule_pack import APPROVER_ID, AUTHOR_ID, DEMO_TENANT_ID
from shared.config import settings
from shared.db import SessionLocal


def main() -> None:
    if settings.environment not in {"development", "test"}:
        print("Refusing to run the demo: ENVIRONMENT is not development or test.")
        sys.exit(1)

    db = SessionLocal()
    try:
        seed_procurement_pack(db, DEMO_TENANT_ID, created_by=AUTHOR_ID)
        activate_pack(db, DEMO_TENANT_ID, approved_by=APPROVER_ID)
        created = run_phase2_scenario(db, DEMO_TENANT_ID)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print("Exceptions created in this run:")
    for code, count in created.items():
        print(f"  {code:15} {count}")
    print(f"  {'TOTAL':15} {sum(created.values())}")
    print(f"Demo tenant: {DEMO_TENANT_ID}")


if __name__ == "__main__":
    main()
