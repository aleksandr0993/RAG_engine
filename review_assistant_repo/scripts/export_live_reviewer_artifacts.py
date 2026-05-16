"""Run a notebook through Review Assistant and export reviewer-facing artifacts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a Markdown review, reviewed .ipynb, and JSON findings for a student notebook."
    )
    parser.add_argument("notebook", type=Path, help="Student .ipynb file")
    parser.add_argument("--criteria-map-code", default="notebook_games_preprocessing_v1")
    parser.add_argument("--review-training-project", default="games_preprocessing")
    parser.add_argument("--practicum-input-channel", default="revisor")
    parser.add_argument("--output-dir", type=Path, default=Path("data/student_samples"))
    parser.add_argument("--execute-notebook", action="store_true", help="Enable notebook execution before review")
    parser.add_argument(
        "--use-current-env",
        action="store_true",
        help="Use current DATABASE_URL/FILES_ROOT/EXPORTS_ROOT instead of an isolated temporary workspace",
    )
    return parser.parse_args()


def configure_env(args: argparse.Namespace) -> Path:
    if args.use_current_env:
        exports_root = Path(os.environ.get("EXPORTS_ROOT", "data/exports"))
    else:
        tmpdir = Path(tempfile.mkdtemp(prefix="rag_live_review_"))
        os.environ.setdefault("DATABASE_URL", f"sqlite:///{tmpdir / 'review.db'}")
        os.environ.setdefault("FILES_ROOT", str(tmpdir / "files"))
        os.environ.setdefault("EXPORTS_ROOT", str(tmpdir / "exports"))
        exports_root = tmpdir / "exports"

    os.environ["ENABLE_NOTEBOOK_EXECUTION"] = "true" if args.execute_notebook else "false"
    os.environ.setdefault("ENABLE_LLM", "false")
    os.environ.setdefault("ENABLE_LLM_COMMENT_GENERATION", "false")
    os.environ.setdefault("ENABLE_RETRIEVAL", "true")
    os.environ.setdefault("ENABLE_PROJECT_REVIEW_TRAINING", "true")
    os.environ.setdefault(
        "PROJECT_REVIEW_TRAINING_PATH",
        "./data/project_training/games_preprocessing_senior_review.jsonl",
    )
    return exports_root


def main() -> None:
    args = parse_args()
    notebook = args.notebook.resolve()
    if not notebook.is_file():
        raise SystemExit(f"Notebook not found: {notebook}")

    exports_root = configure_env(args)

    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    with notebook.open("rb") as fh:
        upload = client.post(
            "/api/v1/projects/upload",
            data={
                "criteria_map_code": args.criteria_map_code,
                "review_training_project": args.review_training_project,
                "practicum_input_channel": args.practicum_input_channel,
            },
            files={"file": (notebook.name, fh, "application/x-ipynb+json")},
        )
    upload.raise_for_status()
    project_id = upload.json()["project_id"]

    review = client.post(f"/api/v1/projects/{project_id}/review")
    review.raise_for_status()

    project: dict[str, Any] = client.get(f"/api/v1/projects/{project_id}").json()
    findings: list[dict[str, Any]] = client.get(f"/api/v1/projects/{project_id}/findings").json()
    payload = {
        "project": project,
        "review_result": review.json(),
        "findings": findings,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = notebook.stem
    review_md_path = args.output_dir / f"{stem}_live_reviewer_review.md"
    json_path = args.output_dir / f"{stem}_review_result.json"
    reviewed_path = args.output_dir / f"{stem}_reviewed_by_assistant.ipynb"

    review_md_path.write_text((project.get("review_markdown") or "").rstrip() + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    generated_reviewed = exports_root / project_id / "reviewed.ipynb"
    if generated_reviewed.exists():
        shutil.copy2(generated_reviewed, reviewed_path)

    print(f"project_id={project_id}")
    print(f"markdown_review={review_md_path}")
    print(f"review_json={json_path}")
    if reviewed_path.exists():
        print(f"reviewed_notebook={reviewed_path}")


if __name__ == "__main__":
    main()
