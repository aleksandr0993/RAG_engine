from homework_reviewer_llm.schema import NormalizedRecord
from homework_reviewer_llm.split import leak_safe_split_strict_both


def _row(sid: str, aid: str, rid: str) -> NormalizedRecord:
    return NormalizedRecord(
        id=rid,
        student_id=sid,
        assignment_id=aid,
        submission_text="x" * 60,
        review_text="y" * 25,
        overall_score=70.0,
    )


def test_strict_both_disjoint() -> None:
    rows = []
    for sid in ("s1", "s2", "s3", "s4"):
        for aid in ("a1", "a2"):
            rows.append(_row(sid, aid, f"{sid}_{aid}"))
    out, dropped = leak_safe_split_strict_both(
        rows,
        seed="x",
        train_ratio=0.5,
        val_ratio=0.25,
        test_ratio=0.25,
        test_assignment_pool_ratio=0.5,
    )
    assert dropped >= 0
    train_a = {r.assignment_id for r in out if r.split == "train"}
    test_a = {r.assignment_id for r in out if r.split == "test"}
    assert train_a.isdisjoint(test_a)

    train_s = {r.student_id for r in out if r.split == "train"}
    test_s = {r.student_id for r in out if r.split == "test"}
    assert train_s.isdisjoint(test_s)
