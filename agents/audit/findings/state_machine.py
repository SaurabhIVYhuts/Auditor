"""Audit finding state machine (AUD-031): which status may follow which.

Pure Python: no database. The finding service will call ensure_transition() before every change.

    DRAFT -> UNDER_REVIEW -> CONFIRMED -> ACTION_ASSIGNED -> RESOLVED -> VERIFIED -> CLOSED
      ^          |                             ^                |
      +----------+ (returned for changes)      +-- REOPENED <---+ (verification failed)
                 +-> DISMISSED (reason mandatory)
"""
from enum import StrEnum

from agents.audit.workflow import InvalidTransition, StateMachine  # noqa: F401  (InvalidTransition re-exported)


class FindingStatus(StrEnum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"
    ACTION_ASSIGNED = "ACTION_ASSIGNED"
    RESOLVED = "RESOLVED"
    VERIFIED = "VERIFIED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


# Allowed next statuses for each status (architecture section 4.11, finding state machine).
TRANSITIONS: dict[FindingStatus, frozenset[FindingStatus]] = {
    FindingStatus.DRAFT: frozenset({FindingStatus.UNDER_REVIEW}),
    FindingStatus.UNDER_REVIEW: frozenset({FindingStatus.CONFIRMED, FindingStatus.DISMISSED, FindingStatus.DRAFT}),
    FindingStatus.CONFIRMED: frozenset({FindingStatus.ACTION_ASSIGNED}),
    FindingStatus.DISMISSED: frozenset(),
    FindingStatus.ACTION_ASSIGNED: frozenset({FindingStatus.RESOLVED}),
    FindingStatus.RESOLVED: frozenset({FindingStatus.VERIFIED, FindingStatus.REOPENED}),
    FindingStatus.REOPENED: frozenset({FindingStatus.ACTION_ASSIGNED}),
    FindingStatus.VERIFIED: frozenset({FindingStatus.CLOSED}),
    FindingStatus.CLOSED: frozenset(),
}

# Findings that still need work (used later: a case cannot close while any of these remain).
OPEN_STATUSES: frozenset[FindingStatus] = frozenset(FindingStatus) - {FindingStatus.DISMISSED, FindingStatus.CLOSED}

_MACHINE = StateMachine(FindingStatus, TRANSITIONS)
can_transition = _MACHINE.can_transition
allowed_next = _MACHINE.allowed_next
ensure_transition = _MACHINE.ensure_transition
