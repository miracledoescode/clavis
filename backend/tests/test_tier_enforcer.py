"""Tier enforcer: pure tier/feature mapping + Supabase-backed lookups.

The pure functions (`tier_for_subscription`, `has_feature`, `live_agent_limit`,
`can_deploy_live_agent`) need no I/O. `check_feature_access` /
`check_live_agent_limit` add the `subscriptions` lookup, exercised here against
`httpx.MockTransport` (same pattern as test_versioning.py) — no network or DB.
"""
import asyncio

import httpx
import pytest

from app.engine.tier_enforcer import (
    Feature,
    Tier,
    can_deploy_live_agent,
    check_feature_access,
    check_live_agent_limit,
    get_tier,
    has_feature,
    live_agent_limit,
    tier_for_subscription,
)


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch):
    monkeypatch.setattr("app.engine.tier_enforcer.config.SUPABASE_REST_URL", "http://rest.test")
    monkeypatch.setattr("app.engine.tier_enforcer.config.SUPABASE_SERVICE_ROLE_KEY", "service-key")


# --------------------------------------------------------------------------- #
# tier_for_subscription                                                        #
# --------------------------------------------------------------------------- #
def test_no_subscription_is_free():
    assert tier_for_subscription(None) == Tier.FREE


@pytest.mark.parametrize("status", ["canceled", "past_due", "weird"])
def test_inactive_subscription_is_free(status):
    assert tier_for_subscription({"tier": "titan", "status": status}) == Tier.FREE


@pytest.mark.parametrize("status", ["active", "trialing"])
@pytest.mark.parametrize(
    "tier_str,expected",
    [("explorer", Tier.EXPLORER), ("navigator", Tier.NAVIGATOR), ("titan", Tier.TITAN)],
)
def test_active_or_trialing_subscription_maps_tier(status, tier_str, expected):
    assert tier_for_subscription({"tier": tier_str, "status": status}) == expected


def test_unknown_tier_string_is_free():
    assert tier_for_subscription({"tier": "enterprise", "status": "active"}) == Tier.FREE


# --------------------------------------------------------------------------- #
# has_feature                                                                  #
# --------------------------------------------------------------------------- #
def test_free_has_no_gated_features():
    for feature in Feature:
        assert has_feature(Tier.FREE, feature) is False


def test_live_deploy_requires_explorer_or_above():
    assert has_feature(Tier.FREE, Feature.LIVE_DEPLOY) is False
    assert has_feature(Tier.EXPLORER, Feature.LIVE_DEPLOY) is True
    assert has_feature(Tier.NAVIGATOR, Feature.LIVE_DEPLOY) is True
    assert has_feature(Tier.TITAN, Feature.LIVE_DEPLOY) is True


@pytest.mark.parametrize("feature", [Feature.MULTI_LEG_TP, Feature.PRIORITY_EXECUTION])
def test_titan_only_features(feature):
    assert has_feature(Tier.NAVIGATOR, feature) is False
    assert has_feature(Tier.TITAN, feature) is True


# --------------------------------------------------------------------------- #
# live_agent_limit / can_deploy_live_agent                                     #
# --------------------------------------------------------------------------- #
def test_live_agent_limits_per_tier():
    assert live_agent_limit(Tier.FREE) == 0
    assert live_agent_limit(Tier.EXPLORER) == 1
    assert live_agent_limit(Tier.NAVIGATOR) == 5
    assert live_agent_limit(Tier.TITAN) is None


def test_free_cannot_deploy_any_live_agent():
    assert can_deploy_live_agent(Tier.FREE, current_live_agents=0) is False


def test_explorer_can_deploy_one_then_blocked():
    assert can_deploy_live_agent(Tier.EXPLORER, current_live_agents=0) is True
    assert can_deploy_live_agent(Tier.EXPLORER, current_live_agents=1) is False


def test_navigator_allows_several_then_blocked():
    assert can_deploy_live_agent(Tier.NAVIGATOR, current_live_agents=4) is True
    assert can_deploy_live_agent(Tier.NAVIGATOR, current_live_agents=5) is False


def test_titan_is_unlimited():
    assert can_deploy_live_agent(Tier.TITAN, current_live_agents=10_000) is True


# --------------------------------------------------------------------------- #
# Supabase-backed checks (mocked transport)                                    #
# --------------------------------------------------------------------------- #
def _client_for(rows):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/subscriptions")
        assert request.headers["apikey"] == "service-key"
        return httpx.Response(200, json=rows)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_get_tier_no_row_is_free():
    async def run():
        async with _client_for([]) as client:
            return await get_tier("u1", client=client)

    assert asyncio.run(run()) == Tier.FREE


def test_get_tier_returns_subscribed_tier():
    async def run():
        async with _client_for([{"tier": "navigator", "status": "active"}]) as client:
            return await get_tier("u1", client=client)

    assert asyncio.run(run()) == Tier.NAVIGATOR


def test_check_feature_access_gates_on_tier():
    async def run():
        async with _client_for([{"tier": "explorer", "status": "active"}]) as client:
            live = await check_feature_access("u1", Feature.LIVE_DEPLOY, client=client)
            multi_leg = await check_feature_access("u1", Feature.MULTI_LEG_TP, client=client)
            return live, multi_leg

    live, multi_leg = asyncio.run(run())
    assert live is True
    assert multi_leg is False


def test_check_live_agent_limit_uses_tier_limit():
    async def run():
        async with _client_for([{"tier": "explorer", "status": "active"}]) as client:
            ok_first = await check_live_agent_limit("u1", 0, client=client)
            ok_second = await check_live_agent_limit("u1", 1, client=client)
            return ok_first, ok_second

    ok_first, ok_second = asyncio.run(run())
    assert ok_first is True
    assert ok_second is False
