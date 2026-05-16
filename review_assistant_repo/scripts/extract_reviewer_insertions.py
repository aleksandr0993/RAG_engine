"""Extract reviewer comment insertion anchors from a source/reviewed notebook pair."""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.retrieval.reviewer_insertions import extract_reviewer_insertions, write_insertion_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build reviewer insertion memory JSONL from source and human-reviewed .ipynb files."
    )
    parser.add_argument("source", type=Path, help="Student source .ipynb")
    parser.add_argument("reviewed", type=Path, help="Human-reviewed .ipynb")
    parser.add_argument("--project", required=True, help="Stable project type, e.g. games_preprocessing")
    parser.add_argument("--output", type=Path, required=True, help="Output JSONL path")
    parser.add_argument("--overwrite", action="store_true", help="Replace output instead of appending/deduping")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = extract_reviewer_insertions(args.source, args.reviewed, project_type=args.project)
    write_insertion_rows(rows, args.output, append=not args.overwrite)
    print(f"rows={len(rows)}")
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
