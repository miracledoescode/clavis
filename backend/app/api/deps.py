"""Request dependencies — real Supabase JWT verification.

Replaces the slice-1 stub. Every protected route depends on `get_current_user`,
which verifies the caller's Supabase access token and returns the principal
(user_id + the raw token, so engine-mediated writes can run under the user's
authenticated context — never the service role).

Supabase issues asymmetric (RS256/ES256) access tokens when JWT signing keys are
enabled; we verify the signature against the project JWKS and check exp / aud /
iss. A legacy HS256 shared-secret path is supported only if SUPABASE_JWT_SECRET
is configured.
"""
from __future__ import annotations

from typing import Optional

import jwt
from fastapi import Header, HTTPException, status
from jwt import PyJWKClient

from app import config

_ASYMMETRIC_ALGS = ("RS256", "ES256", "EdDSA")

# Cached JWKS client (lazily built; isolated in a getter so tests can patch it).
_JWKS_CLIENT: Optional[PyJWKClient] = None


def _jwks_client() -> PyJWKClient:
    global _JWKS_CLIENT
    if _JWKS_CLIENT is None:
        if not config.SUPABASE_JWKS_URL:
            raise RuntimeError("SUPABASE_JWKS_URL is not configured")
        _JWKS_CLIENT = PyJWKClient(config.SUPABASE_JWKS_URL)
    return _JWKS_CLIENT


def verify_token(token: str) -> dict:
    """Verify a Supabase access token and return its claims. Raises on failure."""
    header = jwt.get_unverified_header(token)
    alg = header.get("alg", "")
    decode_kwargs = dict(
        audience=config.SUPABASE_JWT_AUDIENCE,
        options={"require": ["exp", "sub"]},
    )
    if config.SUPABASE_JWT_ISSUER:
        decode_kwargs["issuer"] = config.SUPABASE_JWT_ISSUER

    if alg in _ASYMMETRIC_ALGS:
        signing_key = _jwks_client().get_signing_key_from_jwt(token).key
        return jwt.decode(token, signing_key, algorithms=list(_ASYMMETRIC_ALGS), **decode_kwargs)

    if alg == "HS256":
        if not config.SUPABASE_JWT_SECRET:
            raise ValueError("HS256 token received but SUPABASE_JWT_SECRET is not set")
        return jwt.decode(token, config.SUPABASE_JWT_SECRET, algorithms=["HS256"], **decode_kwargs)

    raise ValueError(f"Unsupported JWT alg: {alg!r}")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    """Authenticate the request via the Supabase bearer token."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized("Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = verify_token(token)
    except Exception as exc:  # noqa: BLE001 - surface any verification failure as 401
        raise _unauthorized(f"Invalid token: {exc}")
    user_id = claims.get("sub")
    if not user_id:
        raise _unauthorized("Token missing 'sub' claim")
    return {"user_id": user_id, "token": token, "claims": claims}
