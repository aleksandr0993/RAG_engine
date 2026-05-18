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


def test_restore_student_source_removes_lowercase_final_reviewer_comment(tmp_path: Path):
    reviewed = tmp_path / "reviewed.ipynb"
    restored = tmp_path / "restored.ipynb"
    final_comment = (
        '<div style="border:solid Chocolate 2px; padding: 40px">'
        '<h2>Итоговый комментарий ревьюера 2 (итоговый вывод по проекту)</h2>'
        "Теперь почти идеально, молодец! Принимаю твой проект)"
        "</div>"
    )
    _write_nb(
        reviewed,
        [
            new_code_cell("df.info()"),
            new_markdown_cell(final_comment),
        ],
    )

    stats, _ = restore_student_source_from_review(reviewed, restored)

    assert stats["status"] == "ok"
    assert stats["reviewer_comments_found"] == 1
    clean_nb = nbformat.read(restored, as_version=4)
    sources = "\n".join(str(cell.get("source", "")) for cell in clean_nb.cells)
    assert "Теперь почти идеально" not in sources
    assert "df.info()" in sources


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
    report_text = report_md.read_text(encoding="utf-8")
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert "Reviewer insertion memory build report" in report_text
    assert "Criterion counts" in report_text
    assert "Quality summary" in report_text
    assert report["insertions_extracted"] == 1
    assert report["criterion_counts"] == {"games_missing_values_decision": 1}
    assert report["quality_summary"] == {
        "unknown_criterion": 0,
        "unknown_alert": 0,
        "weak_anchors": 0,
        "duplicate_comments": 0,
    }


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


def test_build_reviewer_insertion_memory_flags_jupyter_html_shell(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "shell.ipynb").write_text(
        "<!DOCTYPE HTML><html><body><div id='notebook' "
        "data-notebook-path='project.ipynb'>NotebookApp</div></body></html>",
        encoding="utf-8",
    )

    summary = build_reviewer_insertion_memory_from_archive(
        input_path=input_dir,
        project="games_preprocessing",
        work_dir=tmp_path / "work",
        output=tmp_path / "memory.jsonl",
        report_md=tmp_path / "work" / "report.md",
        report_json=tmp_path / "work" / "report.json",
        overwrite=True,
    )

    assert summary["processed"] == 0
    assert summary["manual_review_required"] == 1
    assert "invalid_notebook:NotebookHtmlShellError" in summary["problem_files"][0]["reasons"]


def test_build_reviewer_insertion_memory_ignores_empty_project_review(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_nb(
        input_dir / "empty_project.ipynb",
        [
            new_markdown_cell(
                '<div class="alert alert-info"><h2>Комментарий ревьюера</h2>'
                "Получил пустой проект, похоже произошел технический сбой."
                "</div>"
            )
        ],
    )

    summary = build_reviewer_insertion_memory_from_archive(
        input_path=input_dir,
        project="games_preprocessing",
        work_dir=tmp_path / "work",
        output=tmp_path / "memory.jsonl",
        report_md=tmp_path / "work" / "report.md",
        report_json=tmp_path / "work" / "report.json",
        overwrite=True,
    )

    assert summary["ignored_empty_projects"] == 1
    assert summary["insertions_extracted"] == 0
    assert summary["manual_review_required"] == 0
    assert load_insertion_rows(tmp_path / "memory.jsonl") == []
    assert "Ignored empty projects" in (tmp_path / "work" / "report.md").read_text(encoding="utf-8")


def test_build_reviewer_insertion_memory_does_not_treat_praise_as_unknown_criterion(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_nb(
        input_dir / "praise.ipynb",
        [
            new_markdown_cell("## Содержимое проекта"),
            new_markdown_cell("Цель проекта описана, задачи перечислены."),
            new_markdown_cell(_review_comment("success", "Отлично по описанию. Цели и задачи ясны.")),
        ],
    )

    summary = build_reviewer_insertion_memory_from_archive(
        input_path=input_dir,
        project="games_preprocessing",
        work_dir=tmp_path / "work",
        output=tmp_path / "memory.jsonl",
        report_md=tmp_path / "work" / "report.md",
        report_json=tmp_path / "work" / "report.json",
        overwrite=True,
    )
    rows = load_insertion_rows(tmp_path / "memory.jsonl")

    assert summary["insertions_extracted"] == 1
    assert summary["unknown_criterion"] == 0
    assert summary["comment_kind_counts"] == {"non_criterion_praise": 1}
    assert summary["criterion_counts"] == {}
    assert summary["praise_counts"] == {"praise_project_intro_context": 1}
    assert summary["quality_summary"]["unknown_criterion"] == 0
    assert rows[0]["praise_code"] == "praise_project_intro_context"
    assert rows[0]["comment_kind"] == "non_criterion_praise"


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


def test_analyze_my_reviewed_notebooks_uses_defaults_with_overrides(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
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
            str(repo / "scripts" / "analyze_my_reviewed_notebooks.py"),
            "--input",
            str(input_dir),
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
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "insertions_extracted=1" in result.stdout
    assert "criterion_counts={'games_missing_values_decision': 1}" in result.stdout
    report = json.loads((tmp_path / "work" / "report.json").read_text(encoding="utf-8"))
    assert report["project"] == "python_preprocessing"
    assert load_insertion_rows(tmp_path / "memory.jsonl")
