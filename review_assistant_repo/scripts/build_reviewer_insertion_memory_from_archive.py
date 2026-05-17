"""Build reviewer insertion memory from an archive or directory of reviewed notebooks."""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.retrieval.reviewer_memory_batch import build_reviewer_insertion_memory_from_archive


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Restore student sources from human-reviewed notebooks and append reviewer "
            "comment insertion anchors to a JSONL memory file."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Input .ipynb, directory, .zip, .tar, .tar.gz, or .tgz with reviewed notebooks.",
    )
    parser.add_argument("--project", required=True, help="Stable project type, e.g. games_preprocessing.")
    parser.add_argument("--work-dir", required=True, type=Path, help="Directory for restored sources and manifests.")
    parser.add_argument("--output", required=True, type=Path, help="Output reviewer insertion memory JSONL.")
    parser.add_argument("--report-md", required=True, type=Path, help="Markdown report path.")
    parser.add_argument("--report-json", required=True, type=Path, help="JSON report path.")
    parser.add_argument("--overwrite", action="store_true", help="Replace output instead of appending/deduping.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_reviewer_insertion_memory_from_archive(
        input_path=args.input,
        project=args.project,
        work_dir=args.work_dir,
        output=args.output,
        report_md=args.report_md,
        report_json=args.report_json,
        overwrite=args.overwrite,
    )
    print(f"notebooks_found={summary['notebooks_found']}")
    print(f"processed={summary['processed']}")
    print(f"ignored_empty_projects={summary.get('ignored_empty_projects', 0)}")
    print(f"insertions_extracted={summary['insertions_extracted']}")
    print(f"manual_review_required={summary['manual_review_required']}")
    print(f"output={args.output}")
    print(f"report_md={args.report_md}")
    print(f"report_json={args.report_json}")


if __name__ == "__main__":
    main()
