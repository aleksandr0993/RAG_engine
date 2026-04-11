from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.supabase_jwt import decode_supabase_user
from app.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


def get_settings_dep() -> Settings:
    return get_settings()


def get_current_user_optional(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> dict[str, Any] | None:
    if creds is None or creds.scheme.lower() != "bearer":
        return None
    try:
        return decode_supabase_user(creds.credentials, settings)
    except Exception:
        return None


def require_user_for_writes(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    x_user_token: Annotated[str | None, Header(alias="X-User-Token")] = None,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> dict[str, Any] | None:
    """
    When ``require_auth_for_writes`` is true, require a valid Supabase JWT
    (``Authorization: Bearer`` or ``X-User-Token`` for simple clients).
    """
    if not settings.require_auth_for_writes:
        return None
    token = None
    if creds and creds.scheme.lower() == "bearer":
        token = creds.credentials
    elif x_user_token:
        token = x_user_token
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return decode_supabase_user(token, settings)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc


def require_user_for_debug_routes(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    x_user_token: Annotated[str | None, Header(alias="X-User-Token")] = None,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> dict[str, Any] | None:
    """
    When ``require_auth_for_debug_routes`` is true, require a valid Supabase JWT for debug HTTP APIs.
    Same token sources as ``require_user_for_writes`` (``Authorization: Bearer`` or ``X-User-Token``).
    """
    if not settings.require_auth_for_debug_routes:
        return None
    token = None
    if creds and creds.scheme.lower() == "bearer":
        token = creds.credentials
    elif x_user_token:
        token = x_user_token
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required for debug routes")
    try:
        return decode_supabase_user(token, settings)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc


def require_user_for_rl_writes(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    x_user_token: Annotated[str | None, Header(alias="X-User-Token")] = None,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> dict[str, Any] | None:
    """
    When ``require_auth_for_rl_writes`` is true, require a valid Supabase JWT for RL train APIs.
    Mirrors ``require_user_for_writes`` token resolution.
    """
    if not settings.require_auth_for_rl_writes:
        return None
    token = None
    if creds and creds.scheme.lower() == "bearer":
        token = creds.credentials
    elif x_user_token:
        token = x_user_token
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required for RL training APIs")
    try:
        return decode_supabase_user(token, settings)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc
