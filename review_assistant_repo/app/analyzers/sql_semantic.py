from __future__ import annotations

from app.analyzers.sql_ast import analyze_sql_query
from app.llm.service import LLMService


def _first_sql_artifact(artifacts: list[dict]) -> dict | None:
    for a in artifacts:
        if a.get("artifact_type") == "sql_query":
            return a
    return None


def _issue_finding_dict(criterion: dict, issue: dict, anchor_idx: int | None) -> dict:
    return {
        "status": "fail" if criterion.get("severity") == "required" else "warn",
        "confidence": 0.88,
        "anchor_position_idx": anchor_idx,
        "evidence": [
            {
                "problem_type": issue.get("problem_type"),
                "offending_sql_excerpt": issue.get("offending_sql_excerpt"),
                "recommended_fix_hint": issue.get("recommended_fix_hint"),
            }
        ],
        "metadata": {
            "source_stage": "semantic",
            "sql_ast": True,
            "problem_type": issue.get("problem_type"),
        },
    }


def run_sql_semantic(task: str, artifacts: list[dict], criterion: dict, llm: LLMService | None = None) -> dict:
    llm = llm or LLMService()
    art = _first_sql_artifact(artifacts)
    if not art:
        return {
            "status": "unknown",
            "confidence": 0.2,
            "anchor_position_idx": None,
            "evidence": [],
            "metadata": {"task": task, "note": "no_sql_artifact"},
        }

    sql = art.get("raw_text") or ""
    anchor = art.get("position_idx")
    meta = art.get("metadata_json") or {}
    report = meta.get("ast_report")
    if not report:
        parsed_meta = analyze_sql_query(sql)
        report = {
            "issues": [
                {
                    "problem_type": i.problem_type,
                    "offending_sql_excerpt": i.offending_sql_excerpt,
                    "recommended_fix_hint": i.recommended_fix_hint,
                    "metadata": i.metadata,
                }
                for i in parsed_meta.issues
            ],
            "parse_error": parsed_meta.parse_error,
            "join_count": parsed_meta.join_count,
            "left_join_count": parsed_meta.left_join_count,
        }

    issues = report.get("issues") or []

    if task == "division_without_nullif":
        for iss in issues:
            if iss.get("problem_type") == "division_without_nullif":
                return _issue_finding_dict(criterion, iss, anchor)
        return {
            "status": "pass",
            "confidence": 0.9,
            "anchor_position_idx": anchor,
            "evidence": [{"excerpt": (art.get("normalized_text") or "")[:200]}],
            "metadata": {"source_stage": "semantic", "sql_ast": True, "note": "no_unsafe_div"},
        }

    if task == "count_logic_mismatch":
        for iss in issues:
            if iss.get("problem_type") == "count_logic_mismatch":
                return _issue_finding_dict(criterion, iss, anchor)
        return {
            "status": "pass",
            "confidence": 0.85,
            "anchor_position_idx": anchor,
            "evidence": [],
            "metadata": {"source_stage": "semantic", "sql_ast": True},
        }

    if task == "risky_left_join":
        for iss in issues:
            if iss.get("problem_type") == "risky_left_join":
                return _issue_finding_dict(criterion, iss, anchor)
        return {
            "status": "pass",
            "confidence": 0.8,
            "anchor_position_idx": anchor,
            "evidence": [],
            "metadata": {"source_stage": "semantic", "sql_ast": True},
        }

    if task == "suspicious_group_by":
        for iss in issues:
            if iss.get("problem_type") == "suspicious_group_by":
                return _issue_finding_dict(criterion, iss, anchor)
        return {
            "status": "pass",
            "confidence": 0.82,
            "anchor_position_idx": anchor,
            "evidence": [],
            "metadata": {"source_stage": "semantic", "sql_ast": True},
        }

    if task == "ambiguous_metric_calculation":
        for iss in issues:
            if iss.get("problem_type") == "ambiguous_metric_calculation":
                return _issue_finding_dict(criterion, iss, anchor)
        return {
            "status": "pass",
            "confidence": 0.84,
            "anchor_position_idx": anchor,
            "evidence": [],
            "metadata": {"source_stage": "semantic", "sql_ast": True},
        }

    if task == "suspicious_division_without_guard_semantic":
        ast_hit = any(i.get("problem_type") == "division_without_nullif" for i in issues)
        if ast_hit:
            for iss in issues:
                if iss.get("problem_type") == "division_without_nullif":
                    return _issue_finding_dict(criterion, iss, anchor)
        if llm.semantic_checks_enabled:
            r = llm.classify_text(task, sql, {"ast_issues": len(issues)})
            st = r.label if r.label in ("pass", "warn", "fail", "unknown") else "unknown"
            if st == "fail" and criterion.get("severity") != "required":
                st = "warn"
            return {
                "status": st,
                "confidence": r.confidence,
                "anchor_position_idx": anchor,
                "evidence": [{"excerpt": r.evidence, "rationale": r.rationale}],
                "metadata": {
                    "source_stage": "llm",
                    "llm_used": True,
                    "criterion_code": task,
                    "ast_checked": True,
                },
            }
        return {
            "status": "pass",
            "confidence": 0.7,
            "anchor_position_idx": anchor,
            "evidence": [],
            "metadata": {"source_stage": "semantic", "note": "no_ast_div_issue", "llm_used": False},
        }

    if task == "suspicious_join_multiplication":
        risky = any(i.get("problem_type") == "risky_left_join" for i in issues)
        if risky:
            for iss in issues:
                if iss.get("problem_type") == "risky_left_join":
                    return _issue_finding_dict(criterion, iss, anchor)
        if llm.semantic_checks_enabled:
            r = llm.classify_text(task, sql, {"join_count": report.get("join_count")})
            st = r.label if r.label in ("pass", "warn", "fail", "unknown") else "unknown"
            if st == "fail" and criterion.get("severity") != "required":
                st = "warn"
            return {
                "status": st,
                "confidence": r.confidence,
                "anchor_position_idx": anchor,
                "evidence": [{"excerpt": r.evidence}],
                "metadata": {"source_stage": "llm", "llm_used": True},
            }
        return {
            "status": "pass",
            "confidence": 0.65,
            "anchor_position_idx": anchor,
            "evidence": [],
            "metadata": {"source_stage": "semantic", "llm_used": False},
        }

    if task == "metric_definition_consistency":
        if llm.semantic_checks_enabled:
            r = llm.classify_text(task, sql, {})
            st = r.label if r.label in ("pass", "warn", "fail", "unknown") else "unknown"
            if st == "unknown":
                st = "warn"
            if st == "fail" and criterion.get("severity") != "required":
                st = "warn"
            return {
                "status": st,
                "confidence": r.confidence,
                "anchor_position_idx": anchor,
                "evidence": [{"excerpt": r.evidence, "rationale": r.rationale}],
                "metadata": {"source_stage": "llm", "llm_used": True, "criterion_code": task},
            }
        return {
            "status": "unknown",
            "confidence": 0.35,
            "anchor_position_idx": anchor,
            "evidence": [],
            "metadata": {
                "source_stage": "semantic",
                "llm_used": False,
                "note": "enable_llm_semantic_checks_for_deeper_metric_review",
            },
        }

    return {
        "status": "unknown",
        "confidence": 0.2,
        "anchor_position_idx": anchor,
        "evidence": [],
        "metadata": {"task": task, "note": "sql_semantic_unhandled"},
    }
