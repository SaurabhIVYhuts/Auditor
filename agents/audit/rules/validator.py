"""DSL validator (AUD-011): checks a rule definition before it can be saved or run.

Returns a list of plain-language problems (empty list = valid). Anything unknown is
rejected: fields, operators, functions, events, actions, extra keys (architecture test T-04).
"""
import re
from typing import Any

from agents.audit.rules import dsl_spec as spec

COMPARISON_KEYS = frozenset({"field", "op", "value", "value_ref"})
FUNCTION_KEYS = frozenset({"fn", "args", "op", "value", "value_ref"})


class RuleValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _is_whole_number(v: Any, minimum: int) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= minimum


def _check_field(ref: Any, path: str, errors: list[str]) -> None:
    if not isinstance(ref, str) or "." not in ref:
        errors.append(f"{path}: field must look like 'po.grand_total'")
        return
    prefix, name = ref.split(".", 1)
    if name not in spec.FIELDS.get(prefix, frozenset()):
        errors.append(f"{path}: unknown field {ref!r}")


def _check_comparison(node: dict, path: str, errors: list[str]) -> None:
    op = node.get("op")
    if op not in spec.COMPARISON_OPS:
        errors.append(f"{path}: unknown operator {op!r}")
        return
    has_value, has_ref = "value" in node, "value_ref" in node
    if op == "exists":
        if has_value or has_ref:
            errors.append(f"{path}: 'exists' takes no value")
        return
    if has_value == has_ref:
        errors.append(f"{path}: give exactly one of 'value' or 'value_ref'")
        return
    if has_ref:
        ref = node["value_ref"]
        if not (isinstance(ref, str) and re.match(spec.CONFIG_REF_PATTERN, ref)):
            errors.append(f"{path}: value_ref must look like 'config.some_limit'")
        return
    value = node["value"]
    if op == "between" and not (isinstance(value, list) and len(value) == 2):
        errors.append(f"{path}: 'between' needs [low, high]")
    elif op == "in" and not isinstance(value, list):
        errors.append(f"{path}: 'in' needs a list")
    elif op == "matches":
        if not (isinstance(value, str) and len(value) <= spec.MAX_PATTERN_LENGTH):
            errors.append(f"{path}: 'matches' needs a text pattern of at most "
                          f"{spec.MAX_PATTERN_LENGTH} characters")
        else:
            try:
                re.compile(value)
            except re.error:
                errors.append(f"{path}: 'matches' pattern is not valid")


def _check_arg(value: Any, kind: str, path: str, errors: list[str]) -> None:
    if kind == "entity":
        if value not in spec.FIELDS:
            errors.append(f"{path}: unknown entity {value!r}")
    elif kind == "field":
        _check_field(value, path, errors)
    elif kind == "fields":
        if not isinstance(value, list) or not value:
            errors.append(f"{path}: needs a non-empty list of fields")
        else:
            for i, item in enumerate(value):
                _check_field(item, f"{path}[{i}]", errors)
    elif kind == "int":
        if not _is_whole_number(value, 0):
            errors.append(f"{path}: must be a whole number >= 0")
    elif kind == "level":
        if isinstance(value, str):
            _check_field(value, path, errors)
        elif not _is_whole_number(value, 1):
            errors.append(f"{path}: must be a number >= 1 or a field")


def _check_function(node: dict, path: str, errors: list[str]) -> None:
    name = node.get("fn")
    fn_spec = spec.FUNCTIONS.get(name) if isinstance(name, str) else None
    if fn_spec is None:
        errors.append(f"{path}: unknown function {name!r}")
        return
    args = node.get("args")
    if not isinstance(args, dict) or set(args) != set(fn_spec["args"]):
        errors.append(f"{path}: {name} needs exactly the args {sorted(fn_spec['args'])}")
        return
    for arg, kind in fn_spec["args"].items():
        _check_arg(args[arg], kind, f"{path}.args.{arg}", errors)
    if fn_spec["returns"] == "number":
        _check_comparison(node, path, errors)        # e.g. days_between(...) > 30
    elif {"op", "value", "value_ref"} & set(node):
        errors.append(f"{path}: {name} is a yes/no check and takes no operator or value")


def _check_condition(node: Any, path: str, depth: int, counter: list[int], errors: list[str]) -> None:
    counter[0] += 1
    if depth > spec.MAX_DEPTH or counter[0] > spec.MAX_NODES:
        errors.append(f"{path}: condition is too deep or has too many parts")
        return
    if not isinstance(node, dict):
        errors.append(f"{path}: must be an object")
        return
    group = next((k for k in ("all", "any", "not") if k in node), None)
    if group is not None:
        if len(node) != 1:
            errors.append(f"{path}: '{group}' cannot be mixed with other keys")
            return
        children = [node["not"]] if group == "not" else node[group]
        if group != "not" and (not isinstance(children, list) or not children):
            errors.append(f"{path}: '{group}' needs a non-empty list")
            return
        for i, child in enumerate(children):
            child_path = f"{path}.not" if group == "not" else f"{path}.{group}[{i}]"
            _check_condition(child, child_path, depth + 1, counter, errors)
        return
    allowed = FUNCTION_KEYS if "fn" in node else COMPARISON_KEYS
    extra = set(node) - allowed
    if extra:
        errors.append(f"{path}: keys not allowed: {sorted(extra)}")
        return
    if "fn" in node:
        _check_function(node, path, errors)
    elif "field" in node:
        _check_field(node["field"], path, errors)
        _check_comparison(node, path, errors)
    else:
        errors.append(f"{path}: expected all, any, not, field or fn")


ALL_FIELD_NAMES = frozenset(name for names in spec.FIELDS.values() for name in names)


def _check_trigger(trigger: Any, errors: list[str]) -> None:
    if not isinstance(trigger, dict) or trigger.get("type") not in spec.TRIGGER_TYPES:
        errors.append("trigger.type must be EVENT or BATCH")
        return
    extra = set(trigger) - {"type", "events", "batch_cron"}
    if extra:
        errors.append(f"trigger: keys not allowed: {sorted(extra)}")
    events = trigger.get("events", [])
    if not isinstance(events, list):
        errors.append("trigger.events must be a list")
        return
    if trigger["type"] == "EVENT" and not events:
        errors.append("trigger.events: an EVENT rule needs at least one event")
    for event in events:
        if event not in spec.EVENT_TYPES:
            errors.append(f"trigger.events: unknown event {event!r}")
    cron = trigger.get("batch_cron")
    if trigger["type"] == "BATCH" and not cron:
        errors.append("trigger.batch_cron is required for a BATCH rule")
    if cron is not None and not (isinstance(cron, str) and len(cron.split()) == 5):
        errors.append("trigger.batch_cron must have 5 parts, like '0 2 * * *'")


def _check_action(action: Any, errors: list[str]) -> None:
    if not isinstance(action, dict) or action.get("type") not in spec.ACTION_TYPES:
        errors.append("action.type must be CREATE_EXCEPTION, CREATE_CASE or NOTIFY_ONLY")
        return
    extra = set(action) - {"type", "group_by", "group_window_days"}
    if extra:
        errors.append(f"action: keys not allowed: {sorted(extra)}")
    group_by = action.get("group_by", [])
    if not isinstance(group_by, list) or any(f not in ALL_FIELD_NAMES for f in group_by):
        errors.append("action.group_by must be a list of known field names, like ['vendor_id']")
    if "group_window_days" in action and not _is_whole_number(action["group_window_days"], 1):
        errors.append("action.group_window_days must be a whole number >= 1")


def validate_definition(definition: Any) -> list[str]:
    """Return every problem found in a rule definition (empty list = valid)."""
    if not isinstance(definition, dict):
        return ["definition must be an object"]
    errors: list[str] = []
    extra = set(definition) - spec.DEFINITION_KEYS
    if extra:
        errors.append(f"definition: keys not allowed: {sorted(extra)}")
    _check_trigger(definition.get("trigger"), errors)
    if "condition" not in definition:
        errors.append("condition is required")
    else:
        _check_condition(definition["condition"], "condition", 1, [0], errors)
    _check_action(definition.get("action"), errors)
    capture = definition.get("evidence_capture", [])
    if not (isinstance(capture, list) and all(isinstance(c, str) for c in capture)):
        errors.append("evidence_capture must be a list of names")
    return errors


def ensure_valid(definition: Any) -> None:
    """Raise RuleValidationError (listing every problem) if the definition is not valid."""
    errors = validate_definition(definition)
    if errors:
        raise RuleValidationError(errors)
