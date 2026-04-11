from __future__ import annotations

from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

from app.parsers.notebook import (
    MIDDLE_REVIEWER_MARKER,
    REVIEWER_MARKER,
    STUDENT_MARKER,
    NotebookParser,
    infer_notebook_comment_role,
)


def test_infer_notebook_comment_role_order():
    assert infer_notebook_comment_role(f"{REVIEWER_MARKER} then {MIDDLE_REVIEWER_MARKER}") == "reviewer"
    assert infer_notebook_comment_role(f"{MIDDLE_REVIEWER_MARKER} only") == "middle_reviewer"
    assert infer_notebook_comment_role("Комментарий мидл ревьюера alt") == "middle_reviewer"
    assert infer_notebook_comment_role(f"{STUDENT_MARKER} reply") == "student"
    assert infer_notebook_comment_role("plain code x=1") == "unknown"


def test_parser_metadata_comment_role(tmp_path: Path):
    nb = new_notebook(
        cells=[
            new_code_cell("x = 1"),
            new_markdown_cell(f"{REVIEWER_MARKER}\n\nPlease fix."),
            new_markdown_cell(f"{MIDDLE_REVIEWER_MARKER}\n\nAlmost."),
            new_markdown_cell(f"{STUDENT_MARKER}\n\nQuestion?"),
        ]
    )
    p = tmp_path / "t.ipynb"
    nbformat.write(nb, p)
    parser = NotebookParser()
    arts, _ = parser.parse(str(p))
    assert arts[0].metadata["comment_role"] == "unknown"
    assert arts[1].metadata["comment_role"] == "reviewer"
    assert arts[1].metadata["is_reviewer_comment"] is True
    assert arts[2].metadata["comment_role"] == "middle_reviewer"
    assert arts[2].metadata["is_middle_reviewer_comment"] is True
    assert arts[3].metadata["comment_role"] == "student"


def test_clean_notebook_strips_reviewer_and_middle(tmp_path: Path):
    nb = new_notebook(
        cells=[
            new_code_cell("x = 1"),
            new_markdown_cell(f"{REVIEWER_MARKER}\n\ndrop"),
            new_markdown_cell(f"{MIDDLE_REVIEWER_MARKER}\n\ndrop"),
            new_markdown_cell(f'{STUDENT_MARKER}\n\n<div class="x">drop html</div>'),
            new_markdown_cell(f"{STUDENT_MARKER}\n\nkeep plain"),
        ]
    )
    p = tmp_path / "c.ipynb"
    nbformat.write(nb, p)
    _, nb_dict = NotebookParser().parse(str(p))
    cleaned = NotebookParser().clean_notebook(nb_dict)
    sources = []
    for c in cleaned["cells"]:
        try:
            sources.append(c.source)
        except AttributeError:
            sources.append("".join(c.get("source", "")))
    assert all(REVIEWER_MARKER not in s for s in sources)
    assert all(MIDDLE_REVIEWER_MARKER not in s for s in sources)
    assert any("keep plain" in s for s in sources)
