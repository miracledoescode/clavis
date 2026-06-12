"""Tests for app.integrations.telegram.set_webhook.

httpx.MockTransport stands in for the Telegram Bot API — no real network.
"""
from __future__ import annotations

import asyncio
import json

import httpx

from app.integrations.telegram import set_webhook

run = asyncio.run


def test_set_webhook_posts_url_and_secret():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await set_webhook("tok123", "https://example.com/telegram/webhook", "shh", client=client)

    run(go())

    assert captured["url"] == "https://api.telegram.org/bottok123/setWebhook"
    assert captured["body"] == {"url": "https://example.com/telegram/webhook", "secret_token": "shh"}


def test_set_webhook_without_secret_sends_none():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await set_webhook("tok123", "https://example.com/telegram/webhook", client=client)

    run(go())

    assert captured["body"]["secret_token"] is None
