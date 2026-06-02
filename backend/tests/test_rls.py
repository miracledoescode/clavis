"""RLS cross-user isolation for public.strategies (the `strategies_owner` policy).

Proves the database itself — not just app logic — stops one user from reading,
updating, or deleting another user's strategy. Runs in a rolled-back transaction
under the Postgres `authenticated` role with a forged `request.jwt.claims` GUC,
exactly the way PostgREST sets up an authenticated browser request:

    set local role authenticated;
    select set_config('request.jwt.claims', json_build_object('sub', <uid>)::text, true);
"""
from __future__ import annotations

import json
import uuid

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
    """Insert an auth user; the on_auth_user_created trigger mirrors public.users."""
    uid = uuid.uuid4()
    cur.execute(_AUTH_USER_INSERT, (uid, f"rls_{uid.hex[:12]}@test.clavis"))
    return uid


def _act_as(cur, uid: uuid.UUID) -> None:
    """Drop into the authenticated role so auth.uid() resolves to `uid`."""
    cur.execute("set local role authenticated")
    cur.execute(
        "select set_config('request.jwt.claims', json_build_object('sub', %s::text)::text, true)",
        (str(uid),),
    )


def _reset_role(cur) -> None:
    cur.execute("reset role")
    cur.execute("select set_config('request.jwt.claims', '', true)")


def test_strategies_owner_isolates_cross_user(db_conn):
    cur = db_conn.cursor()

    # Seed two users + a strategy owned by A. Setup runs as the privileged login
    # role, which owns the tables and therefore bypasses RLS.
    user_a = _seed_user(cur)
    user_b = _seed_user(cur)
    cur.execute(
        "insert into public.strategies (user_id, name, strategy_spec) "
        "values (%s, %s, %s::jsonb) returning id",
        (user_a, "A private strategy", json.dumps({"schema_version": "1.0"})),
    )
    strategy_id = cur.fetchone()[0]

    # A sees their own strategy.
    _act_as(cur, user_a)
    cur.execute("select count(*) from public.strategies where id = %s", (strategy_id,))
    assert cur.fetchone()[0] == 1
    _reset_role(cur)

    # B cannot SEE it.
    _act_as(cur, user_b)
    cur.execute("select count(*) from public.strategies where id = %s", (strategy_id,))
    assert cur.fetchone()[0] == 0

    # B cannot UPDATE it: RLS USING hides the row, so 0 rows are affected.
    cur.execute("update public.strategies set name = 'hacked' where id = %s", (strategy_id,))
    assert cur.rowcount == 0

    # B cannot DELETE it: 0 rows affected.
    cur.execute("delete from public.strategies where id = %s", (strategy_id,))
    assert cur.rowcount == 0
    _reset_role(cur)

    # The row is intact and still owned by A.
    cur.execute("select user_id, name from public.strategies where id = %s", (strategy_id,))
    owner, name = cur.fetchone()
    assert owner == user_a
    assert name == "A private strategy"
    # db_conn rolls back -> the seeded users/strategy never persist.
