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
    assert has_permission(["AUD"], "finding:write")             # create, edit and submit
    assert not has_permission(["AUD"], "finding:confirm")
    assert has_permission(["MGT"], "finding:read") and not has_permission(["MGT"], "finding:write")


def test_management_reads_only_high_risk_cases_and_cannot_change_them():
    assert has_permission(["MGT"], "dashboard:summary")
    assert has_permission(["MGT"], "case:read_high_risk")
    for permission in ("case:read_all", "case:read_assigned", "case:create", "case:update", "case:assign"):
        assert not has_permission(["MGT"], permission)


def test_only_audit_manager_creates_cases_and_sees_restricted_ones():
    for permission in ("case:create", "case:read_all", "case:read_restricted"):
        assert {r for r in ALL_ROLES if has_permission([r.value], permission)} == {AuditRole.AUDIT_MANAGER}


def test_unknown_or_missing_roles_grant_nothing():
    assert permissions_for(["HACKER"]) == frozenset()
    assert permissions_for([]) == frozenset()


def test_multiple_roles_combine_permissions():
    combined = permissions_for(["CO", "ADM"])
    assert "policy:write" in combined
    assert "connector:sync" in combined
