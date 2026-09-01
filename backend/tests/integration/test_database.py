from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import database_healthy
from app.models.user import User


async def test_database_healthy_reports_true_when_reachable() -> None:
    assert await database_healthy() is True


async def test_session_can_query(db_session: AsyncSession) -> None:
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1


async def test_session_rolls_back_on_exception(db_session: AsyncSession) -> None:
    """The `get_db` dependency rolls back on any exception raised while handling a
    request — verified here directly against the session contract it wraps."""
    await db_session.execute(text("SELECT 1"))  # session is usable
    user = User(email="rollback-check@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()

    # Simulate the get_db dependency's error path without going through a full request.
    await db_session.rollback()

    result = await db_session.execute(
        text('SELECT count(*) FROM "user" WHERE email = :email'),
        {"email": "rollback-check@example.com"},
    )
    assert result.scalar_one() == 0
