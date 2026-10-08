"""Audit case state machine (AUD-020): which status may follow which.

Pure Python: no database. The case service will call ensure_transition() before every change.

    OPEN -> ASSIGNED -> IN_INVESTIGATION -> PENDING_REVIEW -> FINDING_CONFIRMED -> ACTION_IN_PROGRESS -> CLOSED
                         ^    |                     |
                         |    v                     +-> NO_ISSUE (dismissed with reason) -> CLOSED
                         |  ON_HOLD (awaiting info)
                         +-- REOPENED <- CLOSED (new evidence)
"""
from enum import StrEnum

from agents.audit.workflow import InvalidTransition, StateMachine  # noqa: F401  (InvalidTransition re-exported)


class CaseStatus(StrEnum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_INVESTIGATION = "IN_INVESTIGATION"
    ON_HOLD = "ON_HOLD"
    PENDING_REVIEW = "PENDING_REVIEW"
    FINDING_CONFIRMED = "FINDING_CONFIRMED"
    NO_ISSUE = "NO_ISSUE"
    ACTION_IN_PROGRESS = "ACTION_IN_PROGRESS"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


# Allowed next statuses for each status (architecture section 4.1, case state machine).
TRANSITIONS: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.OPEN: frozenset({CaseStatus.ASSIGNED}),
    CaseStatus.ASSIGNED: frozenset({CaseStatus.IN_INVESTIGATION}),
    CaseStatus.IN_INVESTIGATION: frozenset({CaseStatus.PENDING_REVIEW, CaseStatus.ON_HOLD}),
    CaseStatus.ON_HOLD: frozenset({CaseStatus.IN_INVESTIGATION}),
    CaseStatus.PENDING_REVIEW: frozenset({CaseStatus.FINDING_CONFIRMED, CaseStatus.NO_ISSUE}),
    CaseStatus.FINDING_CONFIRMED: frozenset({CaseStatus.ACTION_IN_PROGRESS}),
    CaseStatus.ACTION_IN_PROGRESS: frozenset({CaseStatus.CLOSED}),
    CaseStatus.NO_ISSUE: frozenset({CaseStatus.CLOSED}),
    CaseStatus.CLOSED: frozenset({CaseStatus.REOPENED}),
    CaseStatus.REOPENED: frozenset({CaseStatus.IN_INVESTIGATION}),
}

# Every status a case can have while it still needs work (used by queues and counts).
OPEN_STATUSES: frozenset[CaseStatus] = frozenset(CaseStatus) - {CaseStatus.CLOSED}


_MACHINE = StateMachine(CaseStatus, TRANSITIONS)
can_transition = _MACHINE.can_transition        # may a case in `current` move to `target`?
allowed_next = _MACHINE.allowed_next            # statuses a case may move to next, stable order
ensure_transition = _MACHINE.ensure_transition  # raises InvalidTransition unless allowed
