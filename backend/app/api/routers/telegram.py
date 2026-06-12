"""Telegram webhook router — Approve/Reject callback queries.

Telegram calls this when the trader taps a Co-Pilot proposal's inline keyboard
(see integrations/telegram.py, which sends `callback_data` of the form
"approve:<proposal_id>" / "reject:<proposal_id>"). This router resolves the
proposal to the AgentLoop that owns it (via AgentLoopRegistry) and feeds the
decision into AgentLoop.on_approval / AgentLoop.on_rejection.

Verification: Telegram does not sign webhook bodies. Instead, when the webhook
is registered with a `secret_token` (setWebhook), Telegram echoes it back as the
`X-Telegram-Bot-Api-Secret-Token` header on every call — requests where it
doesn't match are rejected (constant-time compare). If
`config.TELEGRAM_WEBHOOK_SECRET` is unset, verification is skipped (local dev
only).

This route is NOT under the `/v1` prefix used by routes.py — it is an
unauthenticated (Telegram-authenticated) webhook, not a Supabase-JWT API call.
"""
from __future__ import annotations

import hmac
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app import config
from app.engine.agent_loop import AgentLoopRegistry

router = APIRouter(prefix="/telegram", tags=["telegram"])


def get_agent_loop_registry() -> AgentLoopRegistry:
    """Wired to the live engine runner's registry. Tests override this."""
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Agent loop registry is not configured",
    )


def _verify_secret(secret_token: Optional[str]) -> None:
    expected = config.TELEGRAM_WEBHOOK_SECRET
    if not expected:
        return  # not configured: accept (local dev only)
    if not secret_token or not hmac.compare_digest(secret_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")


@router.post("/webhook")
async def telegram_webhook(
    update: dict,
    registry: AgentLoopRegistry = Depends(get_agent_loop_registry),
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
) -> dict:
    _verify_secret(x_telegram_bot_api_secret_token)

    callback = update.get("callback_query")
    if not callback:
        return {"ok": True}  # not a button tap (e.g. /start) — nothing to do

    action, _, proposal_id = str(callback.get("data", "")).partition(":")
    if action not in ("approve", "reject") or not proposal_id:
        return {"ok": True}

    loop = await registry.get_loop_for_proposal(proposal_id)
    if loop is None:
        return {"ok": True}  # unknown/expired proposal — nothing to do

    if action == "approve":
        used_keys = await loop.state_store.used_idempotency_keys()
        await loop.on_approval(proposal_id, used_keys)
    else:
        await loop.on_rejection(proposal_id)

    callback_id = callback.get("id")
    if callback_id:
        await loop.telegram.answer_callback_query(callback_id)

    return {"ok": True}
