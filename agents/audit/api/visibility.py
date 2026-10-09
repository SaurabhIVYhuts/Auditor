"""Who may see which finding - ONE rule, used by the finding list, detail, actions and evidence.

- Audit team (finding:read): findings of cases they can see (case_visibility). Drafts and findings
  under review only for those who also write findings (Auditor, Audit Manager), not Management.
- Auditee (finding:read_own): only findings they own, and only once confirmed.
Several roles combine. Everything is limited to the user's hospital.
"""
from sqlalchemy import ColumnElement, and_, false, or_, select, true

from agents.audit.api.cases import case_visibility
from agents.audit.findings.state_machine import CONFIRMED_STATUSES
from agents.audit.models import AuditCase, AuditFinding
from agents.audit.permissions import permissions_for
from shared.auth import CurrentUser

CONFIRMED = sorted(CONFIRMED_STATUSES)


def finding_visibility(user: CurrentUser) -> ColumnElement[bool]:
    """Condition on AuditFinding (needs AuditCase joined on the finding's case_id)."""
    perms = permissions_for(user.roles)
    parts = []
    if "finding:read" in perms:
        stages = true() if "finding:write" in perms else AuditFinding.status.in_(CONFIRMED)
        parts.append(and_(case_visibility(user), stages))
    if "finding:read_own" in perms:
        parts.append(and_(AuditFinding.owner_user_id == user.user_id, AuditFinding.status.in_(CONFIRMED)))
    scope = or_(*parts) if parts else false()
    return and_(AuditFinding.tenant_id == user.tenant_id, AuditFinding.is_deleted.is_(False), scope)


def visible_findings(user: CurrentUser):
    """SELECT of the findings this user may see (case joined for the case rules)."""
    return (select(AuditFinding)
            .join(AuditCase, AuditCase.id == AuditFinding.case_id)
            .where(AuditCase.tenant_id == user.tenant_id, finding_visibility(user)))
