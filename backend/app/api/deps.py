"""Request dependencies — Supabase JWT authentication.

The wiring is real: this dependency runs on protected routes and extracts the
bearer token. The signature VERIFICATION is a scaffold stub — replace the TODO
with RS256 verification against the Supabase JWKS before any non-stub use.

There is intentionally no JWT library import yet, so ``requirements.txt`` stays
limited to the named runtime deps. ``PyJWT[crypto]`` is the planned dependency
for the real check.
"""
from __future__ import annotations

from fastapi import Header, HTTPException, status


async def get_current_user(
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Verify the Supabase JWT and return the authenticated principal.

    SCAFFOLD STUB: structure only. A Bearer token must be present, but its
    signature and claims are NOT yet verified.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    # TODO(auth): verify the RS256 signature against the Supabase JWKS; validate
    #             aud / iss / exp; derive user_id from the `sub` claim.
    return {"user_id": "stub-user", "token": token}
