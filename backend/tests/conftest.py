"""Shared pytest fixtures.

The DB-backed tests (test_rls.py, test_strategy_engine.py) exercise the real
Postgres safety surfaces — RLS and the versioning constraints — that unit tests
with mocks cannot reach. Point them at a TEST database with the Clavis schema
applied via TEST_DATABASE_URL (or SUPABASE_DB_URL / DATABASE_URL). Each test runs
inside a transaction that is ALWAYS rolled back, so nothing persists and
production data is never touched.

When no reachable database is configured these tests SKIP, so the rest of the
suite (contract, parse, auth, versioning-unit) still runs anywhere.
"""
from __future__ import annotations

import os

import pytest

_DSN_ENV_VARS = ("TEST_DATABASE_URL", "SUPABASE_DB_URL", "DATABASE_URL")


def _test_dsn() -> str | None:
    for var in _DSN_ENV_VARS:
        value = os.getenv(var)
        if value:
            return value
    return None


@pytest.fixture(scope="session")
def psycopg_module():
    try:
        import psycopg
    except ImportError:  # pragma: no cover - environment dependent
        pytest.skip("psycopg is not installed (pip install -r requirements-dev.txt)")
    return psycopg


@pytest.fixture
def db_conn(psycopg_module):
    """A DB connection whose work is always rolled back at the end of the test."""
    dsn = _test_dsn()
    if not dsn:
        pytest.skip(
            "No test database configured. Set TEST_DATABASE_URL to a Postgres "
            "instance with the Clavis schema applied to run DB-backed tests."
        )
    try:
        conn = psycopg_module.connect(dsn, connect_timeout=5, autocommit=False)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Test database not reachable: {exc}")
    try:
        yield conn
    finally:
        conn.rollback()  # nothing the test did is ever committed
        conn.close()
