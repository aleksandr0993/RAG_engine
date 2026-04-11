from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.schemas import (
    StudentAssistantChatRequest,
    StudentAssistantChatResponse,
    StudentAssistantSourceDTO,
)
from app.services.student_assistant import answer_student_question

router = APIRouter(tags=["student_assistant"])

_UI_PATH = Path(__file__).resolve().parents[1] / "static" / "student_assistant.html"


@router.get("/projects/{project_id}/assistant", response_class=HTMLResponse)
def student_assistant_ui(project_id: str):
    settings = get_settings()
    if not settings.student_assistant_enabled:
        raise HTTPException(status_code=404, detail="Student assistant disabled")
    if not _UI_PATH.is_file():
        raise HTTPException(status_code=500, detail="UI template missing")
    html = _UI_PATH.read_text(encoding="utf-8")
    html = html.replace("__PROJECT_ID__", project_id)
    return HTMLResponse(content=html)


@router.post("/projects/{project_id}/assistant/chat", response_model=StudentAssistantChatResponse)
def student_assistant_chat(
    project_id: str,
    body: StudentAssistantChatRequest,
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if not settings.student_assistant_enabled:
        raise HTTPException(status_code=404, detail="Student assistant disabled")

    from app.models import Project

    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")

    raw = answer_student_question(db, project_id, body.message, settings=settings)
    sources = [StudentAssistantSourceDTO(**s) for s in raw["sources"]]
    return StudentAssistantChatResponse(
        answer=raw["answer"],
        sources=sources,
        needs_teacher=raw["needs_teacher"],
        mode=raw["mode"],
    )
