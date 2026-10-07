"""What the rule DSL may use (whitelists). Anything not listed here is rejected.

Rules are JSON data read by our own interpreter, never run as code, so a rule can
only read these fields, use these operators and call these functions.
"""
from agents.audit.events.procurement_reader import PROCUREMENT_EVENTS

# Fields a rule may read, per prefix (written like "po.grand_total").
FIELDS: dict[str, frozenset[str]] = {
    "po": frozenset({"po_number", "vendor_id", "department_id", "grand_total", "status",
                     "approvals", "required_approval_level", "created_at", "approved_at"}),
    "grn": frozenset({"grn_number", "po_number", "received_qty", "posted_by", "posted_at"}),
    "invoice": frozenset({"invoice_number", "po_number", "vendor_id", "amount",
                          "match_status", "invoice_date"}),
    "payment": frozenset({"payment_ref", "invoice_number", "amount", "status", "paid_at"}),
    "vendor": frozenset({"vendor_id", "status", "bank_changed", "bank_changed_at"}),
}

# Field prefix -> entity_type stored in the Audit Data Hub.
ENTITY_TYPES = {"po": "purchase_order", "grn": "grn", "invoice": "invoice",
                "payment": "payment", "vendor": "vendor"}

COMPARISON_OPS = frozenset({"=", "!=", ">", ">=", "<", "<=", "in", "between", "exists", "matches"})

# Function -> its arguments (name: kind) and what it returns.
# Kinds: entity = a prefix above, field = one whitelisted field, fields = list of fields,
#        int = whole number >= 0, level = number >= 1 or a whitelisted field.
FUNCTIONS: dict[str, dict] = {
    "approval_missing": {"args": {"entity": "entity", "min_level": "level"}, "returns": "bool"},
    "duplicate_of": {"args": {"entity": "entity", "match_fields": "fields", "window_days": "int"},
                     "returns": "bool"},
    "days_between": {"args": {"from": "field", "to": "field"}, "returns": "number"},
    "sum_over_window": {"args": {"field": "field", "group_by": "field", "window_days": "int"},
                        "returns": "number"},
}

TRIGGER_TYPES = frozenset({"EVENT", "BATCH"})
EVENT_TYPES = frozenset(PROCUREMENT_EVENTS)
ACTION_TYPES = frozenset({"CREATE_EXCEPTION", "CREATE_CASE", "NOTIFY_ONLY"})
DEFINITION_KEYS = frozenset({"trigger", "condition", "action", "evidence_capture"})

MAX_DEPTH = 10          # deepest nesting of all / any / not
MAX_NODES = 100         # most conditions in one rule
MAX_PATTERN_LENGTH = 200
CONFIG_REF_PATTERN = r"^config\.[a-z][a-z0-9_]{0,99}$"
