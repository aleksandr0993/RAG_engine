from __future__ import annotations

import re
from pathlib import Path


def changelog_file_path() -> Path:
    """Repo root: parent of the `app` package (…/review_assistant_repo/CHANGELOG.md)."""
    return Path(__file__).resolve().parents[2] / "CHANGELOG.md"


def parse_changelog_markdown(text: str) -> list[tuple[str, list[str]]]:
    """
    Parse KEEP-a-style sections: ## version header, then bullet lines (- item).
    Returns (version_title, items) in file order (newest first if the file is maintained that way).
    """
    entries: list[tuple[str, list[str]]] = []
    current_version: str | None = None
    current_items: list[str] = []

    def flush() -> None:
        nonlocal current_version, current_items
        if current_version is not None:
            entries.append((current_version, list(current_items)))
        current_items = []

    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if line.startswith("## "):
            flush()
            current_version = line[3:].strip()
            continue
        if current_version is None:
            continue
        m = re.match(r"\s*-\s+(.*)$", line)
        if m:
            current_items.append(m.group(1).strip())

    flush()
    return entries


def load_changelog_entries(limit: int | None = None) -> list[tuple[str, list[str]]]:
    path = changelog_file_path()
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    entries = parse_changelog_markdown(text)
    if limit is not None:
        return entries[:limit]
    return entries
