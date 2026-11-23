import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from mykhaya import models  # noqa: F401
from mykhaya.config import get_migration_settings
from mykhaya.db_base import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
# MigrationSettings, not Settings: migrations never need MYKHAYA_SECRET_KEY,
# and nothing imported here may construct the application Settings.
# The URL stays a SQLAlchemy URL object (SEC-086/086a): it is never written
# into Alembic's configuration, whose interpolation would also misread a
# percent-encoded password, and a file-backed password is attached in-process.
database_url = get_migration_settings().database_connect_url()
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    # Offline mode only renders SQL; it never connects, so no password is needed.
    context.configure(
        url=database_url.set(password=None),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: object) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
