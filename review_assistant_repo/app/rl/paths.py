from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

_SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


def normalize_artefact_filename(artefact: str) -> str:
    """Return a safe ``*.zip`` file name (no directories)."""
    s = (artefact or "").strip()
    if not s or s.startswith(".") or "/" in s or "\\" in s:
        raise ValueError("artefact_name must be a plain file name without path components")
    p = Path(s)
    if p.name != s:
        raise ValueError("artefact_name must be a plain file name without path components")
    if p.suffix.lower() == ".zip":
        if not _SAFE_NAME.match(p.stem):
            raise ValueError("invalid artefact_name")
        return s
    if not _SAFE_NAME.match(s):
        raise ValueError("invalid artefact_name")
    return f"{s}.zip"


def resolve_rl_artefact_under_root(settings: Settings, artefact: str, *, require_exists: bool) -> Path:
    """
    Resolve a model file name under ``settings.rl_models_root``.
    Only simple file names are allowed (no directories / traversal).
    """
    name = normalize_artefact_filename(artefact)
    root = Path(settings.rl_models_root).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Invalid model path")
    if require_exists and not path.is_file():
        raise ValueError(f"Model file not found: {path}")
    return path
