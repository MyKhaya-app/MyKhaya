from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from mykhaya.config import get_settings

settings = get_settings()
if settings.environment == "test":
    # Pytest creates isolated event loops; pooled asyncpg connections cannot cross them.
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, poolclass=NullPool)
else:
    engine = create_async_engine(
        settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=10
    )


@event.listens_for(engine.sync_engine, "connect")
def set_statement_timeout(dbapi_connection: object, _: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("SET statement_timeout = '10s'")
    cursor.close()


SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
