"""Tests for audit roles and permissions: they lock in the architecture's rules."""
import pytest

from agents.audit.permissions import ROLE_PERMISSIONS, AuditRole, has_permission, permissions_for

ALL_ROLES = list(AuditRole)


def test_every_role_has_a_permission_set():
    assert set(ROLE_PERMISSIONS) == set(AuditRole)


@pytest.mark.parametrize("permission", ["risk:read", "case:read", "evidence:read", "exception:read"])
def test_auditee_cannot_see_risk_cases_or_other_evidence(permission):
    assert not has_permission(["OWN"], permission)


@pytest.mark.parametrize("permission", ["finding:confirm", "finding:dismiss", "rule:activate", "risk:configure", "risk:override"])
def test_only_audit_manager_has_approval_powers(permission):
    allowed = {role for role in ALL_ROLES if has_permission([role.value], permission)}
    assert allowed == {AuditRole.AUDIT_MANAGER}


def test_auditor_can_draft_and_submit_but_not_confirm_findings():
    assert has_permission(["AUD"], "finding:create")
    assert has_permission(["AUD"], "finding:submit")
    assert not has_permission(["AUD"], "finding:confirm")


def test_management_sees_summaries_not_case_details():
    assert has_permission(["MGT"], "dashboard:summary")
    assert not has_permission(["MGT"], "case:read")


def test_unknown_or_missing_roles_grant_nothing():
    assert permissions_for(["HACKER"]) == frozenset()
    assert permissions_for([]) == frozenset()


def test_multiple_roles_combine_permissions():
    combined = permissions_for(["CO", "ADM"])
    assert "policy:write" in combined
    assert "connector:sync" in combined
