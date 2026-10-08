"""Tests for the audit finding state machine (AUD-031)."""
import itertools

import pytest

from agents.audit.findings.state_machine import (
    OPEN_STATUSES, TRANSITIONS, FindingStatus, InvalidTransition, allowed_next, can_transition,
    ensure_transition,
)
from agents.audit.workflow import InvalidTransition as SharedInvalidTransition

ALLOWED = sorted((current, target) for current, targets in TRANSITIONS.items() for target in targets)
REFUSED = sorted(set(itertools.product(FindingStatus, repeat=2)) - set(ALLOWED))


@pytest.mark.parametrize("current,target", ALLOWED, ids=[f"{c}->{t}" for c, t in ALLOWED])
def test_allowed_transition_passes(current, target):
    assert can_transition(current, target) is True
    ensure_transition(current, target)


@pytest.mark.parametrize("current,target", REFUSED, ids=[f"{c}->{t}" for c, t in REFUSED])
def test_not_allowed_transition_is_refused(current, target):
    assert can_transition(current, target) is False
    with pytest.raises(InvalidTransition):
        ensure_transition(current, target)


def test_shape_of_the_workflow():
    assert len(ALLOWED) == 10 and set(TRANSITIONS) == set(FindingStatus)
    assert allowed_next("UNDER_REVIEW") == ["CONFIRMED", "DISMISSED", "DRAFT"]
    assert allowed_next("DISMISSED") == [] and allowed_next("CLOSED") == []
    assert OPEN_STATUSES == set(FindingStatus) - {"DISMISSED", "CLOSED"}


def test_cases_and_findings_share_one_error_type():
    from agents.audit.cases.state_machine import InvalidTransition as CaseInvalidTransition
    assert InvalidTransition is SharedInvalidTransition is CaseInvalidTransition
    with pytest.raises(InvalidTransition, match="cannot move from DRAFT to CONFIRMED"):
        ensure_transition("DRAFT", "CONFIRMED")
