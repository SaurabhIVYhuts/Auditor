"""case domain allows OTHER

Revision ID: afe40d7ad046
Revises: eb177da98ba0
Create Date: 2026-10-08 12:22:27.560737

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'afe40d7ad046'
down_revision: Union[str, Sequence[str], None] = 'eb177da98ba0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Written by hand: Alembic autogenerate does not detect changes inside a check constraint.
CONSTRAINT = "ck_audit_cases_domain"
RULE_DOMAINS = "'PROCUREMENT', 'INSURANCE', 'BILLING', 'FINANCIAL', 'COMPLIANCE'"


def upgrade() -> None:
    """Case domain also allows OTHER (manual cases that fit no rule domain)."""
    op.drop_constraint(CONSTRAINT, "audit_cases", schema="audit", type_="check")
    op.create_check_constraint(CONSTRAINT, "audit_cases", f"domain IN ({RULE_DOMAINS}, 'OTHER')", schema="audit")


def downgrade() -> None:
    """Fails if any case already uses OTHER (by design: those cases would become invalid)."""
    op.drop_constraint(CONSTRAINT, "audit_cases", schema="audit", type_="check")
    op.create_check_constraint(CONSTRAINT, "audit_cases", f"domain IN ({RULE_DOMAINS})", schema="audit")
