"""Wrapper for the review assistant batch memory builder.

This keeps root-level commands stable while the implementation lives in
review_assistant_repo/.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1] / "review_assistant_repo"
SCRIPT = REPO_ROOT / "scripts" / "build_reviewer_insertion_memory_from_archive.py"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

runpy.run_path(str(SCRIPT), run_name="__main__")
