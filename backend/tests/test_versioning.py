"""Strategy engine persistence + versioning (test (d)).

Uses httpx.MockTransport to stand in for Supabase PostgREST, so the version-bump
logic and the snapshot writes are verified without network. (The same flow is
demonstrated end-to-end against the real database via the Supabase MCP.)
"""
import asyncio
import json

import httpx
import pytest

from app.engine import strategy_engine


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch):
    monkeypatch.setattr(strategy_engine.config, "SUPABASE_REST_URL", "http://rest.test")
    monkeypatch.setattr(strategy_engine.config, "SUPABASE_ANON_KEY", "anon-key")


def test_version_bumps_on_edit():
    captured = {"patch": None, "snapshots": []}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.endswith("/strategies"):
            return httpx.Response(200, json=[{"version": 1}])
        if request.method == "PATCH" and path.endswith("/strategies"):
            body = json.loads(request.content)
            captured["patch"] = body
            return httpx.Response(200, json=[{"id": "s1", "version": body["version"]}])
        if request.method == "POST" and path.endswith("/strategy_versions"):
            captured["snapshots"].append(json.loads(request.content))
            return httpx.Response(201, json=[{}])
        return httpx.Response(404, json={"path": path, "method": request.method})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await strategy_engine.update_strategy(
                strategy_id="s1",
                name="renamed",
                spec={"schema_version": "1.0"},
                token="user-jwt",
                client=client,
            )

    row = asyncio.run(run())
    assert row["version"] == 2  # (d) bumped 1 -> 2
    assert captured["patch"]["version"] == 2
    assert len(captured["snapshots"]) == 1
    assert captured["snapshots"][0]["version"] == 2
    assert captured["snapshots"][0]["strategy_id"] == "s1"


def test_create_writes_v1_and_snapshot():
    captured = {"strategy": None, "snapshots": []}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith("/strategies"):
            body = json.loads(request.content)
            captured["strategy"] = body
            return httpx.Response(201, json=[{"id": "new1", "version": body["version"]}])
        if request.method == "POST" and path.endswith("/strategy_versions"):
            captured["snapshots"].append(json.loads(request.content))
            return httpx.Response(201, json=[{}])
        return httpx.Response(404)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await strategy_engine.create_strategy(
                user_id="u1",
                name="My strat",
                spec={"schema_version": "1.0"},
                token="jwt",
                client=client,
            )

    row = asyncio.run(run())
    assert row["version"] == 1
    assert captured["strategy"]["version"] == 1
    assert captured["snapshots"][0]["version"] == 1
