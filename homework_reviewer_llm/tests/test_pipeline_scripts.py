import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_LEGACY_SAMPLE = ROOT / "data" / "samples" / "raw_homework.jsonl"
SAMPLE = _LEGACY_SAMPLE if _LEGACY_SAMPLE.exists() else (ROOT / "fixtures" / "raw_homework.jsonl")


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample missing")
def test_build_dataset_and_sft(tmp_path: Path) -> None:
    out_dir = tmp_path / "processed"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_dataset.py"),
            "--input",
            str(SAMPLE),
            "--output-dir",
            str(out_dir),
            "--seed",
            "fixed-seed",
        ],
        check=True,
        cwd=str(ROOT),
    )
    train = out_dir / "train.jsonl"
    assert train.exists()
    sft_out = tmp_path / "sft.jsonl"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_sft_jsonl.py"),
            "--train",
            str(train),
            "--output",
            str(sft_out),
            "--splits",
            "train",
        ],
        check=True,
        cwd=str(ROOT),
    )
    line = sft_out.read_text(encoding="utf-8").splitlines()[0]
    obj = json.loads(line)
    assert "messages" in obj


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample missing")
def test_build_sft_v2(tmp_path: Path) -> None:
    out_dir = tmp_path / "processed2"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_dataset.py"),
            "--input",
            str(SAMPLE),
            "--output-dir",
            str(out_dir),
            "--seed",
            "fixed-seed-v2",
        ],
        check=True,
        cwd=str(ROOT),
    )
    train = out_dir / "train.jsonl"
    sft_out = tmp_path / "sft_v2.jsonl"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_sft_jsonl.py"),
            "--train",
            str(train),
            "--output",
            str(sft_out),
            "--splits",
            "train",
            "--output-format",
            "v2",
        ],
        check=True,
        cwd=str(ROOT),
    )
    line = sft_out.read_text(encoding="utf-8").splitlines()[0]
    obj = json.loads(line)
    assistant = json.loads(obj["messages"][-1]["content"])
    assert "student_feedback" in assistant
