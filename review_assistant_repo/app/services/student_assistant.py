"""RAG-style student assistant over project artifacts and optional course knowledge base."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.llm.service import get_llm_service
from app.models import Artifact, Project
from app.parsers.notebook import infer_student_question_intent
from app.retrieval.bm25_util import bm25_scores
from app.retrieval.local_examples import _iter_jsonl_rows, _project_training_jsonl_paths
from app.utils.config_loader import load_criteria_map

SourceKind = Literal[
    "project_doc",
    "course_base",
    "notebook_memory",
    "criteria",
    "senior_solution",
    "reviewer_style",
    "accepted_pattern",
    "external_web",
]


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    text: str
    source_kind: SourceKind
    label: str
    artifact_id: str | None = None
    url: str | None = None
    citation: str | None = None
    metadata: dict[str, Any] | None = None


def split_text_blocks(text: str, max_len: int = 1200) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    parts: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for para in text.split("\n\n"):
        p = para.strip()
        if not p:
            continue
        add_len = len(p) if not cur else len(p) + 2
        if cur_len + add_len > max_len and cur:
            parts.append("\n\n".join(cur))
            cur = [p]
            cur_len = len(p)
        else:
            cur.append(p)
            cur_len += add_len
    if cur:
        parts.append("\n\n".join(cur))
    final: list[str] = []
    for piece in parts:
        if len(piece) <= max_len:
            final.append(piece)
        else:
            for i in range(0, len(piece), max_len):
                final.append(piece[i : i + max_len])
    return final


def rank_knowledge_chunks(
    query: str,
    chunks: list[KnowledgeChunk],
    *,
    project_boost: float = 1.35,
) -> list[tuple[KnowledgeChunk, float]]:
    if not chunks:
        return []
    corpus = [c.text for c in chunks]
    scores = bm25_scores(query, corpus)
    out: list[tuple[KnowledgeChunk, float]] = []
    for chunk, sc in zip(chunks, scores, strict=True):
        boosted = sc * (project_boost if chunk.source_kind == "project_doc" else 1.0)
        out.append((chunk, boosted))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def _load_course_kb_chunks(kb_dir: Path) -> list[KnowledgeChunk]:
    if not kb_dir.is_dir():
        return []
    out: list[KnowledgeChunk] = []
    for path in sorted(kb_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".txt", ".markdown"}:
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            rel = path.relative_to(kb_dir)
        except ValueError:
            rel = path
        label_base = f"course:{rel.as_posix()}"
        for idx, block in enumerate(split_text_blocks(raw)):
            cid = f"course:{rel.as_posix()}:{idx}"
            out.append(
                KnowledgeChunk(
                    chunk_id=cid,
                    text=block,
                    source_kind="course_base",
                    label=label_base,
                    artifact_id=None,
                )
            )
    return out


def _load_project_chunks(db: Session, project_id: str) -> list[KnowledgeChunk]:
    project = db.get(Project, project_id)
    if not project:
        return []
    out: list[KnowledgeChunk] = []
    if project.review_markdown and project.review_markdown.strip():
        for idx, block in enumerate(split_text_blocks(project.review_markdown, max_len=1600)):
            out.append(
                KnowledgeChunk(
                    chunk_id=f"review_markdown:{idx}",
                    text=block,
                    source_kind="project_doc",
                    label="project:review_markdown",
                    artifact_id=None,
                )
            )
    meta = project.metadata_json or {}
    memory = meta.get("notebook_memory")
    if isinstance(memory, dict):
        for key, values in memory.items():
            if not isinstance(values, list):
                continue
            for idx, item in enumerate(values[:30]):
                text = json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else str(item)
                if not text.strip():
                    continue
                out.append(
                    KnowledgeChunk(
                        chunk_id=f"notebook_memory:{key}:{idx}",
                        text=text,
                        source_kind="notebook_memory",
                        label=f"notebook_memory:{key}",
                        metadata={"memory_key": key},
                    )
                )
    try:
        criteria = load_criteria_map(project.criteria_map_code)
    except Exception:
        criteria = []
    for item in criteria:
        text = "\n".join(
            str(x)
            for x in [
                item.get("code"),
                item.get("title"),
                item.get("description"),
                item.get("severity"),
                item.get("category"),
            ]
            if x
        )
        if text.strip():
            out.append(
                KnowledgeChunk(
                    chunk_id=f"criteria:{item.get('code')}",
                    text=text,
                    source_kind="criteria",
                    label=f"criteria:{item.get('code')}",
                    metadata={"criterion_code": item.get("code")},
                )
            )
    rows = db.query(Artifact).filter(Artifact.project_id == project_id).all()
    for row in rows:
        text = (row.normalized_text or row.raw_text or "").strip()
        if not text:
            continue
        section = (row.section_name or "").strip()
        atype = (row.artifact_type or "artifact").strip()
        label = f"project:{atype}" + (f":{section}" if section else "")
        for idx, block in enumerate(split_text_blocks(text)):
            out.append(
                KnowledgeChunk(
                    chunk_id=f"{row.id}:{idx}",
                    text=block,
                    source_kind="project_doc",
                    label=label,
                    artifact_id=row.id,
                )
            )
    return out


def _source_kind_from_lane(row: dict[str, Any], fallback: SourceKind) -> SourceKind:
    lane = str(row.get("lane") or row.get("source_kind") or "").strip()
    if lane in {"senior_solution", "reviewer_reference", "rubric_truth"}:
        return "senior_solution"
    if lane in {"accepted_patterns", "accepted_pattern"}:
        return "accepted_pattern"
    if lane in {"reviewer_style", "negative/error_patterns", "student_question_dialogues", "project_training"}:
        return "reviewer_style"
    return fallback


def _load_reviewer_style_chunks(settings: Settings) -> list[KnowledgeChunk]:
    rows: list[dict[str, Any]] = []
    if settings.enable_project_review_training and settings.project_review_training_path:
        for fp in _project_training_jsonl_paths(Path(settings.project_review_training_path)):
            rows.extend(_iter_jsonl_rows(fp))
    if settings.enable_reviewer_reference_examples and settings.reviewer_reference_examples_path:
        path = Path(settings.reviewer_reference_examples_path)
        if path.is_file():
            rows.extend(_iter_jsonl_rows(path))

    chunks: list[KnowledgeChunk] = []
    for idx, row in enumerate(rows[:2000]):
        text = str(row.get("text") or row.get("review_text") or "").strip()
        if not text:
            continue
        source_kind = _source_kind_from_lane(row, "reviewer_style")
        label = f"{source_kind}:{row.get('source_project') or 'any'}:{row.get('criterion_code') or 'general'}"
        context = str(row.get("student_context") or "").strip()
        if context:
            text = f"{text}\n\n[student_context]\n{context[:1200]}"
        chunks.append(
            KnowledgeChunk(
                chunk_id=f"reviewer_style:{idx}:{row.get('example_id') or ''}",
                text=text[:3000],
                source_kind=source_kind,
                label=label,
                metadata={
                    "author_role": row.get("author_role"),
                    "lane": row.get("lane"),
                    "criterion_code": row.get("criterion_code"),
                    "source_project": row.get("source_project"),
                    "source_notebook": row.get("source_notebook"),
                },
            )
        )
    return chunks


def _load_external_knowledge_chunks(settings: Settings) -> list[KnowledgeChunk]:
    if not settings.enable_external_knowledge or not settings.external_knowledge_path:
        return []
    path = Path(settings.external_knowledge_path)
    if not path.is_file():
        return []
    chunks: list[KnowledgeChunk] = []
    for idx, row in enumerate(_iter_jsonl_rows(path)[:500]):
        text = str(row.get("text") or row.get("summary") or "").strip()
        url = str(row.get("url") or "").strip() or None
        if not text:
            continue
        chunks.append(
            KnowledgeChunk(
                chunk_id=f"external:{idx}",
                text=text[:2000],
                source_kind="external_web",
                label=str(row.get("title") or row.get("cache_key") or "external_web"),
                url=url,
                citation=str(row.get("citation") or url or ""),
                metadata={"timestamp": row.get("timestamp"), "cache_key": row.get("cache_key")},
            )
        )
    return chunks


def load_all_chunks(db: Session, project_id: str, settings: Settings) -> list[KnowledgeChunk]:
    project_chunks = _load_project_chunks(db, project_id)
    kb_path = Path(settings.student_course_kb_dir)
    course_chunks = _load_course_kb_chunks(kb_path)
    return project_chunks + course_chunks + _load_reviewer_style_chunks(settings) + _load_external_knowledge_chunks(settings)


def _excerpt(text: str, limit: int = 450) -> str:
    t = re.sub(r"\s+", " ", text.strip())
    if len(t) <= limit:
        return t
    return t[: limit - 1] + "…"


def _format_extractive_answer(
    ranked: list[tuple[KnowledgeChunk, float]],
    *,
    max_sources: int,
) -> tuple[str, list[dict], bool]:
    if not ranked:
        return (
            "Пока нет проиндексированных материалов: завершите проверку проекта или добавьте файлы "
            "в каталог базы знаний курса.",
            [],
            True,
        )
    best = ranked[0][1]
    needs_teacher = best <= 0.0

    top = ranked[:max_sources]
    lines = [
        "Ниже — выдержки из доступных материалов (ТЗ, артефакты проекта и база курса). "
        "Сверяйте формулировки с первоисточником."
    ]
    sources_out: list[dict] = []
    for i, (ch, sc) in enumerate(top, start=1):
        ex = _excerpt(ch.text)
        kind_ru = {
            "project_doc": "проект",
            "course_base": "курс",
            "notebook_memory": "память тетрадки",
            "criteria": "критерий",
            "senior_solution": "старшее ревью",
            "reviewer_style": "пример ревью",
            "accepted_pattern": "зачтенный пример",
            "external_web": "внешний источник",
        }.get(ch.source_kind, ch.source_kind)
        lines.append(f"\n[{i}] ({kind_ru}, {ch.label})\n{ex}")
        sources_out.append(
            {
                "label": ch.label,
                "source_kind": ch.source_kind,
                "excerpt": ex,
                "score": float(sc),
                "artifact_id": ch.artifact_id,
                "url": ch.url,
                "citation": ch.citation,
            }
        )
    if needs_teacher:
        lines.append(
            "\nПо запросу не нашлось уверенных совпадений в материалах — лучше уточните у преподавателя."
        )
    return "\n".join(lines), sources_out, needs_teacher


def _build_llm_context(ranked: list[tuple[KnowledgeChunk, float]], k: int) -> str:
    blocks: list[str] = []
    for i, (ch, _sc) in enumerate(ranked[:k], start=1):
        blocks.append(f"[{i}] ({ch.source_kind}; {ch.label})\n{ch.text[:3500]}")
    return "\n\n---\n\n".join(blocks)


def _context_summary(ranked: list[tuple[KnowledgeChunk, float]]) -> str:
    kinds = []
    for ch, _sc in ranked[:5]:
        if ch.source_kind not in kinds:
            kinds.append(ch.source_kind)
    return "Использованы источники: " + ", ".join(kinds) if kinds else "Нет уверенных источников."


def _confidence(best_score: float, ranked: list[tuple[KnowledgeChunk, float]]) -> float:
    if not ranked or best_score <= 0:
        return 0.0
    return max(0.05, min(0.95, best_score / (best_score + 3.0)))


def answer_student_question(
    db: Session,
    project_id: str,
    question: str,
    settings: Settings | None = None,
    extra_chunks: list[KnowledgeChunk] | None = None,
) -> dict:
    settings = settings or get_settings()
    chunks = load_all_chunks(db, project_id, settings) + list(extra_chunks or [])
    ranked = rank_knowledge_chunks(
        question,
        chunks,
        project_boost=settings.student_assistant_project_boost,
    )
    top_k = max(1, int(settings.student_assistant_top_k))
    ranked = ranked[:top_k]

    n_sources = max(1, int(settings.student_assistant_answer_sources))
    best = ranked[0][1] if ranked else 0.0
    intent = infer_student_question_intent(question)
    context_summary = _context_summary(ranked)
    confidence = _confidence(best, ranked)
    needs_teacher_reason = "no_relevant_sources" if best <= 0.0 else None

    use_llm = bool(settings.student_assistant_use_llm)
    llm = get_llm_service()
    if use_llm and llm.is_available and chunks:
        prompt_path = Path(__file__).resolve().parents[1] / "llm" / "prompts" / "student_assistant.txt"
        template = prompt_path.read_text(encoding="utf-8")
        context = _build_llm_context(ranked, n_sources)
        user_content = template.format(context=context, question=question.strip())
        result = llm.chat([{"role": "user", "content": user_content}], temperature=0.25)
        if result.ok and result.text:
            sources_meta: list[dict] = []
            for ch, sc in ranked[:n_sources]:
                sources_meta.append(
                    {
                        "label": ch.label,
                        "source_kind": ch.source_kind,
                        "excerpt": _excerpt(ch.text),
                        "score": float(sc),
                        "artifact_id": ch.artifact_id,
                        "url": ch.url,
                        "citation": ch.citation,
                    }
                )
            return {
                "answer": result.text.strip(),
                "sources": sources_meta,
                "needs_teacher": best <= 0.0,
                "mode": "llm",
                "intent": intent,
                "confidence": confidence,
                "context_summary": context_summary,
                "used_memory": any(ch.source_kind == "notebook_memory" for ch, _ in ranked[:n_sources]),
                "needs_teacher_reason": needs_teacher_reason,
            }

    text, sources, needs = _format_extractive_answer(ranked, max_sources=n_sources)
    return {
        "answer": text,
        "sources": sources,
        "needs_teacher": needs,
        "mode": "extractive",
        "intent": intent,
        "confidence": confidence,
        "context_summary": context_summary,
        "used_memory": any(s.get("source_kind") == "notebook_memory" for s in sources),
        "needs_teacher_reason": needs_teacher_reason,
    }


def collect_student_questions_from_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for artifact in artifacts:
        meta = artifact.get("metadata_json") or artifact.get("metadata") or {}
        if not meta.get("is_student_question"):
            continue
        question = str(meta.get("student_question") or "").strip()
        if not question:
            continue
        questions.append(
            {
                "question": question,
                "question_cell_idx": meta.get("question_cell_idx", artifact.get("position_idx")),
                "intent": meta.get("student_question_intent") or infer_student_question_intent(question),
                "topic_tags": meta.get("topic_tags") or [],
                "context_window": meta.get("question_context_window") or [],
                "artifact_id": artifact.get("id"),
            }
        )
    return questions


def _question_extra_chunks(question_row: dict[str, Any], project_memory: dict[str, Any] | None) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    ctx = question_row.get("context_window") or []
    for idx, item in enumerate(ctx[:5]):
        text = str(item.get("text") or "").strip()
        if text:
            chunks.append(
                KnowledgeChunk(
                    chunk_id=f"question_context:{question_row.get('question_cell_idx')}:{idx}",
                    text=text,
                    source_kind="project_doc",
                    label=f"project:question_context:{item.get('position_idx')}",
                    metadata={"question_cell_idx": question_row.get("question_cell_idx")},
                )
            )
    if isinstance(project_memory, dict):
        for key in ("missing_requirements", "project_steps", "key_findings", "risk_flags"):
            values = project_memory.get(key)
            if not isinstance(values, list):
                continue
            for idx, item in enumerate(values[:5]):
                text = json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else str(item)
                chunks.append(
                    KnowledgeChunk(
                        chunk_id=f"question_memory:{key}:{idx}",
                        text=text,
                        source_kind="notebook_memory",
                        label=f"notebook_memory:{key}",
                    )
                )
    return chunks


def answer_student_questions_from_artifacts(
    db: Session,
    project_id: str,
    artifacts: list[dict[str, Any]],
    *,
    project_memory: dict[str, Any] | None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    answers: list[dict[str, Any]] = []
    for row in collect_student_questions_from_artifacts(artifacts):
        answer = answer_student_question(
            db,
            project_id,
            row["question"],
            settings=settings,
            extra_chunks=_question_extra_chunks(row, project_memory),
        )
        answers.append({**row, **answer})
    return answers
