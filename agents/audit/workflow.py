"""Shared state-machine helper for cases, findings (and corrective actions later).

Each workflow declares its statuses (a StrEnum) and its allowed moves; this class answers
"may X move to Y?" the same way for all of them. Pure Python: no database.
"""
from collections.abc import Mapping
from enum import StrEnum


class InvalidTransition(Exception):
    """A record was asked to move to a status that may not follow its current one."""

    def __init__(self, current: str, target: str):
        super().__init__(f"cannot move from {current} to {target}")
        self.current = current
        self.target = target


class StateMachine:
    def __init__(self, statuses: type[StrEnum], transitions: Mapping[StrEnum, frozenset[StrEnum]]):
        missing = set(statuses) - set(transitions)
        if missing:
            raise ValueError(f"Every status needs an entry in the transitions: missing {sorted(missing)}")
        self.statuses = statuses
        self.transitions = transitions

    def can_transition(self, current: str, target: str) -> bool:
        """True if `current` may move to `target`. Unknown statuses are never allowed."""
        try:
            return self.statuses(target) in self.transitions[self.statuses(current)]
        except ValueError:
            return False

    def allowed_next(self, current: str) -> list[StrEnum]:
        """Statuses `current` may move to, in a stable order (for buttons and messages)."""
        return sorted(self.transitions[self.statuses(current)])

    def ensure_transition(self, current: str, target: str) -> None:
        """Raise InvalidTransition unless the move is allowed."""
        if not self.can_transition(current, target):
            raise InvalidTransition(current, target)
