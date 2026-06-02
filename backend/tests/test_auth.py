"""Real RS256 verification of Supabase access tokens.

Uses a locally generated RSA keypair and a fake JWKS client so the signature
path is exercised without any network — the same code path used in production
against the project JWKS.
"""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.api import deps

ISSUER = "https://proj.supabase.co/auth/v1"


@pytest.fixture
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _make_token(key, **overrides):
    claims = {
        "sub": "11111111-1111-4111-8111-111111111111",
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-kid"})


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


def _patch(monkeypatch, public_key):
    class FakeJWKS:
        def get_signing_key_from_jwt(self, token):
            return _FakeSigningKey(public_key)

    monkeypatch.setattr(deps, "_jwks_client", lambda: FakeJWKS())
    monkeypatch.setattr(deps.config, "SUPABASE_JWT_ISSUER", ISSUER)
    monkeypatch.setattr(deps.config, "SUPABASE_JWT_AUDIENCE", "authenticated")


def test_verify_valid_rs256_token(monkeypatch, rsa_key):
    token = _make_token(rsa_key)
    _patch(monkeypatch, rsa_key.public_key())
    claims = deps.verify_token(token)
    assert claims["sub"] == "11111111-1111-4111-8111-111111111111"


def test_reject_token_signed_by_other_key(monkeypatch, rsa_key):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _make_token(rsa_key)  # signed by rsa_key ...
    _patch(monkeypatch, other.public_key())  # ... but JWKS returns a different key
    with pytest.raises(Exception):
        deps.verify_token(token)


def test_reject_expired_token(monkeypatch, rsa_key):
    token = _make_token(rsa_key, exp=int(time.time()) - 10)
    _patch(monkeypatch, rsa_key.public_key())
    with pytest.raises(Exception):
        deps.verify_token(token)


def test_reject_wrong_audience(monkeypatch, rsa_key):
    token = _make_token(rsa_key, aud="some-other-audience")
    _patch(monkeypatch, rsa_key.public_key())
    with pytest.raises(Exception):
        deps.verify_token(token)
