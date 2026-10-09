"""Phase 4 demo: one case taken through the full human audit loop, and one finding waiting for review.

Run:  .venv\\Scripts\\python -m scripts.run_phase4_demo
Development/test only. Run scripts.run_phase2_demo first (it makes the demo cases).
- The PRC-APR-01 case (PO-DEMO-1) goes all the way to CLOSED: a finished example.
- The PRC-INVPO-01 case (INV-DEMO-5) gets a SUBMITTED finding, waiting for Rahul to confirm it.
Safe to run again: each case continues from where it is; what already exists is not created twice.
People: Priya (AUD), Rahul (AM), Sunita (OWN) - the frontend's dev users.
"""
import sys
from datetime import timedelta

from sqlalchemy.orm import Session

from agents.audit.cases.state_machine import path as case_path
from agents.audit.demo.dev_users import PRIYA, RAHUL, SUNITA
from agents.audit.models import AuditCase, AuditRule, LinkTarget
from agents.audit.services.action_service import (
    actions_for_finding, create_action, start_action, submit_action, verify_action,
)
from agents.audit.services.case_service import (
    _hospital_today, assign_case, case_exceptions, change_status, list_cases,
)
from agents.audit.services.evidence_service import link_evidence, upload_evidence
from agents.audit.services.finding_service import (
    close_finding, confirm_finding, create_finding, list_findings, submit_finding,
)
from scripts.seed_rule_pack import DEMO_TENANT_ID
from shared.config import settings
from shared.db import SessionLocal

AUDITOR, MANAGER = ["AUD"], ["AM"]
PDF = b"%PDF-1.4 demo evidence"

FINDINGS = {
    "PRC-APR-01": {
        "title": "PO-DEMO-1 approved without level-2 approval",
        "condition": "PO-DEMO-1 (Rs 150,000) was approved with no approvals recorded",
        "criteria": "Purchase policy: orders above the limit need level-2 approval",
        "cause": "The approval step was skipped in the procurement system",
        "effect": "Spending above the limit without the required check",
        "recommendation": "Obtain retrospective level-2 approval and enforce the approval step",
        "risk_level": "HIGH", "financial_impact": 150000,
    },
    "PRC-INVPO-01": {
        "title": "INV-DEMO-5 is higher than its purchase order",
        "condition": "Invoice INV-DEMO-5 is Rs 60,000; PO-DEMO-5 is Rs 50,000",
        "criteria": "Invoices may not exceed the approved purchase order value",
        "cause": "Invoice was accepted without a PO value check",
        "effect": "Rs 10,000 billed above the approved amount",
        "recommendation": "Confirm the extra Rs 10,000 with the vendor or recover it; add the PO value check",
        "risk_level": "MEDIUM", "financial_impact": 10000,
    },
}


def case_for_rule(db: Session, rule_code: str) -> AuditCase | None:
    for case in list_cases(db, DEMO_TENANT_ID):
        if any(db.get(AuditRule, e.rule_id).rule_code == rule_code for e in case_exceptions(db, case)):
            return case
    return None


def walk(db: Session, case: AuditCase, target: str, actor, roles) -> None:
    """Move the case step by step to target (nothing if it is there or cannot get there)."""
    for step in case_path(case.status, target) or []:
        change_status(db, case, step.value, actor, roles)


def evidence(db: Session, title: str, filename: str, content_type: str, data: bytes, actor, targets) -> None:
    item = upload_evidence(db, DEMO_TENANT_ID, title=title, filename=filename, content_type=content_type,
                           data=data, actor_id=actor)
    for target_type, target_id in targets:
        link_evidence(db, item, target_type, target_id, actor)


def submitted_finding(db: Session, case: AuditCase, rule_code: str):
    """Priya investigates and submits a finding with evidence (or returns the one already there)."""
    existing = list_findings(db, DEMO_TENANT_ID, case_id=case.id)
    if existing:
        return existing[-1]                                     # the oldest one
    if case.assigned_to != PRIYA:
        assign_case(db, case, PRIYA, RAHUL)
    walk(db, case, "IN_INVESTIGATION", PRIYA, AUDITOR)
    fields = dict(FINDINGS[rule_code])
    finding = create_finding(db, case, fields.pop("title"), PRIYA, **fields)
    evidence(db, "Procurement system record (exported)", "export.txt", "text/plain",
             f"Demo export for {case.case_number}: approvals list is empty.\n".encode(), PRIYA,
             [(LinkTarget.FINDING.value, finding.id), (LinkTarget.CASE.value, case.id)])
    submit_finding(db, finding, PRIYA)
    return finding


def finish_loop(db: Session, case: AuditCase, finding) -> None:
    """Rahul confirms, Sunita fixes and proves it, Priya verifies and closes, Rahul closes the case."""
    due = _hospital_today() + timedelta(days=14)
    if finding.status == "UNDER_REVIEW":
        confirm_finding(db, finding, RAHUL, MANAGER, owner_user_id=SUNITA, due_date=due)
    if finding.status == "CONFIRMED":
        walk(db, case, "FINDING_CONFIRMED", PRIYA, AUDITOR)
        create_action(db, finding, "Obtain retrospective level-2 approval for PO-DEMO-1", SUNITA, due, RAHUL, MANAGER)
        walk(db, case, "ACTION_IN_PROGRESS", RAHUL, MANAGER)
    for action in actions_for_finding(db, finding):
        if action.status in ("OPEN", "RETURNED"):
            start_action(db, action, action.owner_user_id)
        if action.status == "IN_PROGRESS":
            evidence(db, "Signed level-2 approval", "approval.pdf", "application/pdf", PDF, action.owner_user_id,
                     [(LinkTarget.ACTION.value, action.id), (LinkTarget.CASE.value, case.id)])
            submit_action(db, action, action.owner_user_id)
        if action.status == "SUBMITTED":
            verify_action(db, action, PRIYA, AUDITOR, note="Signed approval matches PO-DEMO-1")
    if finding.status == "VERIFIED":
        close_finding(db, finding, PRIYA, AUDITOR)
    if finding.status == "CLOSED":
        walk(db, case, "CLOSED", RAHUL, MANAGER)


def summary(db: Session, case: AuditCase) -> str:
    findings = list_findings(db, DEMO_TENANT_ID, case_id=case.id)
    finding = findings[-1] if findings else None
    actions = actions_for_finding(db, finding) if finding else []
    parts = [f"{case.case_number:15} {case.status:19}",
             f"{finding.finding_number} {finding.status}" if finding else "no finding",
             ", ".join(f"{a.action_number} {a.status}" for a in actions) or "no action"]
    return " | ".join(parts)


def main() -> None:
    if settings.environment not in {"development", "test"}:
        print("Refusing to run the demo: ENVIRONMENT is not development or test.")
        sys.exit(1)

    db = SessionLocal()
    try:
        done, waiting = case_for_rule(db, "PRC-APR-01"), case_for_rule(db, "PRC-INVPO-01")
        if done is None or waiting is None:
            print("Demo cases not found. Run scripts.run_phase2_demo first.")
            sys.exit(1)
        if done.status != "CLOSED":
            finish_loop(db, done, submitted_finding(db, done, "PRC-APR-01"))
        if waiting.status != "CLOSED":
            submitted_finding(db, waiting, "PRC-INVPO-01")
        db.commit()
        lines = [("finished example", summary(db, done)), ("waiting for Rahul", summary(db, waiting))]
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    for name, line in lines:
        print(f"{name:18} {line}")
    print(f"Demo tenant: {DEMO_TENANT_ID}")


if __name__ == "__main__":
    main()
