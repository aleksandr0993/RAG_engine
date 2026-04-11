from __future__ import annotations


def build_verdict(results: list[dict]) -> str:
    has_required_fail = any(
        result["severity"] == "required" and result["status"] == "fail"
        for result in results
    )
    return "revise" if has_required_fail else "pass"
