"""RLS: a user cannot backtest or see another user's strategy / backtests (c).

Same approach as test_rls.py — under the Postgres `authenticated` role with a
forged request.jwt.claims, in a rolled-back transaction. Skips without a
TEST_DATABASE_URL; the same checks are demonstrated on the live DB via MCP.
"""
from __future__ import annotations

import json
import uuid

import pytest

_AUTH_USER_INSERT = """
    insert into auth.users
      (instance_id, id, aud, role, email, encrypted_password,
       email_confirmed_at, created_at, updated_at,
       raw_app_meta_data, raw_user_meta_data)
    values
      ('00000000-0000-0000-0000-000000000000', %s, 'authenticated', 'authenticated',
       %s, 'x', now(), now(), now(), '{}'::jsonb, '{}'::jsonb)
"""


def _seed_user(cur) -> uuid.UUID:
    uid = uuid.uuid4()
    cur.execute(_AUTH_USER_INSERT, (uid, f"bt_{uid.hex[:12]}@test.clavis"))
    return uid


def _act_as(cur, uid: uuid.UUID) -> None:
    cur.execute("set local role authenticated")
    cur.execute(
        "select set_config('request.jwt.claims', json_build_object('sub', %s::text)::text, true)",
        (str(uid),),
    )


def _reset(cur) -> None:
    cur.execute("reset role")
    cur.execute("select set_config('request.jwt.claims', '', true)")


def test_backtest_rls_cross_user(db_conn):
    cur = db_conn.cursor()

    user_a = _seed_user(cur)
    user_b = _seed_user(cur)
    cur.execute(
        "insert into public.strategies (user_id, name, strategy_spec) "
        "values (%s, %s, %s::jsonb) returning id",
        (user_a, "A strategy", json.dumps({"schema_version": "1.0"})),
    )
    strategy_id = cur.fetchone()[0]
    cur.execute(
        "insert into public.backtests (user_id, strategy_id, status, report) "
        "values (%s, %s, 'done', %s::jsonb) returning id",
        (user_a, strategy_id, json.dumps({"disclaimer": "x"})),
    )
    backtest_id = cur.fetchone()[0]

    # A sees both.
    _act_as(cur, user_a)
    cur.execute("select count(*) from public.strategies where id = %s", (strategy_id,))
    assert cur.fetchone()[0] == 1
    cur.execute("select count(*) from public.backtests where id = %s", (backtest_id,))
    assert cur.fetchone()[0] == 1
    _reset(cur)

    # B cannot LOAD A's strategy (so the backtest route returns 404 / never runs)...
    _act_as(cur, user_b)
    cur.execute("select count(*) from public.strategies where id = %s", (strategy_id,))
    assert cur.fetchone()[0] == 0
    # ...nor see A's backtest results.
    cur.execute("select count(*) from public.backtests where id = %s", (backtest_id,))
    assert cur.fetchone()[0] == 0
    # ...nor insert a backtest claiming A's user_id (WITH CHECK violation).
    with pytest.raises(Exception):
        with db_conn.transaction():
            cur.execute(
                "insert into public.backtests (user_id, strategy_id, status) values (%s, %s, 'queued')",
                (user_a, strategy_id),
            )
    _reset(cur)
