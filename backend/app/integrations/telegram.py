"""Telegram integration — delivers Agent proposals (Approve/Reject) and alerts.

Implements TelegramNotifier (from agent_loop). Uses the Telegram Bot API
directly via httpx.

Proposal message format:
  📊 EURUSD LONG  •  H1 Setup
  Entry  1.08500   SL  1.08000   TP  1.09500
  Confidence: 70%
  "Setup 'EMA Cross' conditions matched on H1"
  ✅ Approve   ❌ Reject   (inline keyboard)
  Expires in 5 min.

Inline keyboard callback data:
  "approve:<proposal_id>"  /  "reject:<proposal_id>"

The FastAPI Telegram webhook handler (api/routers/telegram.py) will parse
callback_query.data and call loop.on_approval / loop.on_rejection.
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

from app import config
from app.engine.agent_loop import ActiveProposal

_TELEGRAM_API = "https://api.telegram.org"


def _direction_emoji(direction: str) -> str:
    return "📈" if direction == "long" else "📉"


def _format_proposal(proposal: ActiveProposal) -> str:
    tps = "  ".join(f"{p:.5f}" for p in proposal.take_profit_prices)
    return (
        f"{_direction_emoji(proposal.direction)} "
        f"*{proposal.symbol}* {proposal.direction.upper()}\n"
        f"Entry `{proposal.entry_price:.5f}`  "
        f"SL `{proposal.stop_loss_price:.5f}`  "
        f"TP `{tps}`\n"
        f"Confidence: {int(proposal.confidence_score * 100)}%\n"
        f"_{proposal.rationale}_\n\n"
        f"Expires in 5 min."
    )


async def set_webhook(
    token: str,
    url: str,
    secret_token: str = "",
    client: Optional[httpx.AsyncClient] = None,
) -> None:
    """Register `url` as the Telegram Bot API webhook for `token`.

    Idempotent — Telegram's setWebhook is safe to call repeatedly with the
    same URL. Called once from main.py's lifespan on startup.
    """
    owns_client = client is None
    c = client or httpx.AsyncClient(timeout=10.0)
    try:
        await c.post(
            f"{_TELEGRAM_API}/bot{token}/setWebhook",
            json={"url": url, "secret_token": secret_token or None},
        )
    finally:
        if owns_client:
            await c.aclose()


class TelegramBotNotifier:
    """Sends proposals and invalidation notices via the Telegram Bot API."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        self._client = client
        self._owns_client = client is None

    async def _get(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    def _api(self, method: str) -> str:
        return f"{_TELEGRAM_API}/bot{self._token}/{method}"

    async def send_proposal(self, proposal: ActiveProposal) -> None:
        c = await self._get()
        await c.post(
            self._api("sendMessage"),
            json={
                "chat_id": self._chat_id,
                "text": _format_proposal(proposal),
                "parse_mode": "Markdown",
                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {
                                "text": "✅ Approve",
                                "callback_data": f"approve:{proposal.proposal_id}",
                            },
                            {
                                "text": "❌ Reject",
                                "callback_data": f"reject:{proposal.proposal_id}",
                            },
                        ]
                    ]
                },
            },
        )

    async def send_invalidation(self, proposal_id: str, reason: str) -> None:
        c = await self._get()
        await c.post(
            self._api("sendMessage"),
            json={
                "chat_id": self._chat_id,
                "text": f"⚠️ Proposal invalidated: {reason}",
            },
        )

    async def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None) -> None:
        """Dismiss the inline keyboard's loading spinner after a tap is handled."""
        c = await self._get()
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        await c.post(self._api("answerCallbackQuery"), json=payload)

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
