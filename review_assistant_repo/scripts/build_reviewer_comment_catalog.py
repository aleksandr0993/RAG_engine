#!/usr/bin/env python3
"""
Build a JSON (and optional Markdown) catalog of typical reviewer comments from many .ipynb files.

Example:
  python scripts/build_reviewer_comment_catalog.py \\
    --input-dir ./data/reviewed_notebooks \\
    --project my_corpus \\
    --output ./data/reviewer_comment_catalog.json \\
    --output-md ./data/reviewer_comment_catalog.md
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.retrieval.comment_catalog import build_catalog, catalog_to_markdown, write_catalog_json


def _collect_ipynb(input_dir: Path) -> list[Path]:
    return sorted(input_dir.rglob("*.ipynb"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Cluster reviewer comments from notebooks into a reference catalog.")
    ap.add_argument("--input-dir", type=Path, required=True, help="Root directory (recursive *.ipynb)")
    ap.add_argument("--project", type=str, default="catalog", help="Label stored as source_project / meta")
    ap.add_argument("--output", type=Path, required=True, help="Output JSON path")
    ap.add_argument("--output-md", type=Path, default=None, help="Optional Markdown path")
    ap.add_argument(
        "--method",
        choices=("heuristic", "tfidf_kmeans"),
        default="heuristic",
        help="heuristic: Jaccard on tokens; tfidf_kmeans: needs pip install -e .[analysis]",
    )
    ap.add_argument("--sim-threshold", type=float, default=0.55, help="Jaccard threshold for heuristic clustering")
    ap.add_argument(
        "--n-clusters",
        type=int,
        default=None,
        help="Max clusters per (section,color) bucket for tfidf_kmeans (default: auto ~sqrt(n))",
    )
    ap.add_argument(
        "--include-student",
        action="store_true",
        help="Append student-role samples under student_context_samples (not clustered)",
    )
    args = ap.parse_args()

    input_dir: Path = args.input_dir
    if not input_dir.is_dir():
        raise SystemExit(f"Not a directory: {input_dir}")

    paths = _collect_ipynb(input_dir)
    if not paths:
        raise SystemExit(f"No .ipynb files under {input_dir}")

    catalog = build_catalog(
        ipynb_paths=paths,
        source_project=args.project,
        method=args.method,
        sim_threshold=args.sim_threshold,
        n_clusters=args.n_clusters,
        auto_k_method=args.auto_k_method,
        min_cluster_frequency=args.min_cluster_frequency,
        min_cluster_abs=args.min_cluster_abs,
        include_student=args.include_student,
    )
    write_catalog_json(catalog, args.output)
    print(f"Wrote JSON -> {args.output.resolve()} ({catalog['meta']['total_clusters']} clusters)")
    if args.output_md:
        md = catalog_to_markdown(catalog)
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(md, encoding="utf-8")
        print(f"Wrote Markdown -> {args.output_md.resolve()}")


if __name__ == "__main__":
    main()
