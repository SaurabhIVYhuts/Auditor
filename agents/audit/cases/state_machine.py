"""Audit case state machine (AUD-020): which status may follow which.

Pure Python: no database. The case service will call ensure_transition() before every change.

    OPEN -> ASSIGNED -> IN_INVESTIGATION -> PENDING_REVIEW -> FINDING_CONFIRMED -> ACTION_IN_PROGRESS -> CLOSED
                         ^    |                     |
                         |    v                     +-> NO_ISSUE (dismissed with reason) -> CLOSED
                         |  ON_HOLD (awaiting info)
                         +-- REOPENED <- CLOSED (new evidence)
"""
from enum import StrEnum


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


class InvalidTransition(Exception):
    """A case was asked to move to a status that may not follow its current one."""

    def __init__(self, current: str, target: str):
        super().__init__(f"cannot move from {current} to {target}")
        self.current = current
        self.target = target


def can_transition(current: str, target: str) -> bool:
    """True if a case in `current` may move to `target`. Unknown statuses are never allowed."""
    try:
        return CaseStatus(target) in TRANSITIONS[CaseStatus(current)]
    except ValueError:
        return False


def allowed_next(current: str) -> list[CaseStatus]:
    """The statuses a case in `current` may move to, in a stable order (for buttons and messages)."""
    return sorted(TRANSITIONS[CaseStatus(current)])


def ensure_transition(current: str, target: str) -> None:
    """Raise InvalidTransition unless the move is allowed."""
    if not can_transition(current, target):
        raise InvalidTransition(current, target)
