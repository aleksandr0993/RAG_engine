from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Project
from app.services.matching_service import MatchingService

router = APIRouter(tags=["assignments"])


class ProjectAssignmentDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    reviewer_id: str
    assigned_at: datetime
    priority: int
    status: str
    metadata_json: dict = Field(default_factory=dict)


class AutoAssignBody(BaseModel):
    reviewer_ids: list[str]
    criteria_map_code: str | None = None
    expertise: dict[str, list[str]] | None = Field(
        default=None,
        description="Optional map reviewer_id -> list of criteria_map_code for specialization",
    )


class ManualAssignBody(BaseModel):
    reviewer_id: str
    priority: int = 0


@router.post("/admin/projects/{project_id}/assignments/auto", response_model=ProjectAssignmentDTO)
def auto_assign_reviewer(
    project_id: str,
    body: AutoAssignBody,
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    svc = MatchingService()
    rid = svc.suggest_reviewer(
        db,
        body.reviewer_ids,
        criteria_map_code=body.criteria_map_code or project.criteria_map_code,
        expertise_by_reviewer=body.expertise,
    )
    if not rid:
        raise HTTPException(status_code=400, detail="reviewer_ids is empty")
    row = svc.assign(db, project_id=project_id, reviewer_id=rid, priority=0)
    return row


@router.post("/admin/projects/{project_id}/assignments", response_model=ProjectAssignmentDTO)
def manual_assign(
    project_id: str,
    body: ManualAssignBody,
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    svc = MatchingService()
    row = svc.assign(
        db,
        project_id=project_id,
        reviewer_id=body.reviewer_id,
        priority=body.priority,
    )
    return row


@router.get("/admin/projects/{project_id}/assignments", response_model=list[ProjectAssignmentDTO])
def list_assignments(project_id: str, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    svc = MatchingService()
    return svc.list_for_project(db, project_id)
