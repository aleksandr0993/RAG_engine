from __future__ import annotations

import re
from typing import Any

from app.llm.service import LLMService

_CONC_WORDS = re.compile(
    r"вывод|итог|заключ|результат|объясн|интерпрет|можно сказать|следовательно",
    re.IGNORECASE,
)
_INTRO_WORDS = re.compile(r"цель|задач|данн|описание|введен", re.IGNORECASE)


def _ignored_artifact(artifact: dict) -> bool:
    meta = artifact.get("metadata_json") or artifact.get("metadata") or {}
    return bool(meta.get("is_practicum_instruction") or meta.get("is_reviewer_comment") or meta.get("is_middle_reviewer_comment"))


def _heuristic_intro(artifacts: list[dict], criterion: dict | None = None) -> dict:
    for a in artifacts:
        if _ignored_artifact(a):
            continue
        if a.get("artifact_type") != "markdown_cell":
            continue
        text = a.get("normalized_text") or ""
        if len(text.strip()) < 40:
            continue
        if _INTRO_WORDS.search(text):
            return {
                "status": "pass",
                "confidence": 0.72,
                "anchor_position_idx": a.get("position_idx"),
                "evidence": [{"excerpt": text[:280]}],
                "metadata": {"check": "has_meaningful_intro", "method": "heuristic"},
            }
    sev = (criterion or {}).get("severity")
    return {
        "status": "fail" if sev == "required" else "warn",
        "confidence": 0.55,
        "anchor_position_idx": None,
        "evidence": [],
        "metadata": {"check": "has_meaningful_intro", "method": "heuristic"},
    }


def _markdown_after_plot(artifacts: list[dict], section: str | None, label: str) -> dict | None:
    """Find markdown cell after a code cell with plot in/near section."""
    ordered = sorted([a for a in artifacts if a.get("position_idx") is not None], key=lambda x: x["position_idx"])
    for i, a in enumerate(ordered):
        if _ignored_artifact(a):
            continue
        if a.get("artifact_type") != "code_cell":
            continue
        meta = a.get("metadata_json") or a.get("metadata") or {}
        if not meta.get("has_plot_code"):
            continue
        if section and (a.get("section_name") or "") != section:
            continue
        for j in range(i + 1, min(i + 4, len(ordered))):
            nxt = ordered[j]
            if _ignored_artifact(nxt):
                continue
            if nxt.get("artifact_type") != "markdown_cell":
                continue
            t = nxt.get("normalized_text") or ""
            if len(t.strip()) < 25:
                continue
            if _CONC_WORDS.search(t) or meta.get("markdown_interpretation_hint"):
                return nxt
    return None


def _section_conclusion(artifacts: list[dict], section: str, code: str) -> dict:
    for a in artifacts:
        if _ignored_artifact(a):
            continue
        if a.get("artifact_type") != "markdown_cell":
            continue
        if (a.get("section_name") or "") != section:
            continue
        t = a.get("normalized_text") or ""
        if len(t.strip()) < 30:
            continue
        if _CONC_WORDS.search(t):
            return {
                "status": "pass",
                "confidence": 0.68,
                "anchor_position_idx": a.get("position_idx"),
                "evidence": [{"excerpt": t[:280]}],
                "metadata": {"criterion_code": code, "method": "heuristic"},
            }

    after = _markdown_after_plot(artifacts, section, code)
    if after:
        t = after.get("normalized_text") or ""
        return {
            "status": "pass",
            "confidence": 0.62,
            "anchor_position_idx": after.get("position_idx"),
            "evidence": [{"excerpt": t[:280]}],
            "metadata": {"criterion_code": code, "method": "heuristic", "note": "interpretation_after_plot"},
        }

    return {
        "status": "unknown",
        "confidence": 0.4,
        "anchor_position_idx": None,
        "evidence": [],
        "metadata": {"criterion_code": code, "method": "heuristic", "note": "no_clear_conclusion"},
    }


def _merge_llm(
    base: dict,
    llm_res: Any,
    criterion: dict,
    task: str,
) -> dict:
    if llm_res is None or getattr(llm_res, "confidence", 0) <= 0:
        return base
    if llm_res.confidence < 0.45 and llm_res.label == "unknown":
        return base
    status_map = {"pass": "pass", "warn": "warn", "fail": "fail", "unknown": "unknown"}
    st = status_map.get(llm_res.label, "unknown")
    if st == "unknown" and base["status"] != "unknown":
        return base
    sev = criterion.get("severity")
    if st == "fail" and sev != "required":
        st = "warn"
    return {
        "status": st,
        "confidence": round(min(0.95, max(base.get("confidence", 0.3), llm_res.confidence)), 4),
        "anchor_position_idx": base.get("anchor_position_idx"),
        "evidence": base.get("evidence", [])
        + [{"excerpt": llm_res.evidence[:250], "rationale": llm_res.rationale[:200]}],
        "metadata": {
            **base.get("metadata", {}),
            "source_stage": "llm",
            "llm_used": True,
            "llm_task": task,
            "llm_label": llm_res.label,
        },
    }


def run_notebook_semantic(
    task: str,
    artifacts: list[dict],
    criterion: dict,
    llm: LLMService | None = None,
) -> dict:
    """Notebook-only semantic checks with conservative heuristics and optional LLM refinement."""
    llm = llm or LLMService()

    if task == "has_meaningful_intro":
        base = _heuristic_intro(artifacts, criterion)
        if llm.semantic_checks_enabled:
            text = "\n\n".join(
                (a.get("normalized_text") or "")[:1200]
                for a in artifacts
                if a.get("artifact_type") == "markdown_cell" and (a.get("position_idx") or 0) <= 2 and not _ignored_artifact(a)
            )
            r = llm.classify_text(task, text, {"sections": [a.get("section_name") for a in artifacts[:5]]})
            return _merge_llm({**base, "metadata": {**base["metadata"], "source_stage": "semantic"}}, r, criterion, task)
        base["metadata"]["source_stage"] = "semantic"
        return base

    if task == "has_eda_conclusion":
        base = _section_conclusion(artifacts, "eda", "has_eda_conclusion")
        base["metadata"]["criterion_code"] = "has_eda_conclusion"
        if llm.semantic_checks_enabled:
            blob = "\n".join(
                (a.get("normalized_text") or "")[:800]
                for a in artifacts
                if a.get("section_name") == "eda" and not _ignored_artifact(a)
            )
            r = llm.classify_text(task, blob, {})
            return _merge_llm(base, r, criterion, task)
        base["metadata"]["source_stage"] = "semantic"
        return base

    if task == "has_modeling_conclusion":
        base = _section_conclusion(artifacts, "modeling", "has_modeling_conclusion")
        base["metadata"]["criterion_code"] = "has_modeling_conclusion"
        if llm.semantic_checks_enabled:
            blob = "\n".join(
                (a.get("normalized_text") or "")[:800]
                for a in artifacts
                if a.get("section_name") == "modeling" and not _ignored_artifact(a)
            )
            r = llm.classify_text(task, blob, {})
            return _merge_llm(base, r, criterion, task)
        base["metadata"]["source_stage"] = "semantic"
        return base

    if task == "has_final_conclusion":
        for a in reversed(artifacts):
            if _ignored_artifact(a):
                continue
            if a.get("artifact_type") != "markdown_cell":
                continue
            t = a.get("normalized_text") or ""
            if _CONC_WORDS.search(t) and len(t.strip()) > 35:
                base = {
                    "status": "pass",
                    "confidence": 0.75,
                    "anchor_position_idx": a.get("position_idx"),
                    "evidence": [{"excerpt": t[:280]}],
                    "metadata": {"criterion_code": "has_final_conclusion", "method": "heuristic"},
                }
                if llm.semantic_checks_enabled:
                    r = llm.classify_text(task, t[:2000], {})
                    return _merge_llm({**base, "metadata": {**base["metadata"], "source_stage": "semantic"}}, r, criterion, task)
                base["metadata"]["source_stage"] = "semantic"
                return base
        base = {
            "status": "warn" if criterion.get("severity") != "required" else "fail",
            "confidence": 0.58,
            "anchor_position_idx": None,
            "evidence": [],
            "metadata": {"criterion_code": "has_final_conclusion", "method": "heuristic"},
        }
        if llm.semantic_checks_enabled:
            blob = "\n".join(
                (a.get("normalized_text") or "")[:1200]
                for a in artifacts
                if a.get("artifact_type") == "markdown_cell" and not _ignored_artifact(a)
            )
            r = llm.classify_text(task, blob, {})
            return _merge_llm({**base, "metadata": {**base["metadata"], "source_stage": "semantic"}}, r, criterion, task)
        base["metadata"]["source_stage"] = "semantic"
        return base

    return {
        "status": "unknown",
        "confidence": 0.2,
        "anchor_position_idx": None,
        "evidence": [],
        "metadata": {"task": task, "note": "notebook_semantic_unhandled"},
    }
