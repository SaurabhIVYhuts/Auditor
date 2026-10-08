"""Tests for the audit case state machine (AUD-020)."""
import itertools

import pytest

from agents.audit.cases.state_machine import (
    OPEN_STATUSES, TRANSITIONS, CaseStatus, InvalidTransition, allowed_next, can_transition,
    ensure_transition,
)

ALLOWED = sorted((current, target) for current, targets in TRANSITIONS.items() for target in targets)
REFUSED = sorted(set(itertools.product(CaseStatus, repeat=2)) - set(ALLOWED))


@pytest.mark.parametrize("current,target", ALLOWED, ids=[f"{c}->{t}" for c, t in ALLOWED])
def test_allowed_transition_passes(current, target):
    assert can_transition(current, target) is True
    ensure_transition(current, target)                      # does not raise


@pytest.mark.parametrize("current,target", REFUSED, ids=[f"{c}->{t}" for c, t in REFUSED])
def test_not_allowed_transition_is_refused(current, target):
    assert can_transition(current, target) is False
    with pytest.raises(InvalidTransition):
        ensure_transition(current, target)


def test_every_status_has_an_entry_and_open_to_closed_is_refused():
    assert set(TRANSITIONS) == set(CaseStatus)
    assert ("OPEN", "CLOSED") in [(str(c), str(t)) for c, t in REFUSED]


def test_staying_in_the_same_status_is_refused():
    for status in CaseStatus:
        assert can_transition(status, status) is False


def test_error_message_names_both_statuses():
    with pytest.raises(InvalidTransition, match="cannot move from OPEN to CLOSED") as caught:
        ensure_transition("OPEN", "CLOSED")
    assert (caught.value.current, caught.value.target) == ("OPEN", "CLOSED")


def test_helpers():
    assert allowed_next("IN_INVESTIGATION") == ["ON_HOLD", "PENDING_REVIEW"]
    assert CaseStatus.CLOSED not in OPEN_STATUSES and len(OPEN_STATUSES) == 9
    assert can_transition("OPEN", "NOT_A_STATUS") is False
