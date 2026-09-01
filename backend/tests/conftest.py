"""Shared fixtures.

`db_session` binds a session to a single connection wrapped in an outer transaction
that's rolled back at the end of every test — the standard SQLAlchemy pattern for
fast, isolated integration tests against a real database without needing a fresh DB
per test. `client` overrides the app's `get_db` dependency with that same session, so
API-level tests get the same isolation as direct repository tests.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import _engine, get_db
from app.main import create_app


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with _engine.connect() as connection:
        outer_transaction = await connection.begin()
        session_factory = async_sessionmaker(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        session = session_factory()
        try:
            yield session
        finally:
            await session.close()
            await outer_transaction.rollback()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
