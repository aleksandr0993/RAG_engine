from homework_reviewer_llm.schema import NormalizedRecord
from homework_reviewer_llm.split import leak_safe_split


def _rec(sid: str, aid: str, rid: str) -> NormalizedRecord:
    return NormalizedRecord(
        id=rid,
        student_id=sid,
        assignment_id=aid,
        submission_text="x" * 60,
        review_text="y" * 25,
        overall_score=70.0,
    )


def test_no_student_leak() -> None:
    rows = [
        _rec("s1", "a1", "r1"),
        _rec("s1", "a2", "r2"),
        _rec("s2", "a1", "r3"),
        _rec("s3", "a3", "r4"),
    ]
    out = leak_safe_split(rows, seed="t", train_ratio=0.5, val_ratio=0.25, test_ratio=0.25)
    by_student: dict[str, set[str]] = {}
    for r in out:
        by_student.setdefault(r.student_id, set()).add(r.split or "")
    for splits in by_student.values():
        assert len(splits) == 1
