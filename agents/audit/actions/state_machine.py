"""Corrective action state machine (AUD-032): which status may follow which.

Pure Python: no database. The action service calls ensure_transition() before every change.

    OPEN -> IN_PROGRESS -> SUBMITTED -> VERIFIED -> CLOSED
                ^              |
                +-- RETURNED <-+  (evidence not enough: owner works on it again)
"""
from enum import StrEnum

from agents.audit.workflow import InvalidTransition, StateMachine  # noqa: F401  (InvalidTransition re-exported)


class ActionStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"


TRANSITIONS: dict[ActionStatus, frozenset[ActionStatus]] = {
    ActionStatus.OPEN: frozenset({ActionStatus.IN_PROGRESS}),
    ActionStatus.IN_PROGRESS: frozenset({ActionStatus.SUBMITTED}),
    ActionStatus.SUBMITTED: frozenset({ActionStatus.VERIFIED, ActionStatus.RETURNED}),
    ActionStatus.RETURNED: frozenset({ActionStatus.IN_PROGRESS}),
    ActionStatus.VERIFIED: frozenset({ActionStatus.CLOSED}),
    ActionStatus.CLOSED: frozenset(),
}

# Actions the owner has handed in (or that are already accepted).
SUBMITTED_OR_LATER: frozenset[ActionStatus] = frozenset({ActionStatus.SUBMITTED, ActionStatus.VERIFIED,
                                                         ActionStatus.CLOSED})
# Actions accepted by a verifier.
DONE_STATUSES: frozenset[ActionStatus] = frozenset({ActionStatus.VERIFIED, ActionStatus.CLOSED})
# Actions that still need work (a case cannot close while any of these remain).
OPEN_STATUSES: frozenset[ActionStatus] = frozenset(ActionStatus) - DONE_STATUSES
# Actions waiting for the owner (reminders and "overdue" only apply to these).
WITH_OWNER: frozenset[ActionStatus] = OPEN_STATUSES - SUBMITTED_OR_LATER

_MACHINE = StateMachine(ActionStatus, TRANSITIONS)
can_transition = _MACHINE.can_transition
allowed_next = _MACHINE.allowed_next
ensure_transition = _MACHINE.ensure_transition
