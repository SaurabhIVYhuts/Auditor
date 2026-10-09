"""Daily jobs for every hospital: batch rule runs (Phase 2) and corrective-action reminders.

Run:  .venv\\Scripts\\python -m scripts.run_daily_jobs
Each hospital is committed on its own, so one hospital's error does not undo the others.
Safe to run again the same day: reminders are sent once; batch runs skip what was already found.
TODO: schedule daily (cron/Celery) later.
"""
from sqlalchemy import select, union

from agents.audit.models import AuditRule, CorrectiveAction
from agents.audit.services.action_service import WITH_OWNER_VALUES, run_action_reminders
from agents.audit.services.batch_runner import run_due_batch_rules
from shared.db import SessionLocal


def hospitals(db) -> list:
    """Hospitals that have rules or actions still with their owners."""
    return sorted(db.scalars(union(
        select(AuditRule.tenant_id).where(AuditRule.is_deleted.is_(False)),
        select(CorrectiveAction.tenant_id).where(CorrectiveAction.is_deleted.is_(False),
                                                 CorrectiveAction.status.in_(WITH_OWNER_VALUES)),
    )), key=str)


def main() -> None:
    db = SessionLocal()
    failed = 0
    try:
        for tenant_id in hospitals(db):
            try:
                runs = run_due_batch_rules(db, tenant_id)
                reminders = run_action_reminders(db, tenant_id)
                db.commit()
            except Exception as err:                        # keep going with the other hospitals
                db.rollback()
                failed += 1
                print(f"{tenant_id}: FAILED - {err}")
                continue
            print(f"{tenant_id}: batch runs {len(runs)}, new exceptions {sum(r.exceptions_created for r in runs)}, "
                  f"due soon {reminders['due_soon']}, overdue {reminders['overdue']}, "
                  f"escalated {reminders['escalated']}")
    finally:
        db.close()
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
