from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy.orm import Session

from app.analyzers.visual_summary import build_visual_debug_payload
from app.models import Artifact, Project, ProjectFile
from app.schemas import (
    ArtifactDTO,
    PreviewPairDTO,
    ProjectFileDTO,
    RegionDTO,
    VisualPreviewDTO,
    VisualSummaryDTO,
)

REGION_ARTIFACT_TYPES = {
    "pdf_region",
    "pdf_image_region",
    "datalens_region",
    "datalens_image_region",
}
PREVIEW_BASE_KINDS = {"pdf_page_image", "capture_screenshot"}
PREVIEW_OVERLAY_KINDS = {"pdf_page_overlay", "capture_overlay"}


def file_to_dto(row: ProjectFile) -> ProjectFileDTO:
    return ProjectFileDTO(
        id=row.id,
        kind=row.kind,
        filename=Path(row.storage_path).name,
        mime_type=row.mime_type,
        page_no=row.page_no,
        metadata_json=row.metadata_json or {},
    )


def artifact_to_dto(row: Artifact) -> ArtifactDTO:
    return ArtifactDTO(
        id=row.id,
        artifact_type=row.artifact_type,
        position_idx=row.position_idx,
        section_name=row.section_name,
        raw_text=row.raw_text,
        normalized_text=row.normalized_text,
        metadata_json=row.metadata_json or {},
    )


def artifact_to_region_dto(row: Artifact) -> RegionDTO:
    meta = row.metadata_json or {}
    return RegionDTO(
        id=row.id,
        region_id=meta.get("region_id"),
        artifact_type=row.artifact_type,
        position_idx=row.position_idx,
        page_no=meta.get("page_no") if meta.get("page_no") is not None else meta.get("capture_index"),
        region_kind=meta.get("region_kind"),
        tags=list(meta.get("tags") or []),
        bbox=meta.get("bbox"),
        bbox_normalized=meta.get("bbox_normalized"),
        source=meta.get("source"),
        image_path=meta.get("image_path") or meta.get("path"),
        normalized_text=row.normalized_text,
        metadata_json=meta,
    )


class ProjectExplorerService:
    def __init__(self, db: Session):
        self.db = db

    def get_project(self, project_id: str) -> Project:
        project = self.db.get(Project, project_id)
        if not project:
            raise ValueError("Project not found")
        return project

    def list_artifacts(
        self,
        project_id: str,
        artifact_type: str | None = None,
        region_kind: str | None = None,
        page_no: int | None = None,
        tag: str | None = None,
        section_name: str | None = None,
        source_type: str | None = None,
        limit: int = 500,
    ) -> list[ArtifactDTO]:
        project = self.get_project(project_id)
        rows = (
            self.db.query(Artifact)
            .filter(Artifact.project_id == project.id)
            .order_by(Artifact.position_idx.asc().nullslast(), Artifact.artifact_type.asc())
            .all()
        )
        result = []
        for row in rows:
            meta = row.metadata_json or {}
            if artifact_type and row.artifact_type != artifact_type:
                continue
            if region_kind and meta.get("region_kind") != region_kind:
                continue
            row_page_no = meta.get("page_no") if meta.get("page_no") is not None else meta.get("capture_index")
            if page_no is not None and row_page_no != page_no:
                continue
            if tag and tag not in (meta.get("tags") or []):
                continue
            if section_name and (row.section_name or "") != section_name:
                continue
            if source_type and (meta.get("source_type") or "") != source_type:
                continue
            result.append(artifact_to_dto(row))
            if len(result) >= limit:
                break
        return result

    def get_artifact(self, project_id: str, artifact_id: str) -> ArtifactDTO:
        project = self.get_project(project_id)
        row = self.db.get(Artifact, artifact_id)
        if not row or row.project_id != project.id:
            raise ValueError("Artifact not found")
        return artifact_to_dto(row)

    def list_regions(
        self,
        project_id: str,
        region_kind: str | None = None,
        page_no: int | None = None,
        source_type: str | None = None,
        limit: int = 500,
    ) -> list[RegionDTO]:
        project = self.get_project(project_id)
        rows = (
            self.db.query(Artifact)
            .filter(Artifact.project_id == project.id)
            .filter(Artifact.artifact_type.in_(sorted(REGION_ARTIFACT_TYPES)))
            .order_by(Artifact.position_idx.asc().nullslast(), Artifact.artifact_type.asc())
            .all()
        )
        result = []
        for row in rows:
            meta = row.metadata_json or {}
            this_region_kind = meta.get("region_kind")
            this_page_no = meta.get("page_no") if meta.get("page_no") is not None else meta.get("capture_index")
            this_source_type = "image" if "image" in row.artifact_type else "text"
            if region_kind and this_region_kind != region_kind:
                continue
            if page_no is not None and this_page_no != page_no:
                continue
            if source_type and this_source_type != source_type:
                continue
            result.append(artifact_to_region_dto(row))
            if len(result) >= limit:
                break
        return result

    def build_visual_summary(self, project_id: str) -> VisualSummaryDTO:
        project = self.get_project(project_id)
        artifact_rows = self.db.query(Artifact).filter(Artifact.project_id == project.id).all()
        file_rows = self.db.query(ProjectFile).filter(ProjectFile.project_id == project.id).all()

        artifact_counts = Counter(row.artifact_type for row in artifact_rows)
        file_counts = Counter(row.kind for row in file_rows)
        region_counts: Counter[str] = Counter()
        regions_by_page = defaultdict(list)

        for row in artifact_rows:
            if row.artifact_type not in REGION_ARTIFACT_TYPES:
                continue
            meta = row.metadata_json or {}
            region_kind = meta.get("region_kind") or "unknown"
            page_no = meta.get("page_no") if meta.get("page_no") is not None else meta.get("capture_index")
            region_counts[region_kind] += 1
            regions_by_page[page_no].append(row)

        base_files = {row.page_no: row for row in file_rows if row.kind in PREVIEW_BASE_KINDS}
        overlay_files = {row.page_no: row for row in file_rows if row.kind in PREVIEW_OVERLAY_KINDS}
        preview_page_keys = sorted(set(base_files) | set(overlay_files) | set(regions_by_page), key=lambda x: (-1 if x is None else x))

        preview_pairs = []
        for page_no in preview_page_keys:
            page_regions = regions_by_page.get(page_no, [])
            region_kind_counts = Counter((row.metadata_json or {}).get("region_kind") or "unknown" for row in page_regions)
            base_file = base_files.get(page_no)
            overlay_file = overlay_files.get(page_no)
            source_type = "pdf" if base_file and base_file.kind == "pdf_page_image" else "datalens"
            if not base_file and overlay_file and overlay_file.kind == "pdf_page_overlay":
                source_type = "pdf"
            preview_pairs.append(
                PreviewPairDTO(
                    page_no=page_no,
                    source_type=source_type,
                    base_file=file_to_dto(base_file) if base_file else None,
                    overlay_file=file_to_dto(overlay_file) if overlay_file else None,
                    region_count=len(page_regions),
                    region_kinds=dict(sorted(region_kind_counts.items())),
                )
            )

        debug = build_visual_debug_payload(artifact_rows, file_rows)

        return VisualSummaryDTO(
            project_id=project.id,
            artifact_counts=dict(sorted(artifact_counts.items())),
            file_counts=dict(sorted(file_counts.items())),
            region_counts=dict(sorted(region_counts.items())),
            preview_pairs=preview_pairs,
            image_region_count=debug["image_region_count"],
            text_region_count=debug["text_region_count"],
            low_text_extraction_pages=debug["low_text_extraction_pages"],
            low_region_confidence_pages=debug["low_region_confidence_pages"],
        )

    def build_visual_preview(self, project_id: str, page_no: int | None = None) -> VisualPreviewDTO:
        project = self.get_project(project_id)
        file_rows = self.db.query(ProjectFile).filter(ProjectFile.project_id == project.id).all()
        base_files = [f for f in file_rows if f.kind in PREVIEW_BASE_KINDS and (page_no is None or f.page_no == page_no)]
        overlay_files = [f for f in file_rows if f.kind in PREVIEW_OVERLAY_KINDS and (page_no is None or f.page_no == page_no)]
        base = base_files[0] if base_files else None
        overlay = None
        if base:
            overlay = next((o for o in overlay_files if o.page_no == base.page_no), overlay_files[0] if overlay_files else None)
        elif overlay_files:
            overlay = overlay_files[0]
        key_page = base.page_no if base else (overlay.page_no if overlay else page_no)

        rows = (
            self.db.query(Artifact)
            .filter(Artifact.project_id == project.id)
            .filter(Artifact.artifact_type.in_(sorted(REGION_ARTIFACT_TYPES)))
            .order_by(Artifact.position_idx.asc().nullslast())
            .all()
        )
        regions_out: list[RegionDTO] = []
        for row in rows:
            meta = row.metadata_json or {}
            pno = meta.get("page_no") if meta.get("page_no") is not None else meta.get("capture_index")
            if key_page is not None and pno != key_page:
                continue
            regions_out.append(artifact_to_region_dto(row))

        meta_summary = {
            "page_no": key_page,
            "region_count": len(regions_out),
            "kinds": dict(Counter((r.region_kind or "unknown") for r in regions_out)),
        }
        return VisualPreviewDTO(
            page_no=key_page,
            base_file=file_to_dto(base) if base else None,
            overlay_file=file_to_dto(overlay) if overlay else None,
            regions=regions_out,
            metadata_summary=meta_summary,
        )
