import json
import subprocess
import sys
from pathlib import Path

import pytest

from homework_reviewer_llm.raw_csv import row_to_record_dict

ROOT = Path(__file__).resolve().parents[1]


def test_row_to_record_dict_roundtrip() -> None:
    row = {
        "id": "1",
        "student_id": "s",
        "assignment_id": "a",
        "submission_text": "work",
        "review_text": "ok",
        "overall_score": "80",
        "rubric_scores": '{"x": 1}',
        "revision_history": "",
        "student_profile": "",
    }
    d = row_to_record_dict(row)
    assert d["overall_score"] == 80.0
    assert d["rubric_scores"] == {"x": 1}


@pytest.mark.skipif(not (ROOT / "data/templates/reviewer_manual_export.csv").exists(), reason="template")
def test_template_csv_converts() -> None:
    out = ROOT / "tests" / "_tmp_from_template.jsonl"
    try:
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "csv_to_raw_jsonl.py"),
                "--input",
                str(ROOT / "data/templates/reviewer_manual_export.csv"),
                "--output",
                str(out),
            ],
            check=True,
            cwd=str(ROOT),
        )
        line = out.read_text(encoding="utf-8").strip().splitlines()[0]
        obj = json.loads(line)
        assert obj["id"] == "example_001"
        assert obj["rubric_scores"]["sql"] == 20
    finally:
        if out.exists():
            out.unlink()
