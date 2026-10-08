"""Phase 3 demo: make sure every demo exception is in a case, then give the dev user some work.

Run:  .venv\\Scripts\\python -m scripts.run_phase3_demo
Development/test only. Run scripts.run_phase2_demo first. Safe to run again: cases that are
already assigned or already have comments are left alone.
"""
import sys
import uuid

from agents.audit.services.case_grouping_service import backfill_cases
from agents.audit.services.case_service import add_comment, assign_case, case_comments, list_cases
from scripts.seed_rule_pack import APPROVER_ID, DEMO_TENANT_ID
from shared.config import settings
from shared.db import SessionLocal

# Must match DEV_USER_ID in frontend/lib/api.ts, so these cases show as "Me" in the browser.
DEV_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
DEMO_COMMENT = "Demo: started reviewing the linked records."


def _person(user_id: uuid.UUID | None) -> str:
    if user_id is None:
        return "-"
    return "dev user (Me)" if user_id == DEV_USER_ID else str(user_id)[:8]


def main() -> None:
    if settings.environment not in {"development", "test"}:
        print("Refusing to run the demo: ENVIRONMENT is not development or test.")
        sys.exit(1)

    db = SessionLocal()
    try:
        backfill = backfill_cases(db, DEMO_TENANT_ID)
        cases = list_cases(db, DEMO_TENANT_ID)
        picked = [c for c in cases if c.priority == "CRITICAL"][:1] + [c for c in cases if c.priority == "HIGH"][:1]
        assigned = commented = 0
        for case in picked:
            if case.assigned_to is None:
                assign_case(db, case, DEV_USER_ID, actor_id=APPROVER_ID)   # the dev audit manager assigns
                assigned += 1
            if not case_comments(db, case):
                add_comment(db, case, DEV_USER_ID, DEMO_COMMENT)
                commented += 1
        db.commit()
        rows = [(c.case_number, c.priority, c.status, _person(c.assigned_to)) for c in cases]
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(f"backfill: {backfill['cases_created']} cases created, {backfill['joined']} joined")
    print(f"assigned to dev user: {assigned}, comments added: {commented}")
    print(f"{'CASE':15} {'PRIORITY':9} {'STATUS':19} ASSIGNED")
    for number, priority, status, person in sorted(rows):
        print(f"{number:15} {priority:9} {status:19} {person}")
    print(f"Demo tenant: {DEMO_TENANT_ID}")


if __name__ == "__main__":
    main()
