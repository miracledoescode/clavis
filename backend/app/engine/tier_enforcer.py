"""Tier enforcer: tier gating + billing checks.

Gates tier-locked capabilities against the trader's subscription tier
(`public.subscriptions`; see `db/clavis_billing_schema.sql`). A trader with no
row, or a row whose `status` is not `active`/`trialing`, is FREE (paper only) —
`subscriptions.tier` itself only ever stores `'explorer' | 'navigator' | 'titan'`.

The pure mapping (`has_feature`, `live_agent_limit`, `can_deploy_live_agent`,
`tier_for_subscription`) needs no I/O and is exhaustively unit tested. The
`check_*` functions add the Supabase lookup, following the
`engine/strategy_engine.py` pattern: an optional injected `httpx.AsyncClient`
for tests (see `tests/test_versioning.py`'s `httpx.MockTransport`), a
service-role client otherwise (CLAUDE.md: "the engine uses the service role
key").
"""
from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Optional

import httpx

from app import config


class Tier(str, Enum):
    FREE = "free"
    EXPLORER = "explorer"
    NAVIGATOR = "navigator"
    TITAN = "titan"


class Feature(str, Enum):
    MULTI_LEG_TP = "multi_leg_tp"
    LIVE_DEPLOY = "live_deploy"
    PRIORITY_EXECUTION = "priority_execution"


# Ordered low -> high; index comparison drives `has_feature`.
_TIER_ORDER: list[Tier] = [Tier.FREE, Tier.EXPLORER, Tier.NAVIGATOR, Tier.TITAN]

# Minimum tier required to unlock each gated feature.
FEATURE_MIN_TIER: dict[Feature, Tier] = {
    Feature.LIVE_DEPLOY: Tier.EXPLORER,
    Feature.MULTI_LEG_TP: Tier.TITAN,
    Feature.PRIORITY_EXECUTION: Tier.TITAN,
}

# Concurrent live Agents allowed per tier. None == unlimited.
# "Several" (Navigator, landing-page copy) is a configurable heuristic, not a
# contractual promise.
LIVE_AGENT_LIMITS: dict[Tier, Optional[int]] = {
    Tier.FREE: 0,
    Tier.EXPLORER: 1,
    Tier.NAVIGATOR: 5,
    Tier.TITAN: None,
}

# subscriptions.status values that count as a paid tier (clavis_billing_schema.sql).
_ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}


# --------------------------------------------------------------------------- #
# Pure mapping (no I/O)                                                        #
# --------------------------------------------------------------------------- #
def tier_for_subscription(subscription: Optional[Mapping[str, Any]]) -> Tier:
    """Map a `subscriptions` row to a Tier. No row, or an inactive row -> FREE."""
    if subscription is None:
        return Tier.FREE
    if subscription.get("status") not in _ACTIVE_SUBSCRIPTION_STATUSES:
        return Tier.FREE
    try:
        return Tier(subscription.get("tier"))
    except ValueError:
        return Tier.FREE


def has_feature(tier: Tier, feature: Feature) -> bool:
    """True if `tier` unlocks `feature`."""
    return _TIER_ORDER.index(tier) >= _TIER_ORDER.index(FEATURE_MIN_TIER[feature])


def live_agent_limit(tier: Tier) -> Optional[int]:
    """Max concurrent live Agents for `tier`. None == unlimited."""
    return LIVE_AGENT_LIMITS[tier]


def can_deploy_live_agent(tier: Tier, current_live_agents: int) -> bool:
    """True if `tier` may deploy one more live Agent given `current_live_agents`."""
    if not has_feature(tier, Feature.LIVE_DEPLOY):
        return False
    limit = live_agent_limit(tier)
    return limit is None or current_live_agents < limit


# --------------------------------------------------------------------------- #
# Supabase-backed lookups (engine-side; service role)                         #
# --------------------------------------------------------------------------- #
def _service_headers() -> dict[str, str]:
    return {
        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
    }


def _url(path: str) -> str:
    return f"{config.SUPABASE_REST_URL}/{path}"


async def _with_client(client: Optional[httpx.AsyncClient]):
    if client is not None:
        return client, False
    return httpx.AsyncClient(timeout=10.0), True


async def get_subscription(
    user_id: str, *, client: Optional[httpx.AsyncClient] = None
) -> Optional[dict[str, Any]]:
    """The trader's `subscriptions` row, or None if they have never subscribed."""
    c, owns = await _with_client(client)
    try:
        resp = await c.get(
            _url("subscriptions"),
            headers=_service_headers(),
            params={"user_id": f"eq.{user_id}", "select": "tier,status", "limit": "1"},
        )
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None
    finally:
        if owns:
            await c.aclose()


async def get_tier(user_id: str, *, client: Optional[httpx.AsyncClient] = None) -> Tier:
    """The trader's effective Tier (FREE if unsubscribed/inactive)."""
    return tier_for_subscription(await get_subscription(user_id, client=client))


async def check_feature_access(
    user_id: str, feature: Feature, *, client: Optional[httpx.AsyncClient] = None
) -> bool:
    """True if the trader's current tier unlocks `feature`."""
    return has_feature(await get_tier(user_id, client=client), feature)


async def check_live_agent_limit(
    user_id: str, current_live_agents: int, *, client: Optional[httpx.AsyncClient] = None
) -> bool:
    """True if the trader may deploy one more live Agent right now."""
    return can_deploy_live_agent(await get_tier(user_id, client=client), current_live_agents)
