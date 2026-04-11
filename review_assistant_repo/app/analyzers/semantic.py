from __future__ import annotations

import re

from app.analyzers.notebook_semantic import run_notebook_semantic
from app.analyzers.sql_semantic import run_sql_semantic
from app.llm.service import get_llm_service

_BUSINESS_PAT = re.compile(
    r"бизнес|выруч|kpi|метрик|инсайт|рекомендац|рост|паден|эффект|причин|интерпрет",
    re.IGNORECASE,
)
_TITLE_PAT = re.compile(r"^#{1,3}\s+\S+", re.MULTILINE)
_NOTE_PAT = re.compile(r"примечан|заметк|вывод|итог|summary|note", re.IGNORECASE)


class SemanticAnalyzer:
    def __init__(self):
        self._llm = get_llm_service()

    def check(self, task: str, artifacts: list[dict], criterion: dict) -> dict:
        # Notebook-specific semantic suite
        if task in {
            "has_meaningful_intro",
            "has_eda_conclusion",
            "has_modeling_conclusion",
            "has_final_conclusion",
        }:
            r = run_notebook_semantic(task, artifacts, criterion, self._llm)
            r.setdefault("metadata", {})["source_stage"] = "semantic"
            return r

        if task in {
            "division_without_nullif",
            "count_logic_mismatch",
            "risky_left_join",
            "suspicious_group_by",
            "ambiguous_metric_calculation",
            "suspicious_division_without_guard_semantic",
            "suspicious_join_multiplication",
            "metric_definition_consistency",
        }:
            r = run_sql_semantic(task, artifacts, criterion, self._llm)
            r.setdefault("metadata", {})["source_stage"] = "semantic"
            return r

        if task == "has_business_interpretation_text":
            return self._dashboard_text_task(task, artifacts, criterion, _BUSINESS_PAT, min_len=25)

        if task == "has_explanatory_titles":
            for artifact in artifacts:
                if artifact["artifact_type"] not in {"pdf_page", "pdf_text_block", "datalens_text_fragment", "markdown_cell"}:
                    continue
                text = artifact.get("normalized_text") or ""
                if len(_TITLE_PAT.findall(text)) >= 1 or len(text.splitlines()) > 2 and len(text) > 40:
                    return {
                        "status": "pass",
                        "confidence": 0.66,
                        "anchor_position_idx": artifact.get("position_idx"),
                        "evidence": [{"excerpt": text[:250]}],
                        "metadata": {"task": task, "source_stage": "semantic", "method": "heuristic"},
                    }
            return self._soft_fail(task, criterion, note="no_title_like_structure")

        if task == "has_conclusion_or_note_block":
            for artifact in artifacts:
                if artifact["artifact_type"] not in {"pdf_page", "pdf_text_block", "datalens_text_fragment", "markdown_cell"}:
                    continue
                text = artifact.get("normalized_text") or ""
                if _NOTE_PAT.search(text) and len(text.strip()) > 20:
                    return {
                        "status": "pass",
                        "confidence": 0.7,
                        "anchor_position_idx": artifact.get("position_idx"),
                        "evidence": [{"excerpt": text[:250]}],
                        "metadata": {"task": task, "source_stage": "semantic", "method": "heuristic"},
                    }
            return self._soft_fail(task, criterion, note="no_conclusion_block")

        if task == "has_markdown_conclusion":
            for artifact in artifacts:
                if artifact["artifact_type"] != "markdown_cell":
                    continue
                text = (artifact.get("normalized_text") or "").lower()
                if any(token in text for token in ["вывод", "итог", "можно сделать вывод", "результат исследования"]):
                    return {
                        "status": "pass",
                        "confidence": 0.86,
                        "anchor_position_idx": artifact.get("position_idx"),
                        "evidence": [{"excerpt": (artifact.get("normalized_text") or "")[:250]}],
                        "metadata": {"task": task, "source_stage": "semantic"},
                    }
            return {
                "status": "warn" if criterion["severity"] != "required" else "fail",
                "confidence": 0.82,
                "anchor_position_idx": None,
                "evidence": [],
                "metadata": {"task": task, "source_stage": "semantic"},
            }

        if task == "dangerous_division_guard":
            has_division = False
            for artifact in artifacts:
                if artifact["artifact_type"] != "sql_query":
                    continue
                text = (artifact.get("normalized_text") or "").lower()
                raw = (artifact.get("raw_text") or "").lower()
                if "/" in raw or "/" in text:
                    has_division = True
                    if "nullif(" in raw or "nullif(" in text:
                        return {
                            "status": "pass",
                            "confidence": 0.93,
                            "anchor_position_idx": artifact.get("position_idx"),
                            "evidence": [{"excerpt": (artifact.get("normalized_text") or "")[:250]}],
                            "metadata": {"task": task, "source_stage": "semantic"},
                        }
                    return {
                        "status": "fail",
                        "confidence": 0.92,
                        "anchor_position_idx": artifact.get("position_idx"),
                        "evidence": [{"excerpt": (artifact.get("normalized_text") or "")[:250]}],
                        "metadata": {"task": task, "source_stage": "semantic"},
                    }
            if not has_division:
                return {
                    "status": "pass",
                    "confidence": 0.8,
                    "anchor_position_idx": None,
                    "evidence": [],
                    "metadata": {"task": task, "note": "no division found", "source_stage": "semantic"},
                }

        return {
            "status": "unknown",
            "confidence": 0.2,
            "anchor_position_idx": None,
            "evidence": [],
            "metadata": {"task": task, "note": "not implemented", "source_stage": "semantic"},
        }

    def _dashboard_text_task(self, task: str, artifacts: list[dict], criterion: dict, pattern: re.Pattern, min_len: int) -> dict:
        for artifact in artifacts:
            if artifact["artifact_type"] not in {"pdf_page", "pdf_text_block", "datalens_text_fragment", "markdown_cell"}:
                continue
            text = artifact.get("normalized_text") or ""
            if len(text.strip()) < min_len:
                continue
            if pattern.search(text):
                return {
                    "status": "pass",
                    "confidence": 0.64,
                    "anchor_position_idx": artifact.get("position_idx"),
                    "evidence": [{"excerpt": text[:280]}],
                    "metadata": {"task": task, "source_stage": "semantic", "method": "heuristic"},
                }
        return self._soft_fail(task, criterion, note="no_business_interpretation")

    def _soft_fail(self, task: str, criterion: dict, note: str) -> dict:
        return {
            "status": "fail" if criterion.get("severity") == "required" else "warn",
            "confidence": 0.55,
            "anchor_position_idx": None,
            "evidence": [],
            "metadata": {"task": task, "note": note, "source_stage": "semantic"},
        }
