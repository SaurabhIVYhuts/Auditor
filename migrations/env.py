"""Alembic migration environment for the Auditor Agent.

- Database URL comes from .env via shared.config (never from alembic.ini).
- Only the 'audit' schema is managed; the version table also lives there.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

import shared.audit_log  # noqa: F401  (registers the placeholder platform tables on SharedBase)
import shared.notifications  # noqa: F401
from agents.audit.models import AUDIT_SCHEMA, AuditBase
from shared.config import settings
from shared.models import SharedBase

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# '%' must be doubled for Alembic's config parser.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

# Agent tables plus placeholder platform tables (shared/), both in the "audit" schema.
target_metadata = [AuditBase.metadata, SharedBase.metadata]


def include_name(name, type_, parent_names):
    """Only look at our own schema; ignore 'public' and anything else."""
    if type_ == "schema":
        return name == AUDIT_SCHEMA
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=AUDIT_SCHEMA,
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {AUDIT_SCHEMA}"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=AUDIT_SCHEMA,
            include_schemas=True,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
