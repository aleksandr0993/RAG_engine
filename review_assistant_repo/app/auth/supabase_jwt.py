"""Decode Supabase JWTs (HS256 secret or RS256 via JWKS)."""

from __future__ import annotations

from typing import Any

import jwt
from jwt import PyJWKClient

from app.config import Settings


def decode_supabase_user(token: str, settings: Settings) -> dict[str, Any]:
    """
    Return JWT payload (``sub``, ``email``, ``user_metadata``, …) or raise ``jwt.PyJWTError``.
    """
    token = (token or "").strip()
    if not token:
        raise jwt.InvalidTokenError("empty token")

    opts_strict = {"verify_aud": True}
    opts_loose = {"verify_aud": False}

    if settings.supabase_jwt_secret and str(settings.supabase_jwt_secret).strip():
        secret = str(settings.supabase_jwt_secret).strip()
        try:
            return jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                audience="authenticated",
                options=opts_strict,
            )
        except jwt.InvalidAudienceError:
            return jwt.decode(token, secret, algorithms=["HS256"], options=opts_loose)

    if settings.supabase_jwks_url and str(settings.supabase_jwks_url).strip():
        jwks = PyJWKClient(str(settings.supabase_jwks_url).strip())
        signing_key = jwks.get_signing_key_from_jwt(token)
        try:
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience="authenticated",
                options=opts_strict,
            )
        except jwt.InvalidAudienceError:
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                options=opts_loose,
            )

    raise jwt.InvalidTokenError("supabase_jwt_secret or supabase_jwks_url must be configured")
