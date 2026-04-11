"""iteration_fix_summary / notebook_execution / resolution detail normalization."""

from __future__ import annotations

from app.services.iteration_metadata_quality import (
    audit_iteration_metadata_on_projects,
    normalize_iteration_fix_summary,
    normalize_iteration_issue_resolution_detail,
    normalize_notebook_execution,
)


def test_normalize_iteration_fix_summary_non_dict():
    out = normalize_iteration_fix_summary("bad")
    assert out["status"] == "corrupt_metadata_normalized"
    assert out["items"] == []
    assert out["iteration_fix_policy_version"] == "1.1"


def test_normalize_iteration_fix_summary_invalid_status():
    out = normalize_iteration_fix_summary({"status": "nope", "items": []})
    assert out["status"] == "corrupt_metadata_normalized"
    assert out["_normalized_invalid_status"] == "nope"


def test_normalize_iteration_fix_summary_no_parent_link():
    out = normalize_iteration_fix_summary({"has_parent_link": False, "status": "no_parent_link"})
    assert out["status"] == "no_parent_link"
    assert out["iteration_fix_policy_version"] == "1.1"


def test_normalize_notebook_execution_strips_unknown_keys():
    out = normalize_notebook_execution(
        {
            "notebook_execution_ok": True,
            "extra_should_drop": 1,
        }
    )
    assert "extra_should_drop" not in out
    assert out["notebook_execution_ok"] is True


def test_normalize_resolution_detail_coerces_match():
    out = normalize_iteration_issue_resolution_detail(
        {
            "criterion_code": "  x  ",
            "resolution_status": "fixed",
            "match": {"method": None, "candidates": "3"},
        }
    )
    assert out["criterion_code"] == "x"
    assert out["resolution_status"] == "fixed"
    assert out["match"]["method"] == "unknown"
    assert out["match"]["candidates"] == 3


def test_audit_iteration_metadata_on_projects():
    class _P:
        __slots__ = ("metadata_json",)

        def __init__(self, metadata_json):
            self.metadata_json = metadata_json

    rows = [
        _P({}),
        _P({"iteration_fix_summary": []}),
        _P(
            {
                "iteration_fix_summary": {
                    "status": "evaluated",
                    "counts": "bad",
                }
            }
        ),
        _P(
            {
                "iteration_fix_summary": {
                    "status": "evaluated",
                    "counts": {},
                }
            }
        ),
    ]
    r = audit_iteration_metadata_on_projects(rows)
    assert r["projects_sample_size"] == 4
    assert r["iteration_fix_summary_invalid_type"] == 1
    assert r["evaluated_missing_policy_version"] == 2
    assert r["evaluated_missing_or_bad_counts"] == 1
