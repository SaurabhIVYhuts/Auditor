"""rename multi-column unique constraints

Revision ID: 4082239430dd
Revises: 28a72430973c
Create Date: 2026-10-07 11:43:16.005184

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4082239430dd'
down_revision: Union[str, Sequence[str], None] = '28a72430973c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RENAMES = [
    ("audit_rules", "uq_audit_rules_tenant_id", "uq_audit_rules_tenant_id_rule_code"),
    ("audit_config", "uq_audit_config_tenant_id", "uq_audit_config_tenant_id_key"),
    ("audit_rule_versions", "uq_audit_rule_versions_rule_id", "uq_audit_rule_versions_rule_id_version"),
]


def upgrade() -> None:
    """Name multi-column unique constraints after ALL their columns."""
    for table, old, new in RENAMES:
        op.execute(f"ALTER TABLE audit.{table} RENAME CONSTRAINT {old} TO {new}")


def downgrade() -> None:
    for table, old, new in RENAMES:
        op.execute(f"ALTER TABLE audit.{table} RENAME CONSTRAINT {new} TO {old}")
