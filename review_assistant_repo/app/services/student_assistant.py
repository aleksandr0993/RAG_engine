"""RAG-style student assistant over project artifacts and optional course knowledge base."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.llm.service import get_llm_service
from app.models import Artifact, Project
from app.retrieval.bm25_util import bm25_scores

SourceKind = Literal["project_doc", "course_base"]


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    text: str
    source_kind: SourceKind
    label: str
    artifact_id: str | None = None


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


def load_all_chunks(db: Session, project_id: str, settings: Settings) -> list[KnowledgeChunk]:
    project_chunks = _load_project_chunks(db, project_id)
    kb_path = Path(settings.student_course_kb_dir)
    course_chunks = _load_course_kb_chunks(kb_path)
    return project_chunks + course_chunks


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
        kind_ru = "проект" if ch.source_kind == "project_doc" else "курс"
        lines.append(f"\n[{i}] ({kind_ru}, {ch.label})\n{ex}")
        sources_out.append(
            {
                "label": ch.label,
                "source_kind": ch.source_kind,
                "excerpt": ex,
                "score": float(sc),
                "artifact_id": ch.artifact_id,
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


def answer_student_question(
    db: Session,
    project_id: str,
    question: str,
    settings: Settings | None = None,
) -> dict:
    settings = settings or get_settings()
    chunks = load_all_chunks(db, project_id, settings)
    ranked = rank_knowledge_chunks(
        question,
        chunks,
        project_boost=settings.student_assistant_project_boost,
    )
    top_k = max(1, int(settings.student_assistant_top_k))
    ranked = ranked[:top_k]

    n_sources = max(1, int(settings.student_assistant_answer_sources))

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
                    }
                )
            best = ranked[0][1] if ranked else 0.0
            return {
                "answer": result.text.strip(),
                "sources": sources_meta,
                "needs_teacher": best <= 0.0,
                "mode": "llm",
            }

    text, sources, needs = _format_extractive_answer(ranked, max_sources=n_sources)
    return {"answer": text, "sources": sources, "needs_teacher": needs, "mode": "extractive"}
