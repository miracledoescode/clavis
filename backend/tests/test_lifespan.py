"""main.py lifespan: starts/stops the LiveRunner and registers the Telegram
webhook when configured; no-ops otherwise (existing 233+ tests rely on the
no-op path — see test_telegram_webhook.py::test_registry_not_configured_returns_503).
"""
from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.routers.deploy import get_live_runner
from app.api.routers.telegram import get_agent_loop_registry
from app.main import app


class FakeLiveRunner:
    instances: list["FakeLiveRunner"] = []

    def __init__(self) -> None:
        self.registry = object()
        self.start = AsyncMock()
        self.stop = AsyncMock()
        FakeLiveRunner.instances.append(self)


def test_lifespan_starts_runner_and_registers_overrides(monkeypatch):
    FakeLiveRunner.instances.clear()
    monkeypatch.setattr("app.main.config.live_runner_configured", lambda: True)
    monkeypatch.setattr("app.main.LiveRunner", FakeLiveRunner)
    monkeypatch.setattr("app.main.config.TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr("app.main.config.TELEGRAM_WEBHOOK_URL", "")

    with TestClient(app) as client:
        runner = FakeLiveRunner.instances[0]
        runner.start.assert_awaited_once()
        assert app.dependency_overrides[get_agent_loop_registry]() is runner.registry
        assert app.dependency_overrides[get_live_runner]() is runner

    runner.stop.assert_awaited_once()
    assert get_agent_loop_registry not in app.dependency_overrides
    assert get_live_runner not in app.dependency_overrides


def test_lifespan_noop_when_not_configured(monkeypatch):
    FakeLiveRunner.instances.clear()
    monkeypatch.setattr("app.main.config.live_runner_configured", lambda: False)
    monkeypatch.setattr("app.main.LiveRunner", FakeLiveRunner)
    monkeypatch.setattr("app.main.config.TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr("app.main.config.TELEGRAM_WEBHOOK_URL", "")

    with TestClient(app):
        assert FakeLiveRunner.instances == []
        assert get_agent_loop_registry not in app.dependency_overrides
        assert get_live_runner not in app.dependency_overrides


def test_lifespan_registers_telegram_webhook_when_configured(monkeypatch):
    FakeLiveRunner.instances.clear()
    monkeypatch.setattr("app.main.config.live_runner_configured", lambda: False)
    monkeypatch.setattr("app.main.LiveRunner", FakeLiveRunner)
    monkeypatch.setattr("app.main.config.TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setattr("app.main.config.TELEGRAM_WEBHOOK_URL", "https://example.com/telegram/webhook")
    monkeypatch.setattr("app.main.config.TELEGRAM_WEBHOOK_SECRET", "shh")

    fake_set_webhook = AsyncMock()
    monkeypatch.setattr("app.main.set_webhook", fake_set_webhook)

    with TestClient(app):
        pass

    fake_set_webhook.assert_awaited_once_with("tok123", "https://example.com/telegram/webhook", "shh")
