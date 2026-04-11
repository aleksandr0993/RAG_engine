#!/usr/bin/env python3
"""
Release check: every HTTP method + path advertised in README (API sections)
must exist in the live OpenAPI schema.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


README_METHOD_PATH = re.compile(
    r"`(?P<method>GET|POST|PUT|PATCH|DELETE)\s+(?P<path>/api/v1[/a-zA-Z0-9_{}\-\.]+)`"
)


def main() -> int:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    from app.main import create_app

    openapi = create_app().openapi()
    paths = openapi.get("paths") or {}

    missing: list[str] = []
    for m in README_METHOD_PATH.finditer(readme):
        method = m.group("method").lower()
        path = m.group("path")
        # Normalise templated paths: README uses {id} etc.; OpenAPI uses {project_id}
        candidates = {path}
        if "{id}" in path:
            candidates.add(path.replace("{id}", "{project_id}"))
            candidates.add(path.replace("{id}", "{job_id}"))
        if "{job_id}" in path and "{job_id}" not in path:  # pragma: no cover
            pass
        found = False
        entry = None
        for cand in candidates:
            entry = paths.get(cand)
            if entry and method in entry:
                found = True
                break
        if not found:
            missing.append(f"{method.upper()} {path}")

    if missing:
        print("README advertises endpoints missing from OpenAPI:")
        for line in missing:
            print(" -", line)
        return 1
    print("README / OpenAPI endpoint check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
