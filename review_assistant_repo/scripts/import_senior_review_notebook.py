#!/usr/bin/env python3
"""Import a senior-reviewer author notebook as project-specific guidance.

The script extracts color-coded ``Критерии проверки`` / ``Комментарий автора``
cells and writes:

* structured rubric JSON;
* human-readable Markdown;
* runtime JSONL compatible with ``ENABLE_PROJECT_REVIEW_TRAINING``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.retrieval.senior_review import (  # noqa: E402
    extract_senior_review_notebook,
    rubric_to_markdown,
    write_runtime_jsonl,
)


def _write_text(path: Path, text: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists; pass --overwrite to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def import_senior_review_notebook(
    input_notebook: Path,
    *,
    project: str,
    output_json: Path,
    output_md: Path | None,
    runtime_out: Path,
    overwrite: bool,
) -> dict:
    payload = extract_senior_review_notebook(input_notebook, source_project=project)
    if not payload["runtime_rows"]:
        raise ValueError("No senior-review guidance rows were extracted")

    _write_text(
        output_json,
        json.dumps(
            {k: v for k, v in payload.items() if k != "runtime_rows"},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        overwrite=overwrite,
    )
    if output_md is not None:
        _write_text(output_md, rubric_to_markdown(payload), overwrite=overwrite)
    if runtime_out.exists() and not overwrite:
        raise FileExistsError(f"{runtime_out} already exists; pass --overwrite to replace it")
    write_runtime_jsonl(payload["runtime_rows"], runtime_out)

    return {
        "project": project,
        "guidance_blocks": payload["meta"]["guidance_blocks_count"],
        "runtime_rows": payload["meta"]["runtime_rows_count"],
        "output_json": str(output_json),
        "output_md": str(output_md) if output_md else None,
        "runtime_out": str(runtime_out),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_notebook", type=Path)
    parser.add_argument("--project", required=True, help="Stable project slug, e.g. games_preprocessing")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Structured rubric JSON. Default: data/senior_review_guidance/<project>.json",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=None,
        help="Optional Markdown summary. Default: data/senior_review_guidance/<project>.md",
    )
    parser.add_argument(
        "--runtime-out",
        type=Path,
        default=None,
        help="Runtime JSONL for PROJECT_REVIEW_TRAINING_PATH. Default: data/project_training/<project>_senior_review.jsonl",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    output_json = args.output_json or Path("data/senior_review_guidance") / f"{args.project}.json"
    output_md = args.output_md if args.output_md is not None else Path("data/senior_review_guidance") / f"{args.project}.md"
    runtime_out = args.runtime_out or Path("data/project_training") / f"{args.project}_senior_review.jsonl"

    try:
        result = import_senior_review_notebook(
            args.input_notebook,
            project=args.project,
            output_json=output_json,
            output_md=output_md,
            runtime_out=runtime_out,
            overwrite=args.overwrite,
        )
    except Exception as exc:
        print(f"import_senior_review_notebook failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
