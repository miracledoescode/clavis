"""Strategy versioning at the database layer (mirrors the Strategy Engine path).

`strategy_engine.create_strategy` writes version 1 + a snapshot; `update_strategy`
reads the current version, bumps it, and writes a new snapshot. This test runs that
exact sequence against the real schema and asserts the invariants the engine relies
on — including the `unique (strategy_id, version)` guard that makes snapshots
immutable. The engine's HTTP/PostgREST code path itself is covered by
test_versioning.py. Runs in a rolled-back transaction so nothing persists.
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
    cur.execute(_AUTH_USER_INSERT, (uid, f"eng_{uid.hex[:12]}@test.clavis"))
    return uid


def test_edit_bumps_version_and_snapshots(db_conn, psycopg_module):
    cur = db_conn.cursor()
    user_id = _seed_user(cur)

    # create_strategy: version 1 + first snapshot.
    spec_v1 = json.dumps({"schema_version": "1.0", "name": "v1"})
    cur.execute(
        "insert into public.strategies (user_id, name, strategy_spec, version) "
        "values (%s, 'My strategy', %s::jsonb, 1) returning id",
        (user_id, spec_v1),
    )
    strategy_id = cur.fetchone()[0]
    cur.execute(
        "insert into public.strategy_versions (strategy_id, version, spec_snapshot) "
        "values (%s, 1, %s::jsonb)",
        (strategy_id, spec_v1),
    )

    # update_strategy: read current version, bump, write a new snapshot.
    cur.execute("select version from public.strategies where id = %s", (strategy_id,))
    assert cur.fetchone()[0] == 1
    spec_v2 = json.dumps({"schema_version": "1.0", "name": "v2"})
    cur.execute(
        "update public.strategies set version = 2, strategy_spec = %s::jsonb, updated_at = now() "
        "where id = %s",
        (spec_v2, strategy_id),
    )
    cur.execute(
        "insert into public.strategy_versions (strategy_id, version, spec_snapshot) "
        "values (%s, 2, %s::jsonb)",
        (strategy_id, spec_v2),
    )

    # strategies.version is now 2.
    cur.execute("select version from public.strategies where id = %s", (strategy_id,))
    assert cur.fetchone()[0] == 2

    # Two immutable snapshots exist: versions 1 and 2.
    cur.execute(
        "select version from public.strategy_versions where strategy_id = %s order by version",
        (strategy_id,),
    )
    assert [r[0] for r in cur.fetchall()] == [1, 2]

    # A duplicate (strategy_id, version) is rejected by the unique constraint.
    # The savepoint keeps the outer transaction usable after the expected error.
    with pytest.raises(psycopg_module.errors.UniqueViolation):
        with db_conn.transaction():
            cur.execute(
                "insert into public.strategy_versions (strategy_id, version, spec_snapshot) "
                "values (%s, 2, %s::jsonb)",
                (strategy_id, spec_v2),
            )
    # db_conn rolls back -> nothing persists.
