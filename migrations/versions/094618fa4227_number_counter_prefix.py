"""number counter prefix

Revision ID: 094618fa4227
Revises: 2697b0c9dad0
Create Date: 2026-10-09 00:01:11.450032

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '094618fa4227'
down_revision: Union[str, Sequence[str], None] = '2697b0c9dad0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Counters get a prefix (AUD = cases, FND = findings). Existing rows are case counters: 'AUD'."""
    # Adjusted by hand: existing rows need a value, so add with a default, then remove the default.
    op.add_column('audit_case_counters', sa.Column('prefix', sa.String(length=10), nullable=False,
                                                   server_default='AUD'), schema='audit')
    op.alter_column('audit_case_counters', 'prefix', server_default=None, schema='audit')
    op.drop_constraint(op.f('uq_audit_case_counters_tenant_id_year'), 'audit_case_counters', schema='audit', type_='unique')
    op.create_unique_constraint(op.f('uq_audit_case_counters_tenant_id_prefix_year'), 'audit_case_counters', ['tenant_id', 'prefix', 'year'], schema='audit')


def downgrade() -> None:
    """Back to case counters only: other prefixes' counters are removed (they would clash on tenant+year)."""
    op.execute("DELETE FROM audit.audit_case_counters WHERE prefix <> 'AUD'")
    op.drop_constraint(op.f('uq_audit_case_counters_tenant_id_prefix_year'), 'audit_case_counters', schema='audit', type_='unique')
    op.create_unique_constraint(op.f('uq_audit_case_counters_tenant_id_year'), 'audit_case_counters', ['tenant_id', 'year'], schema='audit', postgresql_nulls_not_distinct=False)
    op.drop_column('audit_case_counters', 'prefix', schema='audit')
    # ### end Alembic commands ###
