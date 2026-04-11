import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "samples" / "raw_homework.jsonl"


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample missing")
def test_pipeline_local_from_sample_jsonl(tmp_path: Path) -> None:
    wd = tmp_path / "wd"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "pipeline_local.py"),
            "--raw-jsonl",
            str(SAMPLE),
            "--workdir",
            str(wd),
            "--seed",
            "pipe-test",
            "--output-format",
            "v2",
        ],
        check=True,
        cwd=str(ROOT),
    )
    assert (wd / "sft" / "train_val_v2.jsonl").is_file()
    assert (wd / "processed" / "train.jsonl").is_file()
