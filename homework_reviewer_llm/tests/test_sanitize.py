from homework_reviewer_llm.sanitize import dedupe_by_submission_hash, redact_pii, scrub_record
from homework_reviewer_llm.schema import NormalizedRecord, RawHomeworkRecord


def test_redact_pii() -> None:
    t = "Пишите на a@b.com или +7 999 123-45-67 и https://x.com/y"
    out = redact_pii(t)
    assert "[EMAIL]" in out
    assert "[PHONE]" in out
    assert "[URL]" in out


def test_dedupe_stable() -> None:
    r1 = NormalizedRecord(
        id="1",
        student_id="s",
        assignment_id="a",
        submission_text="same text " * 10,
        review_text="review " * 5,
        overall_score=1.0,
    )
    r2 = r1.model_copy(update={"id": "2"})
    out = dedupe_by_submission_hash([r1, r2])
    assert len(out) == 1


def test_scrub_record() -> None:
    raw = RawHomeworkRecord(
        id="x",
        student_id="s",
        assignment_id="a",
        submission_text="hello@world.ru test",
        review_text="ok",
        overall_score=5.0,
    )
    n = scrub_record(raw)
    assert "[EMAIL]" in n.submission_text
