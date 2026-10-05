"""Shared test helpers (pytest loads this file automatically)."""
import pytest

from shared.db import SessionLocal


@pytest.fixture
def db_session():
    """A database session whose changes are always rolled back after the test."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
