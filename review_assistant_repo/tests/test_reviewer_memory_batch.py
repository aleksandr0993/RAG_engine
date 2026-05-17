from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

from app.retrieval.reviewer_insertions import load_insertion_rows
from app.retrieval.reviewer_memory_batch import (
    build_reviewer_insertion_memory_from_archive,
    restore_student_source_from_review,
)


def _write_nb(path: Path, cells: list) -> None:
    nbformat.write(new_notebook(cells=cells), path)


def _review_comment(color: str = "danger", text: str = "замени rating на non_rating") -> str:
    return (
        f'<div class="alert alert-block alert-{color}">'
        "<h2>Комментарий ревьюера</h2>"
        f"<b>На доработку:</b> {text}"
        "</div>"
    )


def test_restore_student_source_removes_reviewer_and_student_div_comments(tmp_path: Path):
    reviewed = tmp_path / "reviewed.ipynb"
    restored = tmp_path / "restored.ipynb"
    _write_nb(
        reviewed,
        [
            new_markdown_cell("## 2.3. Наличие пропусков"),
            new_code_cell("df['rating'] = df['rating'].fillna('non rating')"),
            new_markdown_cell(_review_comment()),
            new_markdown_cell('<div class="alert alert-info"><h2>Комментарий студента:</h2>fixed</div>'),
            new_code_cell("df.info()"),
        ],
    )

    stats, _ = restore_student_source_from_review(reviewed, restored)

    assert stats["status"] == "ok"
    assert stats["reviewer_comments_found"] == 1
    assert stats["student_comments_removed"] == 1
    clean_nb = nbformat.read(restored, as_version=4)
    sources = "\n".join(str(cell.get("source", "")) for cell in clean_nb.cells)
    assert "Комментарий ревьюера" not in sources
    assert "Комментарий студента" not in sources
    assert "fillna" in sources


def test_build_reviewer_insertion_memory_from_directory_writes_reports(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    reviewed = input_dir / "reviewed.ipynb"
    _write_nb(
        reviewed,
        [
            new_markdown_cell("## 2.3. Наличие пропусков"),
            new_code_cell("df['rating'] = df['rating'].fillna('non rating')"),
            new_markdown_cell(_review_comment()),
        ],
    )
    work_dir = tmp_path / "work"
    output = tmp_path / "memory.jsonl"
    report_md = work_dir / "report.md"
    report_json = work_dir / "report.json"

    summary = build_reviewer_insertion_memory_from_archive(
        input_path=input_dir,
        project="games_preprocessing",
        work_dir=work_dir,
        output=output,
        report_md=report_md,
        report_json=report_json,
        overwrite=True,
    )

    rows = load_insertion_rows(output)
    assert summary["notebooks_found"] == 1
    assert summary["insertions_extracted"] == 1
    assert rows[0]["criterion_code"] == "games_missing_values_decision"
    assert rows[0]["alert_color"] == "danger"
    assert (work_dir / "manifest.jsonl").exists()
    assert (work_dir / "problem_files.txt").exists()
    assert "Reviewer insertion memory build report" in report_md.read_text(encoding="utf-8")
    assert json.loads(report_json.read_text(encoding="utf-8"))["insertions_extracted"] == 1


def test_build_reviewer_insertion_memory_flags_ambiguous_file(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_nb(input_dir / "plain.ipynb", [new_code_cell("x = 1")])

    summary = build_reviewer_insertion_memory_from_archive(
        input_path=input_dir,
        project="games_preprocessing",
        work_dir=tmp_path / "work",
        output=tmp_path / "memory.jsonl",
        report_md=tmp_path / "work" / "report.md",
        report_json=tmp_path / "work" / "report.json",
        overwrite=True,
    )

    assert summary["manual_review_required"] == 1
    assert "no_reviewer_comments_detected" in summary["problem_files"][0]["reasons"]
    assert "no_insertions_extracted" in summary["problem_files"][0]["reasons"]


def test_build_reviewer_insertion_memory_accepts_zip(tmp_path: Path):
    reviewed = tmp_path / "reviewed.ipynb"
    _write_nb(
        reviewed,
        [
            new_code_cell("df.columns = df.columns.str.lower()"),
            new_markdown_cell(_review_comment("warning", "приведи названия столбцов к snake_case")),
        ],
    )
    archive = tmp_path / "archive.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(reviewed, arcname="nested/reviewed.ipynb")

    summary = build_reviewer_insertion_memory_from_archive(
        input_path=archive,
        project="games_preprocessing",
        work_dir=tmp_path / "work",
        output=tmp_path / "memory.jsonl",
        report_md=tmp_path / "work" / "report.md",
        report_json=tmp_path / "work" / "report.json",
        overwrite=True,
    )

    assert summary["notebooks_found"] == 1
    assert summary["insertions_extracted"] == 1


def test_root_wrapper_runs_from_project_root(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_nb(
        input_dir / "reviewed.ipynb",
        [
            new_code_cell("df['rating'] = df['rating'].fillna('non rating')"),
            new_markdown_cell(_review_comment()),
        ],
    )
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "build_reviewer_insertion_memory_from_archive.py"),
            "--input",
            str(input_dir),
            "--project",
            "games_preprocessing",
            "--work-dir",
            str(tmp_path / "work"),
            "--output",
            str(tmp_path / "memory.jsonl"),
            "--report-md",
            str(tmp_path / "work" / "report.md"),
            "--report-json",
            str(tmp_path / "work" / "report.json"),
            "--overwrite",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "insertions_extracted=1" in result.stdout
    assert load_insertion_rows(tmp_path / "memory.jsonl")
