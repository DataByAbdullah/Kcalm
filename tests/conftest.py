import pytest
from sqlalchemy import delete, inspect
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import engine
from app.models.rate_limit import RateLimitBucket


@pytest.fixture(autouse=True)
def isolate_rate_limit_buckets():
    """Tests share a client IP; each test must start with its own quota.

    Keep the real limiter and configured defaults active. Database-independent
    tests can still run when PostgreSQL is unavailable, like the existing suites.
    """
    try:
        with engine.begin() as connection:
            if inspect(connection).has_table(RateLimitBucket.__tablename__):
                connection.execute(delete(RateLimitBucket))
    except SQLAlchemyError:
        pass
