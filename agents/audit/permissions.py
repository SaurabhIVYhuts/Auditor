"""Audit roles and what each role may do (task AUD-002).

Permissions are written as "resource:action". Endpoints check permissions,
never role names, so changing who may do what only means editing this map.
Based on the API role table in architecture section 8.
Row-level scope (assigned cases, own department) is enforced separately, later.
"""
from collections.abc import Iterable
from enum import StrEnum


class AuditRole(StrEnum):
    AUDITOR = "AUD"
    AUDIT_MANAGER = "AM"
    COMPLIANCE_OFFICER = "CO"
    AUDITEE = "OWN"          # department owner / corrective-action owner
    MANAGEMENT = "MGT"
    ADMIN = "ADM"


# Case visibility scopes (which cases "case:read" shows), used by the case API:
#   case:read_assigned   - cases assigned to me            (Auditor)
#   case:read_high_risk  - HIGH and CRITICAL cases         (Management)
#   case:read_all        - every case of my hospital       (Audit Manager)
#   case:read_restricted - also personnel-restricted cases (Audit Manager)
AUDITOR = frozenset({
    "case:read", "case:read_assigned", "case:update", "case:comment",
    "case:query_auditee", "case:close",
    "exception:read", "exception:create_case",
    "source_record:read",
    "rule:read",
    "evidence:write", "evidence:read", "evidence:verify", "evidence:supersede",
    "risk:read",
    "anomaly:read", "anomaly:feedback",
    "finding:read", "finding:write",
    "action:read", "action:create", "action:verify",
    "report:read", "report:create",
    "dashboard:read",
})

AUDIT_MANAGER = AUDITOR | frozenset({
    "case:create", "case:assign", "case:close_high_risk", "case:read_all", "case:read_restricted",
    "rule:write", "rule:activate", "rule:run",
    "evidence:export_pack",
    "risk:configure", "risk:override", "risk:department_read",
    "anomaly:suppress",
    "finding:confirm", "finding:dismiss",
    "action:extend",
    "report:approve", "report:distribute",
    "dashboard:summary",
})

COMPLIANCE_OFFICER = frozenset({
    "rule:read", "rule:write",
    "policy:read", "policy:write",
    "compliance:run", "compliance:read",
    "evidence:write", "evidence:read",
    "dashboard:summary",
})

AUDITEE = frozenset({
    "query:respond",             # answer queries in their own thread only
    "evidence:upload_own",       # upload evidence to their own query/action only
    "finding:respond",           # management response on a confirmed finding
    "action:read_own", "action:submit",
})

MANAGEMENT = frozenset({
    "case:read", "case:read_high_risk", "evidence:read", "finding:read",
    "dashboard:summary",
    "risk:department_read",
    "report:read",
})

ADMIN = frozenset({
    "connector:sync",
    "rule:read_runs",
    "notification_rule:configure",
})

ROLE_PERMISSIONS: dict[AuditRole, frozenset[str]] = {
    AuditRole.AUDITOR: AUDITOR,
    AuditRole.AUDIT_MANAGER: AUDIT_MANAGER,
    AuditRole.COMPLIANCE_OFFICER: COMPLIANCE_OFFICER,
    AuditRole.AUDITEE: AUDITEE,
    AuditRole.MANAGEMENT: MANAGEMENT,
    AuditRole.ADMIN: ADMIN,
}


def permissions_for(roles: Iterable[str]) -> frozenset[str]:
    """All permissions for a user's roles. Unknown roles grant nothing."""
    granted: set[str] = set()
    for role_code in roles:
        try:
            role = AuditRole(role_code)
        except ValueError:
            continue
        granted |= ROLE_PERMISSIONS[role]
    return frozenset(granted)


def has_permission(roles: Iterable[str], permission: str) -> bool:
    return permission in permissions_for(roles)
