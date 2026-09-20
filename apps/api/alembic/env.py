"""Alembic environment bound to the preparation connection when available."""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool

config = context.config
target_metadata = None


def run_migrations_offline() -> None:
    """Generate SQL without connecting when explicitly invoked offline."""

    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations on the session that owns the preparation lock."""

    connection = config.attributes.get("connection")
    if connection is None:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        with connectable.connect() as managed_connection:
            _run_migrations(managed_connection)
        return
    _run_migrations(connection)


def _run_migrations(connection: Connection) -> None:
    """Configure and execute the migration transaction on a sync connection."""

    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
