"""DSL evaluator (AUD-011): runs a VALIDATED rule condition against facts from snapshots.

Read-only: it only reads the facts it is given. Uses three answers:
True = problem found, False = no problem, None = unknown (data missing or wrong type).
Unknown is never a silent pass: it is recorded as a warning. Only True creates an exception.
"""
import operator
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable

MAX_TEXT_LENGTH = 1000      # longest text that 'matches' will look at
_MISSING = object()         # marker for "this data is not there"

_COMPARE = {"=": operator.eq, "!=": operator.ne, ">": operator.gt,
            ">=": operator.ge, "<": operator.lt, "<=": operator.le}


class RuleEvaluationError(RuntimeError):
    """The rule cannot be evaluated at all, e.g. a function that is not available."""


@dataclass
class EvaluationContext:
    facts: dict[str, dict[str, Any]]          # e.g. {"po": {...}, "invoice": {...}}
    get_config: Callable[[str], Any]          # reads audit_config; raises if a value is missing
    functions: dict[str, Callable[..., Any]] = field(default_factory=dict)  # database functions (Step 5)


@dataclass
class EvaluationResult:
    matched: bool = False                     # True only when the answer is definitely True
    outcome: bool | None = None               # True / False / None (unknown)
    warnings: list[str] = field(default_factory=list)
    details: list[dict[str, Any]] = field(default_factory=list)   # the values that were checked


def _read_field(ctx: EvaluationContext, ref: str) -> Any:
    prefix, name = ref.split(".", 1)
    record = ctx.facts.get(prefix)
    if not isinstance(record, dict) or record.get(name) is None:
        return _MISSING
    return record[name]


def _as_number(value: Any) -> Any:
    """Turn numeric text like '250000' into a number; leave everything else unchanged."""
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def _compare(left: Any, op: str, right: Any) -> bool:
    if op == "in":
        return left in right
    if op == "between":
        return _as_number(right[0]) <= _as_number(left) <= _as_number(right[1])
    if op == "matches":
        return isinstance(left, str) and re.search(right, left[:MAX_TEXT_LENGTH]) is not None
    return _COMPARE[op](_as_number(left), _as_number(right))


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def _approval_missing(ctx: EvaluationContext, args: dict[str, Any]) -> Any:
    """True if no approval exists at or above the required level."""
    record = ctx.facts.get(args["entity"])
    if not isinstance(record, dict) or not isinstance(record.get("approvals"), list):
        return _MISSING
    required = args["min_level"]
    if isinstance(required, str):                 # the level comes from a field, e.g. po.required_approval_level
        required = _read_field(ctx, required)
        if required is _MISSING:
            return _MISSING
    required = float(required)
    levels = [a.get("level") for a in record["approvals"] if isinstance(a, dict)]
    return not any(isinstance(level, (int, float)) and level >= required for level in levels)


def _days_between(ctx: EvaluationContext, args: dict[str, Any]) -> Any:
    """Whole days from one date field to another (negative if 'to' is earlier)."""
    start, end = _read_field(ctx, args["from"]), _read_field(ctx, args["to"])
    if start is _MISSING or end is _MISSING:
        return _MISSING
    return (_parse_date(end) - _parse_date(start)).days


# Functions that only need the facts. Database functions (duplicate_of, sum_over_window)
# are passed in through EvaluationContext.functions (Step 5).
PURE_FUNCTIONS: dict[str, Callable[[EvaluationContext, dict[str, Any]], Any]] = {
    "approval_missing": _approval_missing,
    "days_between": _days_between,
}


def _call_function(node: dict[str, Any], ctx: EvaluationContext) -> Any:
    name = node["fn"]
    fn = PURE_FUNCTIONS.get(name) or ctx.functions.get(name)
    if fn is None:
        raise RuleEvaluationError(f"Function {name!r} is not available in this run")
    try:
        return fn(ctx, node["args"])
    except (TypeError, ValueError, KeyError):
        return _MISSING                           # bad or missing data -> unknown, with a warning


def _combine(outcomes: list[bool | None], group: str) -> bool | None:
    """Three-answer logic: unknown never becomes a definite yes or no by accident."""
    if group == "all":
        if False in outcomes:
            return False
        return None if None in outcomes else True
    if True in outcomes:                          # group == "any"
        return True
    return None if None in outcomes else False


def _evaluate(node: dict[str, Any], ctx: EvaluationContext, result: EvaluationResult, path: str) -> bool | None:
    for group in ("all", "any"):
        if group in node:
            outcomes = [_evaluate(child, ctx, result, f"{path}.{group}[{i}]")
                        for i, child in enumerate(node[group])]
            return _combine(outcomes, group)
    if "not" in node:
        inner = _evaluate(node["not"], ctx, result, f"{path}.not")
        return None if inner is None else not inner

    if "fn" in node:
        left, label = _call_function(node, ctx), f"{node['fn']}()"
    else:
        left, label = _read_field(ctx, node["field"]), node["field"]
    op = node.get("op")

    if op is None:                                # yes/no function such as approval_missing
        outcome = None if left is _MISSING else bool(left)
    elif op == "exists":
        outcome = left is not _MISSING
    elif left is _MISSING:
        outcome = None
    else:
        if "value_field" in node:
            right = _read_field(ctx, node["value_field"])     # compare two fields, e.g. invoice vs PO
        elif "value_ref" in node:
            right = ctx.get_config(node["value_ref"].removeprefix("config."))
        else:
            right = node["value"]
        try:
            outcome = None if right is _MISSING else _compare(left, op, right)
        except (TypeError, ValueError, re.error):
            outcome = None

    if outcome is None:
        result.warnings.append(f"{path}: could not check {label} (data missing or wrong type)")
    result.details.append({
        "check": label, "op": op,
        "value": None if left is _MISSING else left,
        "outcome": outcome,
    })
    return outcome


def evaluate_condition(condition: dict[str, Any], ctx: EvaluationContext) -> EvaluationResult:
    """Evaluate a validated condition. Only a definite True counts as a match."""
    result = EvaluationResult()
    result.outcome = _evaluate(condition, ctx, result, "condition")
    result.matched = result.outcome is True
    return result
