"""После pipeline_local: oracle-метрики, команда обучения, контрастный merge (один прогон пайплайна)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_LEGACY_SAMPLE = ROOT / "data" / "samples" / "raw_homework.jsonl"
SAMPLE = _LEGACY_SAMPLE if _LEGACY_SAMPLE.exists() else (ROOT / "fixtures" / "raw_homework.jsonl")


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample missing")
def test_post_pipeline_bundle(tmp_path: Path) -> None:
    wd = tmp_path / "bundle"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "pipeline_local.py"),
            "--raw-jsonl",
            str(SAMPLE),
            "--workdir",
            str(wd),
            "--seed",
            "bundle-seed",
            "--output-format",
            "v2",
            "--with-contrastive",
        ],
        check=True,
        cwd=str(ROOT),
    )

    merged = wd / "sft" / "train_val_v2_plus_contrastive.jsonl"
    assert merged.is_file()
    assert len(merged.read_text(encoding="utf-8").strip().splitlines()) > 3

    test_f = wd / "processed" / "test.jsonl"
    if not test_f.is_file() or not test_f.read_text().strip():
        pytest.skip("нет test split")
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "sanity_eval_workdir.py"),
            "--workdir",
            str(wd),
            "--format",
            "v2",
        ],
        check=True,
        cwd=str(ROOT),
    )
    report = wd / "metrics" / "oracle_v2.json"
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data.get("score_mae") == 0.0
    assert data.get("json_valid_rate") == 1.0

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "print_train_command.py"),
            "--workdir",
            str(wd),
            "--format",
            "v2",
            "--dataset",
            "plus_contrastive",
        ],
        check=True,
        cwd=str(ROOT),
    )
