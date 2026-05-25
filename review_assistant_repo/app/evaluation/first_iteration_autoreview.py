from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import nbformat

from app.analyzers.rules import RuleEngine
from app.config import get_settings
from app.evaluation.quality_metrics import (
    aggregate_quality_evals,
    evaluate_comment_rows_quality,
    render_quality_summary_markdown,
)
from app.exporters.notebook import NotebookCommentInserter
from app.llm.service import LLMService, get_llm_service
from app.parsers.notebook import NotebookParser
from app.retrieval.reviewer_insertions import (
    choose_insertion_anchor,
    detect_alert_color,
    extract_features,
    extract_reviewer_insertions,
    load_insertion_rows,
    plain_text,
)
from app.services.comment_dedup import dedupe_notebook_insertions
from app.services.finding_policy import (
    apply_low_confidence_and_quality_policy,
    coerce_source_stage_metadata,
)
from app.services.notebook_memory import build_notebook_memory, select_relevant_memory_facts
from app.utils.config_loader import load_criteria_map
from app.utils.notebook_html import build_notebook_comment_html

_EXPLICIT_REVIEW_VERSION_RE = re.compile(r"Комментарий\s+ревьюера\s*\d+", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[\wа-яА-ЯёЁ]+", re.UNICODE)
_ACTIONABLE_STATUSES = {"memory_fail", "memory_warn"}
_ACTIONABLE_COMMENT_KINDS = {"actionable_feedback"}


def _write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 2}


def text_similarity(left: str, right: str) -> float:
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a | b), 4)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _bool_from_json(value: Any, *, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "да"}:
            return True
        if normalized in {"false", "no", "0", "нет"}:
            return False
    return default


def _alert_from_level(level: str) -> str:
    return "danger" if level == "danger" else "warning"


def _status_from_memory_kind(row: dict[str, Any]) -> str:
    kind = str(row.get("comment_kind") or "")
    if kind == "criterion_success":
        return "memory_success"
    if kind == "non_criterion_praise":
        return "memory_praise"
    if str(row.get("alert_color") or "") == "danger":
        return "memory_fail"
    return "memory_warn"


def _status_from_llm_classification(comment_kind: str, alert_color: str) -> str:
    if comment_kind == "criterion_success":
        return "memory_success"
    if comment_kind == "non_criterion_praise":
        return "memory_praise"
    if alert_color == "danger":
        return "memory_fail"
    return "memory_warn"


def _kind_from_memory_status(status: str) -> str:
    if status == "memory_success":
        return "criterion_success"
    if status == "memory_praise":
        return "non_criterion_praise"
    if status in {"memory_fail", "memory_warn"}:
        return "actionable_feedback"
    return "unknown"


def _public_gold_row(row: dict[str, Any]) -> dict[str, Any]:
    anchor = row.get("anchor_before") or {}
    return {
        "example_id": row.get("example_id"),
        "reviewed_notebook": row.get("reviewed_notebook"),
        "comment_text": row.get("comment_text"),
        "alert_color": row.get("alert_color"),
        "criterion_code": row.get("criterion_code"),
        "praise_code": row.get("praise_code"),
        "comment_kind": row.get("comment_kind"),
        "section_path": row.get("section_path") or [],
        "anchor_position_idx": row.get("anchor_position_idx"),
        "anchor_cell_type": anchor.get("cell_type") or "",
        "anchor_features": anchor.get("features") or [],
        "anchor_content_hash": anchor.get("content_hash") or "",
    }


def _memory_row_is_first_iteration(row: dict[str, Any]) -> bool:
    text = str(row.get("comment_text") or "")
    if _EXPLICIT_REVIEW_VERSION_RE.search(text):
        return False
    return int(row.get("review_iteration") or 1) == 1


def extract_gold_first_review_comments(
    *,
    restored_notebook: Path,
    reviewed_notebook: Path,
    project: str,
) -> list[dict[str, Any]]:
    rows = extract_reviewer_insertions(restored_notebook, reviewed_notebook, project_type=project)
    gold: list[dict[str, Any]] = []
    for row in rows:
        text = str(row.get("comment_text") or "")
        if _EXPLICIT_REVIEW_VERSION_RE.search(text):
            continue
        if int(row.get("review_iteration") or 1) != 1:
            continue
        gold.append(_public_gold_row(row))
    return gold


def _parse_artifacts(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    parsed, notebook_obj = NotebookParser().parse(str(path), strip_review_comments=True)
    artifacts: list[dict[str, Any]] = []
    for item in parsed:
        artifacts.append(
            {
                "artifact_type": item.artifact_type,
                "position_idx": item.position_idx,
                "section_name": item.section_name,
                "raw_text": item.raw_text,
                "normalized_text": item.normalized_text,
                "metadata_json": item.metadata,
            }
        )
    return artifacts, notebook_obj


def _artifact_text(artifact: dict[str, Any]) -> str:
    return str(artifact.get("normalized_text") or artifact.get("raw_text") or "")


def _artifact_features(artifact: dict[str, Any]) -> set[str]:
    return set(extract_features(_artifact_text(artifact)))


def _anchor_context(artifacts: list[dict[str, Any]], anchor_idx: int | None) -> dict[str, Any]:
    if anchor_idx is None:
        return {}
    ordered = sorted(
        [a for a in artifacts if a.get("position_idx") is not None],
        key=lambda item: int(item.get("position_idx") or 0),
    )
    current_pos = next((i for i, item in enumerate(ordered) if int(item.get("position_idx") or -1) == int(anchor_idx)), None)
    if current_pos is None:
        return {}
    return {
        "anchor_position_idx": anchor_idx,
        "cells": [
            {
                "position_idx": item.get("position_idx"),
                "artifact_type": item.get("artifact_type"),
                "section_name": item.get("section_name"),
                "text": _artifact_text(item)[:1800],
            }
            for item in ordered[max(0, current_pos - 1) : current_pos + 2]
        ],
    }


def _memory_candidate_score(artifact: dict[str, Any], row: dict[str, Any]) -> float:
    art_features = _artifact_features(artifact)
    row_features = set((row.get("anchor_before") or {}).get("features") or [])
    feature_score = len(art_features & row_features) / len(row_features) if row_features else 0.0
    artifact_text = _artifact_text(artifact)
    text_score = text_similarity(artifact_text, str((row.get("local_context") or {}).get("before_text") or ""))
    comment_score = text_similarity(artifact_text, str(row.get("comment_text") or ""))
    section_path = " ".join(str(x).lower() for x in (row.get("section_path") or []))
    section = str(artifact.get("section_name") or "").lower()
    section_score = 1.0 if section and section in section_path else 0.0
    kind_bonus = 0.10 if row.get("comment_kind") in {"actionable_feedback", "criterion_success", "non_criterion_praise"} else 0.0
    actionable_bonus = 0.06 if row.get("comment_kind") == "actionable_feedback" else 0.0
    if str(row.get("alert_color") or "") == "danger":
        actionable_bonus += 0.04
    base_score = 0.50 * feature_score + 0.30 * text_score + 0.10 * section_score + kind_bonus
    return round(min(1.0, base_score + 0.10 * comment_score + actionable_bonus), 4)


def _is_actionable_memory_candidate(item: dict[str, Any]) -> bool:
    return (
        str(item.get("comment_kind") or "") in _ACTIONABLE_COMMENT_KINDS
        or str(item.get("status") or "") in _ACTIONABLE_STATUSES
        or str(item.get("alert_color") or "") in {"danger", "warning"}
    )


def _memory_candidate_selection_score(item: dict[str, Any]) -> float:
    score = float(item.get("confidence") or 0.0)
    if _is_actionable_memory_candidate(item):
        score += 0.08
    if str(item.get("alert_color") or "") == "danger":
        score += 0.04
    return min(1.0, score)


def _best_memory_anchor(artifacts: list[dict[str, Any]], row: dict[str, Any]) -> tuple[int | None, float]:
    best_idx: int | None = None
    best_score = 0.0
    for artifact in artifacts:
        meta = artifact.get("metadata_json") or artifact.get("metadata") or {}
        if meta.get("is_reviewer_comment") or meta.get("is_middle_reviewer_comment") or meta.get("is_student_comment"):
            continue
        pos = artifact.get("position_idx")
        if pos is None:
            continue
        score = _memory_candidate_score(artifact, row)
        if score > best_score:
            best_idx = int(pos)
            best_score = score
    return best_idx, best_score


def generate_all_first_iteration_memory_candidates(
    *,
    artifacts: list[dict[str, Any]],
    memory_rows: list[dict[str, Any]],
    project: str,
    exclude_reviewed_notebook: str | None = None,
    min_score: float = 0.35,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in memory_rows:
        if exclude_reviewed_notebook and row.get("reviewed_notebook") == exclude_reviewed_notebook:
            continue
        row_project = str(row.get("project_type") or row.get("source_project") or "")
        if row_project and row_project != project:
            continue
        if not _memory_row_is_first_iteration(row):
            continue
        anchor_idx, score = _best_memory_anchor(artifacts, row)
        if anchor_idx is None or score < min_score:
            continue
        status = _status_from_memory_kind(row)
        comment_text = str(row.get("comment_text") or "")
        alert_color = str(row.get("alert_color") or detect_alert_color(comment_text) or "unknown")
        candidates.append(
            {
                "criterion_code": str(row.get("criterion_code") or ""),
                "praise_code": str(row.get("praise_code") or ""),
                "status": status,
                "severity": "memory",
                "confidence": score,
                "anchor_position_idx": anchor_idx,
                "alert_color": alert_color,
                "comment_kind": row.get("comment_kind") or _kind_from_memory_status(status),
                "comment_text": comment_text,
                "comment_html": build_notebook_comment_html("Комментарий:", comment_text, level=alert_color),
                "evidence": [],
                "metadata": {
                    "source_stage": "memory_retrieval",
                    "memory_candidate_score": score,
                    "memory_example_id": row.get("example_id"),
                    "memory_reviewed_notebook": row.get("reviewed_notebook"),
                    "memory_source_notebook": row.get("source_notebook"),
                },
            }
        )

    candidates.sort(
        key=lambda item: (
            -float(item.get("confidence") or 0),
            str(item.get("criterion_code") or ""),
            int(item.get("anchor_position_idx") or 0),
        )
    )
    return candidates


def generate_first_iteration_memory_candidates(
    *,
    artifacts: list[dict[str, Any]],
    memory_rows: list[dict[str, Any]],
    project: str,
    exclude_reviewed_notebook: str | None = None,
    min_score: float = 0.35,
    max_candidates: int = 40,
    max_per_criterion_kind: int = 4,
    actionable_min_score: float | None = None,
    max_actionable_candidates: int = 20,
) -> list[dict[str, Any]]:
    actionable_threshold = (
        actionable_min_score
        if actionable_min_score is not None
        else min(float(min_score), max(0.35, float(min_score) - 0.20))
    )
    candidates = generate_all_first_iteration_memory_candidates(
        artifacts=artifacts,
        memory_rows=memory_rows,
        project=project,
        exclude_reviewed_notebook=exclude_reviewed_notebook,
        min_score=min(float(min_score), float(actionable_threshold)),
    )
    picked: list[dict[str, Any]] = []
    per_group: Counter[tuple[str, str]] = Counter()
    seen_text_anchor: set[tuple[str, int]] = set()
    actionable_picked = 0

    def can_pick(item: dict[str, Any]) -> bool:
        score = float(item.get("confidence") or 0.0)
        if _is_actionable_memory_candidate(item):
            return score >= float(actionable_threshold)
        return score >= float(min_score)

    def pick(item: dict[str, Any]) -> bool:
        nonlocal actionable_picked
        is_actionable = _is_actionable_memory_candidate(item)
        if is_actionable and actionable_picked >= max_actionable_candidates:
            return False
        key = (str(item.get("criterion_code") or ""), str(item.get("comment_kind") or item.get("status") or ""))
        if per_group[key] >= max_per_criterion_kind:
            return False
        text_key = (plain_text(str(item.get("comment_text") or "")).lower(), int(item.get("anchor_position_idx") or 0))
        if text_key in seen_text_anchor:
            return False
        seen_text_anchor.add(text_key)
        per_group[key] += 1
        picked.append(item)
        if is_actionable:
            actionable_picked += 1
        return True

    actionable_candidates = sorted(
        [item for item in candidates if _is_actionable_memory_candidate(item) and can_pick(item)],
        key=lambda item: (
            -_memory_candidate_selection_score(item),
            str(item.get("criterion_code") or ""),
            int(item.get("anchor_position_idx") or 0),
        ),
    )
    for item in actionable_candidates:
        if actionable_picked >= max_actionable_candidates:
            break
        pick(item)
        if len(picked) >= max_candidates:
            return picked

    for item in candidates:
        if not can_pick(item):
            continue
        pick(item)
        if len(picked) >= max_candidates:
            break
    return picked


def _rank_auc(points: list[tuple[float, int]]) -> float | None:
    positives = [score for score, label in points if label == 1]
    negatives = [score for score, label in points if label == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    total = len(positives) * len(negatives)
    for pos in positives:
        for neg in negatives:
            if pos > neg:
                wins += 1.0
            elif pos == neg:
                wins += 0.5
    return round(wins / total, 4)


def _average_precision(points: list[tuple[float, int]]) -> float | None:
    positives = sum(1 for _, label in points if label == 1)
    if positives == 0:
        return None
    ranked = sorted(points, key=lambda item: item[0], reverse=True)
    hits = 0
    precision_sum = 0.0
    for idx, (_score, label) in enumerate(ranked, start=1):
        if label != 1:
            continue
        hits += 1
        precision_sum += hits / idx
    return round(precision_sum / positives, 4)


def _candidate_keep_score(row: dict[str, Any], *, score_field: str | None = None) -> float:
    if score_field:
        value = row.get(score_field)
        if value is not None:
            return max(0.0, min(1.0, float(value)))
    meta = row.get("metadata") or {}
    for key in ("keep_score", "llm_keep_score", "llm_judge_keep_score"):
        value = row.get(key, meta.get(key))
        if value is not None:
            return max(0.0, min(1.0, float(value)))
    return max(0.0, min(1.0, float(row.get("confidence") or 0.0)))


def _classification_counts(points: list[tuple[float, int]], threshold: float) -> dict[str, Any]:
    tp = fp = fn = tn = 0
    for score, label in points:
        predicted_positive = score >= threshold
        if predicted_positive and label == 1:
            tp += 1
        elif predicted_positive and label == 0:
            fp += 1
        elif not predicted_positive and label == 1:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": round(threshold, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _best_f1_threshold(points: list[tuple[float, int]]) -> dict[str, Any]:
    if not points:
        return _classification_counts([], 0.5)
    if not any(label == 1 for _score, label in points):
        return _classification_counts(points, 1.0)
    thresholds = sorted({0.0, 1.0, 0.5, *(score for score, _label in points)})
    best = _classification_counts(points, thresholds[0])
    for threshold in thresholds[1:]:
        metrics = _classification_counts(points, threshold)
        if (metrics["f1"], metrics["precision"], metrics["recall"]) > (
            best["f1"],
            best["precision"],
            best["recall"],
        ):
            best = metrics
    return best


def _candidate_breakdowns(labeled: list[dict[str, Any]], *, decision_threshold: float) -> dict[str, Any]:
    specs = {
        "by_project": lambda row: str(row.get("project") or "unknown"),
        "by_criterion_code": lambda row: str(row.get("criterion_code") or "unknown"),
        "by_status": lambda row: str(row.get("status") or "unknown"),
        "by_source_stage": lambda row: str((row.get("metadata") or {}).get("source_stage") or "unknown"),
        "by_comment_kind": lambda row: str(row.get("comment_kind") or "unknown"),
    }
    out: dict[str, Any] = {}
    for name, key_fn in specs.items():
        buckets: dict[str, list[tuple[float, int]]] = {}
        for row in labeled:
            buckets.setdefault(key_fn(row), []).append((float(row.get("keep_score") or 0.0), int(row.get("auc_label") or 0)))
        out[name] = {
            key: {
                "candidate_total": len(points),
                "positive_candidates": sum(label for _score, label in points),
                "negative_candidates": len(points) - sum(label for _score, label in points),
                "roc_auc": _rank_auc(points),
                "pr_auc_average_precision": _average_precision(points),
                "at_threshold": _classification_counts(points, decision_threshold),
            }
            for key, points in sorted(buckets.items())
        }
    return out


def label_memory_candidates_for_auc(
    candidates: list[dict[str, Any]],
    gold: list[dict[str, Any]],
    *,
    min_match_score: float = 0.35,
    decision_threshold: float = 0.5,
    score_field: str | None = None,
    project: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    unmatched_gold = set(range(len(gold)))
    labeled: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: float(item.get("confidence") or 0), reverse=True):
        best: tuple[float, int] | None = None
        for gi in unmatched_gold:
            gold_row = gold[gi]
            if gold_row.get("criterion_code") and candidate.get("criterion_code") != gold_row.get("criterion_code"):
                continue
            score = _match_score(candidate, gold_row)
            if best is None or score > best[0]:
                best = (score, gi)
        label = 0
        matched_gold_index: int | None = None
        match_score = 0.0
        if best is not None and best[0] >= min_match_score:
            match_score, matched_gold_index = best
            unmatched_gold.remove(matched_gold_index)
            label = 1
        row = dict(candidate)
        row["auc_label"] = label
        row["label"] = label
        row["matched_gold_index"] = matched_gold_index
        row["match_score"] = match_score
        row["keep_score"] = _candidate_keep_score(row, score_field=score_field)
        row["project"] = project or row.get("project") or ""
        if matched_gold_index is not None:
            p_anchor = row.get("anchor_position_idx")
            g_anchor = gold[matched_gold_index].get("anchor_position_idx")
            row["anchor_delta"] = (
                abs(int(p_anchor) - int(g_anchor)) if p_anchor is not None and g_anchor is not None else None
            )
        labeled.append(row)

    points = [(float(row.get("keep_score") or 0), int(row["auc_label"])) for row in labeled]
    positives = sum(label for _, label in points)
    summary = {
        "candidate_total": len(labeled),
        "positive_candidates": positives,
        "negative_candidates": len(labeled) - positives,
        "roc_auc": _rank_auc(points),
        "pr_auc_average_precision": _average_precision(points),
        "score_field": score_field or "keep_score|confidence",
        "decision_threshold": round(decision_threshold, 4),
        "at_threshold": _classification_counts(points, decision_threshold),
        "best_f1_on_this_set": _best_f1_threshold(points),
        "breakdowns": _candidate_breakdowns(labeled, decision_threshold=decision_threshold),
    }
    return labeled, summary


def apply_llm_judge_generator(
    candidates: list[dict[str, Any]],
    *,
    artifacts: list[dict[str, Any]],
    project_memory: dict[str, Any] | None = None,
    llm_service: LLMService | None = None,
    enable_judge: bool = False,
    enable_generator: bool = False,
    enable_classifier: bool = False,
    enable_anchor_validator: bool = False,
    max_candidates: int = 30,
) -> list[dict[str, Any]]:
    if not (enable_judge or enable_generator or enable_classifier or enable_anchor_validator):
        return candidates

    llm = llm_service or get_llm_service()
    if not llm.is_available:
        out: list[dict[str, Any]] = []
        for item in candidates:
            updated = dict(item)
            meta = dict(updated.get("metadata") or {})
            meta["llm_skipped"] = "llm_unavailable"
            updated["metadata"] = meta
            out.append(updated)
        return out

    refined: list[dict[str, Any]] = []
    for idx, item in enumerate(candidates):
        updated = dict(item)
        meta = dict(updated.get("metadata") or {})
        if idx >= max_candidates:
            refined.append(updated)
            continue

        anchor_ctx = _anchor_context(artifacts, updated.get("anchor_position_idx"))
        anchor_section = ""
        cells = anchor_ctx.get("cells") if isinstance(anchor_ctx, dict) else None
        if isinstance(cells, list) and cells:
            anchor_section = str((cells[min(1, len(cells) - 1)] or {}).get("section_name") or "")
        context = {
            "candidate": {
                "criterion_code": updated.get("criterion_code"),
                "praise_code": updated.get("praise_code"),
                "status": updated.get("status"),
                "comment_kind": updated.get("comment_kind"),
                "alert_color": updated.get("alert_color"),
                "comment_text": updated.get("comment_text"),
                "evidence": updated.get("evidence") or [],
                "memory_candidate_score": meta.get("memory_candidate_score") or updated.get("confidence"),
            },
            "anchor_context": anchor_ctx,
            "project_memory": select_relevant_memory_facts(
                project_memory,
                criterion_code=str(updated.get("criterion_code") or ""),
                section_name=anchor_section,
                anchor_position_idx=updated.get("anchor_position_idx"),
                query_text=str(updated.get("comment_text") or ""),
                limit=5,
            ),
        }

        keep = True
        anchor_valid = True
        if enable_classifier:
            prompt = (
                "Ты классифицируешь комментарий ревьюера к учебной Jupyter-тетрадке.\n"
                "Верни только JSON: {"
                '"comment_kind": "actionable_feedback|criterion_success|non_criterion_praise|reviewer_note", '
                '"criterion_code": "... или пусто", '
                '"praise_code": "... или пусто", '
                '"alert_color": "danger|warning|success|unknown", '
                '"confidence": 0..1, '
                '"rationale": "..."}.\n'
                "actionable_feedback = нужно исправить; criterion_success = похвала по критерию; "
                "non_criterion_praise = общая похвала; reviewer_note = служебная заметка/не вставлять как проверку.\n"
                f"Данные:\n{json.dumps(context, ensure_ascii=False)[:12000]}"
            )
            result = llm.chat([{"role": "user", "content": prompt}], temperature=0.1)
            meta["llm_classifier_used"] = bool(result.ok)
            if result.ok:
                parsed = _extract_json_object(result.text)
                if parsed:
                    llm_kind = str(parsed.get("comment_kind") or "").strip()
                    llm_alert = str(parsed.get("alert_color") or "").strip()
                    if llm_kind in {"actionable_feedback", "criterion_success", "non_criterion_praise", "reviewer_note"}:
                        updated["comment_kind"] = llm_kind
                        meta["llm_comment_kind"] = llm_kind
                    if llm_alert in {"danger", "warning", "success", "unknown"}:
                        updated["alert_color"] = llm_alert
                        meta["llm_alert_color"] = llm_alert
                    criterion_code = str(parsed.get("criterion_code") or "").strip()
                    praise_code = str(parsed.get("praise_code") or "").strip()
                    if criterion_code:
                        updated["criterion_code"] = criterion_code
                    if praise_code:
                        updated["praise_code"] = praise_code
                    if llm_kind == "reviewer_note":
                        keep = False
                    if llm_kind in {"actionable_feedback", "criterion_success", "non_criterion_praise"}:
                        updated["status"] = _status_from_llm_classification(
                            llm_kind,
                            str(updated.get("alert_color") or "warning"),
                        )
                    meta["llm_classifier_confidence"] = parsed.get("confidence")
                    meta["llm_classifier_rationale"] = str(parsed.get("rationale") or "")[:500]
                else:
                    meta["llm_classifier_error"] = "unparseable_response"
            else:
                meta["llm_classifier_error"] = result.error or "llm_call_failed"

        if enable_judge:
            judge_context = {
                **context,
                "candidate": {
                    **context["candidate"],
                    "criterion_code": updated.get("criterion_code"),
                    "praise_code": updated.get("praise_code"),
                    "status": updated.get("status"),
                    "comment_kind": updated.get("comment_kind"),
                    "alert_color": updated.get("alert_color"),
                    "comment_text": updated.get("comment_text"),
                },
            }
            prompt = (
                "Ты оцениваешь, стоит ли вставлять комментарий ревьюера в учебную Jupyter-тетрадку.\n"
                "Верни только JSON: {"
                '"keep_score": 0..1, '
                '"keep_decision": true|false, '
                '"anchor_ok": true|false, '
                '"criterion_ok": true|false, '
                '"source_support": "strong|medium|weak|none", '
                '"style_match_score": 0..1, '
                '"reason": "..."}.\n'
                "Для обратной совместимости допустимы старые поля keep/confidence/rationale, но предпочтительны новые.\n"
                "Оставляй комментарий только если он конкретно относится к anchor_context и не является лишним дублем.\n"
                f"Данные:\n{json.dumps(judge_context, ensure_ascii=False)[:12000]}"
            )
            result = llm.chat([{"role": "user", "content": prompt}], temperature=0.1)
            meta["llm_judge_used"] = bool(result.ok)
            if result.ok:
                parsed = _extract_json_object(result.text)
                if parsed:
                    if "keep_decision" in parsed:
                        keep = _bool_from_json(parsed.get("keep_decision"), default=True)
                    else:
                        keep = _bool_from_json(parsed.get("keep"), default=True)
                    anchor_ok = _bool_from_json(parsed.get("anchor_ok"), default=True)
                    criterion_ok = _bool_from_json(parsed.get("criterion_ok"), default=True)
                    if "keep_score" in parsed:
                        keep_score = max(0.0, min(1.0, float(parsed.get("keep_score") or 0.0)))
                    else:
                        confidence = parsed.get("confidence")
                        keep_confidence = max(0.0, min(1.0, float(confidence if confidence is not None else 0.5)))
                        keep_score = keep_confidence if keep else 1.0 - keep_confidence
                    keep = keep and anchor_ok and criterion_ok
                    updated["keep_score"] = keep_score
                    meta["llm_judge_keep"] = keep
                    meta["llm_keep_score"] = keep_score
                    meta["llm_judge_keep_score"] = keep_score
                    meta["llm_keep_decision"] = keep
                    meta["llm_anchor_ok"] = anchor_ok
                    meta["llm_criterion_ok"] = criterion_ok
                    source_support = str(parsed.get("source_support") or "").strip().lower()
                    if source_support in {"strong", "medium", "weak", "none"}:
                        meta["llm_source_support"] = source_support
                    if parsed.get("style_match_score") is not None:
                        meta["llm_style_match_score"] = max(0.0, min(1.0, float(parsed.get("style_match_score") or 0.0)))
                    meta["llm_judge_confidence"] = parsed.get("confidence")
                    meta["llm_judge_rationale"] = str(parsed.get("reason") or parsed.get("rationale") or "")[:500]
                else:
                    meta["llm_judge_error"] = "unparseable_response"
            else:
                meta["llm_judge_error"] = result.error or "llm_call_failed"

        if not keep:
            meta["source_stage"] = "llm"
            updated["metadata"] = meta
            refined.append(updated)
            continue

        if enable_anchor_validator:
            validator_context = {
                **context,
                "candidate": {
                    **context["candidate"],
                    "criterion_code": updated.get("criterion_code"),
                    "praise_code": updated.get("praise_code"),
                    "comment_kind": updated.get("comment_kind"),
                    "alert_color": updated.get("alert_color"),
                    "comment_text": updated.get("comment_text"),
                },
            }
            prompt = (
                "Ты проверяешь место вставки комментария ревьюера в Jupyter-тетрадке.\n"
                "Верни только JSON: {"
                '"valid": true|false, '
                '"confidence": 0..1, '
                '"rationale": "...", '
                '"better_anchor_hint": "... или пусто"}.\n'
                "valid=true только если anchor_context действительно расположен рядом с проблемой, решением или похвалой, "
                "к которой относится комментарий. Если связь слабая, ставь valid=false.\n"
                f"Данные:\n{json.dumps(validator_context, ensure_ascii=False)[:12000]}"
            )
            result = llm.chat([{"role": "user", "content": prompt}], temperature=0.1)
            meta["llm_anchor_validator_used"] = bool(result.ok)
            if result.ok:
                parsed = _extract_json_object(result.text)
                if parsed:
                    anchor_valid = bool(parsed.get("valid", True))
                    meta["llm_anchor_valid"] = anchor_valid
                    meta["llm_anchor_confidence"] = parsed.get("confidence")
                    meta["llm_anchor_rationale"] = str(parsed.get("rationale") or "")[:500]
                    hint = str(parsed.get("better_anchor_hint") or "").strip()
                    if hint:
                        meta["llm_anchor_better_hint"] = hint[:500]
                else:
                    meta["llm_anchor_validator_error"] = "unparseable_response"
            else:
                meta["llm_anchor_validator_error"] = result.error or "llm_call_failed"

        if not anchor_valid:
            meta["source_stage"] = "llm"
            updated["metadata"] = meta
            refined.append(updated)
            continue

        if enable_generator:
            prompt = (
                "Ты адаптируешь комментарий ревьюера под текущую тетрадку, сохраняя стиль автора.\n"
                "Верни только JSON: {\"comment_text\": \"...\", \"rationale\": \"...\"}.\n"
                "Не добавляй приветствие или итоговый комментарий. Не упоминай, что ты LLM.\n"
                f"Данные:\n{json.dumps(context, ensure_ascii=False)[:12000]}"
            )
            result = llm.chat([{"role": "user", "content": prompt}], temperature=0.25)
            meta["llm_generator_used"] = bool(result.ok)
            if result.ok:
                parsed = _extract_json_object(result.text)
                generated = str((parsed or {}).get("comment_text") or "").strip()
                if generated:
                    updated["comment_text"] = generated
                    updated["comment_html"] = build_notebook_comment_html(
                        "Комментарий:",
                        generated,
                        level=str(updated.get("alert_color") or "warning"),
                    )
                    meta["llm_generator_rationale"] = str((parsed or {}).get("rationale") or "")[:500]
                else:
                    meta["llm_generator_error"] = "empty_or_unparseable_response"
            else:
                meta["llm_generator_error"] = result.error or "llm_call_failed"

        if (
            meta.get("llm_judge_used")
            or meta.get("llm_generator_used")
            or meta.get("llm_classifier_used")
            or meta.get("llm_anchor_validator_used")
        ):
            meta["source_stage"] = "llm"
        updated["metadata"] = meta
        refined.append(updated)
    return refined


def run_offline_autoreview(
    *,
    restored_notebook: Path,
    criteria_map: str,
    project: str,
    reviewer_insertions_path: Path | None = None,
    exclude_reviewed_notebook: str | None = None,
    include_memory_candidates: bool = True,
    memory_candidate_min_score: float = 0.35,
    max_memory_candidates: int = 30,
    memory_actionable_min_score: float | None = None,
    max_actionable_memory_candidates: int = 20,
    enable_llm_judge: bool = False,
    enable_llm_generator: bool = False,
    enable_llm_classifier: bool = False,
    enable_llm_anchor_validator: bool = False,
    llm_max_candidates: int = 30,
    llm_service: LLMService | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], dict[str, Any] | None, list[dict[str, Any]]]:
    criteria = load_criteria_map(criteria_map)
    artifacts, notebook_obj = _parse_artifacts(restored_notebook)
    settings = get_settings()
    llm = llm_service or get_llm_service()
    notebook_memory_payload = build_notebook_memory(
        artifacts=artifacts,
        criteria=criteria,
        llm_service=llm,
        settings=settings,
    )
    project_memory = notebook_memory_payload.get("memory") if isinstance(notebook_memory_payload, dict) else None
    raw_results = RuleEngine().run(artifacts, criteria)
    memory_rows = load_insertion_rows(reviewer_insertions_path) if reviewer_insertions_path else []
    if exclude_reviewed_notebook:
        memory_rows = [r for r in memory_rows if r.get("reviewed_notebook") != exclude_reviewed_notebook]
    all_memory_candidates = (
        generate_all_first_iteration_memory_candidates(
            artifacts=artifacts,
            memory_rows=memory_rows,
            project=project,
            exclude_reviewed_notebook=None,
            min_score=0.0,
        )
        if memory_rows
        else []
    )

    predicted: list[dict[str, Any]] = []
    notebook_insertions: list[dict[str, Any]] = []
    for criterion, result in zip(criteria, raw_results, strict=True):
        criterion_code = str(criterion["code"])
        severity = str(criterion.get("severity") or "")
        status = str(result.get("status") or "unknown")
        metadata = coerce_source_stage_metadata(dict(result.get("metadata") or {}), criterion.get("detection_mode"))
        outcome = apply_low_confidence_and_quality_policy(
            status=status,
            severity=severity,
            confidence=result.get("confidence"),
            metadata=metadata,
            criterion_code=criterion_code,
            min_confidence_for_required_fail=settings.finding_min_confidence_for_required_fail,
            enabled=settings.finding_policy_enabled,
        )
        final_status = outcome.status
        if final_status == "pass":
            continue

        templates = criterion.get("comment_templates") or {}
        comment_text = templates.get("fail") or criterion.get("description") or criterion.get("title") or criterion_code
        level = "danger" if severity == "required" and final_status in {"fail", "unknown"} else "warning"
        anchor_position_idx = result.get("anchor_position_idx")
        meta = dict(outcome.metadata)
        if memory_rows and (anchor_position_idx is None or not result.get("evidence")):
            learned = choose_insertion_anchor(
                artifacts,
                memory_rows,
                project_type=project,
                criterion_code=criterion_code,
                alert_color=_alert_from_level(level),
                query_text=str(comment_text),
                min_score=settings.reviewer_insertion_min_score,
            )
            if learned is not None:
                anchor_position_idx = learned.position_idx
                meta["reviewer_insertion_memory"] = {
                    "score": learned.score,
                    "example_id": learned.example.get("example_id"),
                    "source_notebook": learned.example.get("source_notebook"),
                }
        if anchor_position_idx is None:
            anchor_position_idx = max((int(a.get("position_idx") or 0) for a in artifacts), default=0)

        html = build_notebook_comment_html("Корректировка решения:", str(comment_text), level=level)
        predicted.append(
            {
                "criterion_code": criterion_code,
                "status": final_status,
                "severity": severity,
                "confidence": outcome.confidence,
                "anchor_position_idx": int(anchor_position_idx),
                "alert_color": _alert_from_level(level),
                "comment_text": str(comment_text),
                "comment_html": html,
                "evidence": result.get("evidence") or [],
                "metadata": meta,
            }
        )
        notebook_insertions.append({"anchor_position_idx": int(anchor_position_idx), "comment_html": html})

    if include_memory_candidates and memory_rows:
        memory_candidates = generate_first_iteration_memory_candidates(
            artifacts=artifacts,
            memory_rows=memory_rows,
            project=project,
            exclude_reviewed_notebook=exclude_reviewed_notebook,
            min_score=memory_candidate_min_score,
            max_candidates=max_memory_candidates,
            actionable_min_score=memory_actionable_min_score,
            max_actionable_candidates=max_actionable_memory_candidates,
        )
        memory_candidates = apply_llm_judge_generator(
            memory_candidates,
            artifacts=artifacts,
            project_memory=project_memory,
            llm_service=llm,
            enable_judge=enable_llm_judge,
            enable_generator=enable_llm_generator,
            enable_classifier=enable_llm_classifier,
            enable_anchor_validator=enable_llm_anchor_validator,
            max_candidates=llm_max_candidates,
        )
        existing = {
            (str(item.get("criterion_code") or ""), int(item.get("anchor_position_idx") or 0), str(item.get("comment_text") or ""))
            for item in predicted
        }
        for item in memory_candidates:
            meta = item.get("metadata") or {}
            if meta.get("llm_judge_keep") is False or meta.get("llm_anchor_valid") is False:
                continue
            key = (str(item.get("criterion_code") or ""), int(item.get("anchor_position_idx") or 0), str(item.get("comment_text") or ""))
            if key in existing:
                continue
            predicted.append(item)
            notebook_insertions.append({"anchor_position_idx": int(item["anchor_position_idx"]), "comment_html": item["comment_html"]})
            existing.add(key)

    deduped = dedupe_notebook_insertions(notebook_insertions)
    reviewed_obj = NotebookCommentInserter().insert_comments(notebook_obj, deduped)
    return predicted, reviewed_obj, all_memory_candidates, project_memory, artifacts


def _match_score(pred: dict[str, Any], gold: dict[str, Any]) -> float:
    score = 0.0
    if pred.get("criterion_code") and pred.get("criterion_code") == gold.get("criterion_code"):
        score += 0.45
    if pred.get("alert_color") == gold.get("alert_color"):
        score += 0.15
    p_anchor = pred.get("anchor_position_idx")
    g_anchor = gold.get("anchor_position_idx")
    if p_anchor is not None and g_anchor is not None:
        delta = abs(int(p_anchor) - int(g_anchor))
        score += max(0.0, 0.25 - min(delta, 5) * 0.05)
    score += 0.15 * text_similarity(str(pred.get("comment_text") or ""), str(gold.get("comment_text") or ""))
    return round(score, 4)


def compare_predictions(predicted: list[dict[str, Any]], gold: list[dict[str, Any]]) -> dict[str, Any]:
    unmatched_pred = set(range(len(predicted)))
    matches: list[dict[str, Any]] = []
    missed: list[dict[str, Any]] = []

    for gi, gold_row in enumerate(gold):
        best: tuple[float, int] | None = None
        for pi in unmatched_pred:
            pred = predicted[pi]
            if gold_row.get("criterion_code") and pred.get("criterion_code") != gold_row.get("criterion_code"):
                continue
            score = _match_score(pred, gold_row)
            if best is None or score > best[0]:
                best = (score, pi)
        if best is None or best[0] < 0.35:
            missed.append({"gold_index": gi, **gold_row})
            continue
        _, pi = best
        unmatched_pred.remove(pi)
        pred = predicted[pi]
        p_anchor = pred.get("anchor_position_idx")
        g_anchor = gold_row.get("anchor_position_idx")
        delta = abs(int(p_anchor) - int(g_anchor)) if p_anchor is not None and g_anchor is not None else None
        matches.append(
            {
                "gold_index": gi,
                "predicted_index": pi,
                "score": best[0],
                "anchor_delta": delta,
                "criterion_match": pred.get("criterion_code") == gold_row.get("criterion_code"),
                "alert_match": pred.get("alert_color") == gold_row.get("alert_color"),
                "text_similarity": text_similarity(str(pred.get("comment_text") or ""), str(gold_row.get("comment_text") or "")),
                "gold": gold_row,
                "predicted": pred,
            }
        )

    extra = [{"predicted_index": pi, **predicted[pi]} for pi in sorted(unmatched_pred)]
    actionable_gold = [g for g in gold if g.get("comment_kind") == "actionable_feedback"]
    actionable_missed = [m for m in missed if m.get("comment_kind") == "actionable_feedback"]
    anchor_deltas = [m["anchor_delta"] for m in matches if m.get("anchor_delta") is not None]
    return {
        "summary": {
            "gold_total": len(gold),
            "gold_actionable": len(actionable_gold),
            "predicted_total": len(predicted),
            "matched_total": len(matches),
            "missed_total": len(missed),
            "missed_actionable": len(actionable_missed),
            "extra_total": len(extra),
            "precision_approx": round(len(matches) / len(predicted), 4) if predicted else 0.0,
            "recall_approx": round(len(matches) / len(gold), 4) if gold else 0.0,
            "actionable_recall_approx": round((len(actionable_gold) - len(actionable_missed)) / len(actionable_gold), 4)
            if actionable_gold
            else 0.0,
            "anchor_exact": sum(1 for d in anchor_deltas if d == 0),
            "anchor_within_1": sum(1 for d in anchor_deltas if d <= 1),
            "anchor_within_2": sum(1 for d in anchor_deltas if d <= 2),
            "anchor_mean_delta": round(sum(anchor_deltas) / len(anchor_deltas), 4) if anchor_deltas else None,
            "gold_comment_kind_counts": dict(Counter(g.get("comment_kind") or "unknown" for g in gold)),
            "predicted_status_counts": dict(Counter(p.get("status") or "unknown" for p in predicted)),
            "predicted_source_stage_counts": dict(
                Counter((p.get("metadata") or {}).get("source_stage") or "unknown" for p in predicted)
            ),
        },
        "matches": matches,
        "missed_gold": missed,
        "extra_predicted": extra,
    }


def render_report(payload: dict[str, Any]) -> str:
    s = payload["comparison"]["summary"]
    auc = payload.get("candidate_auc") or {}
    at_threshold = auc.get("at_threshold") or {}
    lines = [
        "# First-iteration autoreview evaluation",
        "",
        f"- Reviewed notebook: `{payload['reviewed_notebook']}`",
        f"- Restored notebook: `{payload['restored_notebook']}`",
        f"- Criteria map: `{payload['criteria_map']}`",
        "",
        "## Summary",
        "",
        f"- Gold comments: {s['gold_total']} (actionable: {s['gold_actionable']})",
        f"- Predicted comments: {s['predicted_total']}",
        f"- Matched: {s['matched_total']}",
        f"- Missed gold: {s['missed_total']} (actionable: {s['missed_actionable']})",
        f"- Extra predicted: {s['extra_total']}",
        f"- Approx precision / recall: {s['precision_approx']} / {s['recall_approx']}",
        f"- Actionable recall: {s['actionable_recall_approx']}",
        f"- Anchor exact / within 1 / within 2: {s['anchor_exact']} / {s['anchor_within_1']} / {s['anchor_within_2']}",
        f"- Anchor mean delta: {s['anchor_mean_delta']}",
        f"- Gold kinds: {json.dumps(s['gold_comment_kind_counts'], ensure_ascii=False)}",
        f"- Predicted statuses: {json.dumps(s['predicted_status_counts'], ensure_ascii=False)}",
        f"- Predicted source stages: {json.dumps(s.get('predicted_source_stage_counts', {}), ensure_ascii=False)}",
        f"- Memory candidate ROC-AUC: {auc.get('roc_auc')}",
        f"- Memory candidate PR-AUC/AP: {auc.get('pr_auc_average_precision')}",
        f"- Memory candidate F1 @ {at_threshold.get('threshold')}: {at_threshold.get('f1')} "
        f"(precision: {at_threshold.get('precision')}, recall: {at_threshold.get('recall')})",
        f"- Memory candidates labeled: {auc.get('candidate_total')} "
        f"(TP: {auc.get('positive_candidates')}, FP: {auc.get('negative_candidates')})",
        "",
    ]
    breakdowns = auc.get("breakdowns") or {}
    lines.extend(["## Candidate Breakdowns", ""])
    for title, key in [
        ("Source stage", "by_source_stage"),
        ("Comment kind", "by_comment_kind"),
        ("Status", "by_status"),
    ]:
        rows = breakdowns.get(key) or {}
        lines.extend([f"### {title}", "", "| Bucket | Total | Pos | Neg | ROC-AUC | F1 |", "|---|---:|---:|---:|---:|---:|"])
        if not rows:
            lines.append("| none | 0 | 0 | 0 |  |  |")
        else:
            for bucket, metrics in rows.items():
                threshold_metrics = metrics.get("at_threshold") or {}
                lines.append(
                    f"| `{bucket}` | {metrics.get('candidate_total')} | {metrics.get('positive_candidates')} | "
                    f"{metrics.get('negative_candidates')} | {metrics.get('roc_auc')} | {threshold_metrics.get('f1')} |"
                )
        lines.append("")
    lines.extend(["## Missed Gold", ""])
    missed = payload["comparison"]["missed_gold"][:30]
    if not missed:
        lines.append("No missed gold comments.")
    else:
        lines.extend(["| Kind | Criterion | Alert | Comment |", "|---|---|---|---|"])
        for row in missed:
            text = str(row.get("comment_text") or "").replace("\n", " ")[:180]
            lines.append(f"| {row.get('comment_kind')} | `{row.get('criterion_code')}` | {row.get('alert_color')} | {text} |")
    lines.extend(["", "## Extra Predicted", ""])
    extra = payload["comparison"]["extra_predicted"][:30]
    if not extra:
        lines.append("No extra predicted comments.")
    else:
        lines.extend(["| Status | Criterion | Anchor | Comment |", "|---|---|---:|---|"])
        for row in extra:
            text = str(row.get("comment_text") or "").replace("\n", " ")[:180]
            lines.append(f"| {row.get('status')} | `{row.get('criterion_code')}` | {row.get('anchor_position_idx')} | {text} |")
    lines.append("")
    if payload.get("quality_summary"):
        lines.extend(render_quality_summary_markdown(payload["quality_summary"]))
    return "\n".join(lines)


def evaluate_first_iteration(
    *,
    reviewed_notebook: Path,
    restored_notebook: Path,
    project: str,
    criteria_map: str,
    out_dir: Path,
    reviewer_insertions_path: Path | None = None,
    include_memory_candidates: bool = True,
    memory_candidate_min_score: float = 0.35,
    max_memory_candidates: int = 30,
    memory_actionable_min_score: float | None = None,
    max_actionable_memory_candidates: int = 20,
    enable_llm_judge: bool = False,
    enable_llm_generator: bool = False,
    enable_llm_classifier: bool = False,
    enable_llm_anchor_validator: bool = False,
    llm_max_candidates: int = 30,
    decision_threshold: float = 0.5,
    candidate_score_field: str | None = None,
    enable_quality_judge: bool = False,
    quality_judge_model: str | None = None,
    quality_judge_max_items: int = 100,
    quality_judge_min_source_support: str = "medium",
    quality_score_threshold: float = 0.7,
    quality_llm_service: LLMService | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    gold = extract_gold_first_review_comments(
        restored_notebook=restored_notebook,
        reviewed_notebook=reviewed_notebook,
        project=project,
    )
    predicted, reviewed_obj, all_memory_candidates, project_memory, artifacts = run_offline_autoreview(
        restored_notebook=restored_notebook,
        criteria_map=criteria_map,
        project=project,
        reviewer_insertions_path=reviewer_insertions_path,
        exclude_reviewed_notebook=reviewed_notebook.name,
        include_memory_candidates=include_memory_candidates,
        memory_candidate_min_score=memory_candidate_min_score,
        max_memory_candidates=max_memory_candidates,
        memory_actionable_min_score=memory_actionable_min_score,
        max_actionable_memory_candidates=max_actionable_memory_candidates,
        enable_llm_judge=enable_llm_judge,
        enable_llm_generator=enable_llm_generator,
        enable_llm_classifier=enable_llm_classifier,
        enable_llm_anchor_validator=enable_llm_anchor_validator,
        llm_max_candidates=llm_max_candidates,
    )
    comparison = compare_predictions(predicted, gold)
    labeled_candidates, candidate_auc_summary = label_memory_candidates_for_auc(
        all_memory_candidates,
        gold,
        decision_threshold=decision_threshold,
        score_field=candidate_score_field,
        project=project,
    )
    quality_summary: dict[str, Any] | None = None
    if enable_quality_judge:
        criteria = load_criteria_map(criteria_map)
        labeled_candidates = evaluate_comment_rows_quality(
            labeled_candidates,
            artifacts=artifacts,
            criteria=criteria,
            gold=gold,
            project_memory=project_memory,
            llm_service=quality_llm_service,
            model=quality_judge_model,
            max_items=quality_judge_max_items,
            decision_threshold=decision_threshold,
            quality_score_threshold=quality_score_threshold,
            min_source_support=quality_judge_min_source_support,
        )
        quality_summary = aggregate_quality_evals(labeled_candidates)
    predicted_reviewed = out_dir / "predicted_reviewed.ipynb"
    nbformat.write(reviewed_obj, predicted_reviewed)
    _write_jsonl(gold, out_dir / "gold_first_review_comments.jsonl")
    _write_jsonl(predicted, out_dir / "predicted_insertions.jsonl")
    _write_jsonl(labeled_candidates, out_dir / "all_memory_candidates_labeled.jsonl")
    payload = {
        "reviewed_notebook": str(reviewed_notebook),
        "restored_notebook": str(restored_notebook),
        "criteria_map": criteria_map,
        "project": project,
        "decision_threshold": decision_threshold,
        "candidate_score_field": candidate_score_field,
        "artifacts": {
            "gold_jsonl": str(out_dir / "gold_first_review_comments.jsonl"),
            "predicted_jsonl": str(out_dir / "predicted_insertions.jsonl"),
            "all_memory_candidates_labeled_jsonl": str(out_dir / "all_memory_candidates_labeled.jsonl"),
            "predicted_reviewed_notebook": str(predicted_reviewed),
            "comparison_json": str(out_dir / "comparison.json"),
            "report_md": str(out_dir / "report.md"),
        },
        "comparison": comparison,
        "candidate_auc": candidate_auc_summary,
    }
    if quality_summary is not None:
        payload["quality_summary"] = quality_summary
    (out_dir / "comparison.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload
