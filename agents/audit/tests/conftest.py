"""Shared test helpers (pytest loads this file automatically)."""
import pytest
from sqlalchemy.orm import Session

from shared.db import engine


@pytest.fixture
def db_session():
    """A database session whose changes are ALWAYS undone after the test.

    Everything runs inside one outer transaction that is rolled back at the end.
    Even db.commit() inside the code only releases a savepoint, so tests never leave data behind.
    """
    connection = engine.connect()
    outer = connection.begin()
    db = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield db
    finally:
        db.close()
        outer.rollback()
        connection.close()
