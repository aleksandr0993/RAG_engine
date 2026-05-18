"""Analyze the local corpus of notebooks reviewed by the current reviewer."""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.retrieval.reviewer_memory_batch import build_reviewer_insertion_memory_from_archive

DEFAULT_INPUT = Path("/Users/mac/yandex/var/notebooks/python_preprocessing_20260518_150447")
DEFAULT_PROJECT = "python_preprocessing"
DEFAULT_WORK_DIR = Path("./data/reviewer_memory_build/python_preprocessing_20260518_150447")
DEFAULT_OUTPUT = Path("./data/reviewer_insertions/python_preprocessing.jsonl")
DEFAULT_REPORT_MD = DEFAULT_WORK_DIR / "report.md"
DEFAULT_REPORT_JSON = DEFAULT_WORK_DIR / "report.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze notebooks reviewed by the current reviewer, classify reviewer comments "
            "by criteria and praises, and build insertion-position memory."
        )
    )
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT,
        type=Path,
        help=f"Input .ipynb, directory, .zip, .tar, .tar.gz, or .tgz. Default: {DEFAULT_INPUT}",
    )
    parser.add_argument(
        "--project",
        default=DEFAULT_PROJECT,
        help=f"Stable project type stored in memory rows. Default: {DEFAULT_PROJECT}",
    )
    parser.add_argument(
        "--work-dir",
        default=DEFAULT_WORK_DIR,
        type=Path,
        help=f"Directory for restored sources, manifest, and problem file list. Default: {DEFAULT_WORK_DIR}",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        type=Path,
        help=f"Output reviewer insertion memory JSONL. Default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--report-md",
        default=DEFAULT_REPORT_MD,
        type=Path,
        help=f"Markdown report path. Default: {DEFAULT_REPORT_MD}",
    )
    parser.add_argument(
        "--report-json",
        default=DEFAULT_REPORT_JSON,
        type=Path,
        help=f"JSON report path. Default: {DEFAULT_REPORT_JSON}",
    )
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
    print(f"criterion_counts={summary.get('criterion_counts', {})}")
    print(f"praise_counts={summary.get('praise_counts', {})}")
    print(f"quality_summary={summary.get('quality_summary', {})}")
    print(f"output={args.output}")
    print(f"report_md={args.report_md}")
    print(f"report_json={args.report_json}")


if __name__ == "__main__":
    main()
