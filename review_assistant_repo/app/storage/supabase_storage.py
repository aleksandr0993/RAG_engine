"""Upload files to Supabase Storage (optional; uses service role key on the server)."""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

import httpx

from app.config import Settings, get_settings

log = logging.getLogger(__name__)


def supabase_storage_configured(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return bool(
        s.supabase_url
        and str(s.supabase_url).strip()
        and s.supabase_service_role_key
        and str(s.supabase_service_role_key).strip()
    )


def upload_file(
    *,
    object_path: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    settings: Settings | None = None,
) -> str:
    """
    PUT object to ``{supabase_url}/storage/v1/object/{bucket}/{object_path}``.
    Returns public-ish path segment (not a signed URL unless you add policies).
    """
    s = settings or get_settings()
    if not supabase_storage_configured(s):
        raise RuntimeError("Supabase storage is not configured (url + service role key)")
    base = str(s.supabase_url).rstrip("/")
    bucket = s.supabase_storage_bucket
    enc = quote(object_path.lstrip("/"), safe="/")
    url = f"{base}/storage/v1/object/{bucket}/{enc}?upsert=true"
    headers = {
        "Authorization": f"Bearer {s.supabase_service_role_key}",
        "Content-Type": content_type,
    }
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(url, headers=headers, content=data)
        if resp.status_code == 400 and "already exists" in resp.text.lower():
            # Upsert-style: try PATCH/update flow not in MVP — re-raise
            pass
        resp.raise_for_status()
    log.info("Uploaded to Supabase storage: %s/%s", bucket, object_path)
    return f"{bucket}/{object_path}"


def upload_path(local_path: str | Path, *, object_name: str | None = None, settings: Settings | None = None) -> str:
    p = Path(local_path)
    data = p.read_bytes()
    name = object_name or p.name
    return upload_file(object_path=name, data=data, content_type="application/octet-stream", settings=settings)
