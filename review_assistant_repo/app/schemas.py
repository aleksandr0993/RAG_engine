from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    project_id: str
    status: str


class ReviewResponse(BaseModel):
    project_id: str
    status: str
    final_verdict: str | None = None


class AsyncReviewAccepted(BaseModel):
    """202 Accepted — review runs in a FastAPI BackgroundTasks worker."""

    project_id: str
    job_id: str
    status: Literal["accepted"] = "accepted"
    message: str = (
        "Review started in background. Poll GET /api/v1/projects/{id}/review/jobs/{job_id}, "
        "GET /api/v1/projects/{id}, or WebSocket /api/v1/ws/projects/{id}/status."
    )


class ReviewJobDTO(BaseModel):
    """Persistent review job row (async path)."""

    id: str
    project_id: str
    status: Literal["queued", "running", "done", "failed", "timeout"]
    error_message: str | None = None
    detail_json: dict[str, Any] = Field(default_factory=dict)


class ProjectResponse(BaseModel):
    id: str
    source_type: str
    original_filename: str | None = None
    source_url: str | None = None
    status: str
    style_profile_code: str
    criteria_map_code: str
    final_verdict: str | None = None
    review_markdown: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ProjectFileDTO(BaseModel):
    id: str
    kind: str
    filename: str
    mime_type: str | None = None
    page_no: int | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ArtifactDTO(BaseModel):
    id: str
    artifact_type: str
    position_idx: int | None = None
    section_name: str | None = None
    raw_text: str | None = None
    normalized_text: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class RegionDTO(BaseModel):
    id: str
    region_id: str | None = None
    artifact_type: str
    position_idx: int | None = None
    page_no: int | None = None
    region_kind: str | None = None
    tags: list[str] = Field(default_factory=list)
    bbox: list[float] | None = None
    bbox_normalized: list[float] | None = None
    source: str | None = None
    image_path: str | None = None
    normalized_text: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class PreviewPairDTO(BaseModel):
    page_no: int | None = None
    source_type: str
    base_file: ProjectFileDTO | None = None
    overlay_file: ProjectFileDTO | None = None
    region_count: int = 0
    region_kinds: dict[str, int] = Field(default_factory=dict)


class VisualSummaryDTO(BaseModel):
    project_id: str
    artifact_counts: dict[str, int] = Field(default_factory=dict)
    file_counts: dict[str, int] = Field(default_factory=dict)
    region_counts: dict[str, int] = Field(default_factory=dict)
    preview_pairs: list[PreviewPairDTO] = Field(default_factory=list)
    image_region_count: int = 0
    text_region_count: int = 0
    low_text_extraction_pages: list[int] = Field(default_factory=list)
    low_region_confidence_pages: list[int] = Field(default_factory=list)


class VisualPreviewDTO(BaseModel):
    page_no: int | None = None
    base_file: ProjectFileDTO | None = None
    overlay_file: ProjectFileDTO | None = None
    regions: list[RegionDTO] = Field(default_factory=list)
    metadata_summary: dict[str, Any] = Field(default_factory=dict)


class CriterionResultDTO(BaseModel):
    criterion_code: str
    severity: str
    status: Literal["pass", "warn", "fail", "unknown"]
    confidence: float | None = None
    anchor_artifact_id: str | None = None
    evidence_json: list[Any] = Field(default_factory=list)
    generated_comment: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    category: str | None = None


class ReviewResultDTO(BaseModel):
    project_id: str
    final_verdict: str | None
    review_markdown: str | None
    findings: list[CriterionResultDTO] = Field(default_factory=list)
    iteration_fix_summary: dict[str, Any] | None = None


class IterationChainNodeDTO(BaseModel):
    project_id: str
    parent_project_id: str | None = None
    iteration_no: int = 1
    status: str
    final_verdict: str | None = None
    source_type: str
    original_filename: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    review_turnaround_hours: float | None = None
    has_iteration_fix_summary: bool = False
    iteration_fix_status: str | None = None


class IterationChainResponse(BaseModel):
    """Resubmit chain from root iteration to the requested project."""

    anchor_project_id: str
    depth: int
    nodes: list[IterationChainNodeDTO]


class IterationInsightsResponse(BaseModel):
    """Aggregates for iteration-fix matching and resolution rows (admin / dashboards)."""

    project_id: str
    iteration_fix_policy_version: str | None = None
    summary_counts: dict[str, Any] | None = None
    summary_status: str | None = None
    notebook_runtime: dict[str, Any] | None = None
    stored_resolutions: int = 0
    resolution_status_histogram: dict[str, int] = Field(default_factory=dict)
    match_method_histogram: dict[str, int] = Field(default_factory=dict)
    multi_disambiguated_issues: int = 0


class FixRatesDTO(BaseModel):
    """Share of resolution outcomes (iteration fix verification)."""

    total: int = 0
    fixed: int = 0
    partially_fixed: int = 0
    not_fixed: int = 0
    cannot_verify: int = 0
    fixed_rate: float | None = None
    partially_fixed_rate: float | None = None
    not_fixed_rate: float | None = None
    cannot_verify_rate: float | None = None


class CriterionIterationCountsDTO(BaseModel):
    criterion_code: str
    fixed: int = 0
    partially_fixed: int = 0
    not_fixed: int = 0
    cannot_verify: int = 0
    total: int = 0
    fixed_rate: float | None = None


class AnchorChainMetricsBlockDTO(BaseModel):
    rates: FixRatesDTO
    multi_disambiguated_count: int = 0
    multi_disambiguated_share: float | None = None
    criterion_breakdown: list[CriterionIterationCountsDTO] = Field(default_factory=list)


class ChainRollupMetricsDTO(BaseModel):
    rates: FixRatesDTO
    multi_disambiguated_count: int = 0
    multi_disambiguated_share: float | None = None
    criterion_breakdown: list[CriterionIterationCountsDTO] = Field(default_factory=list)
    total_resolution_records: int = 0


class IterationStepMetricsDTO(BaseModel):
    project_id: str
    iteration_no: int
    parent_project_id: str | None = None
    hours_since_prior_iteration: float | None = None
    review_turnaround_hours: float | None = None
    rates: FixRatesDTO
    multi_disambiguated_count: int = 0
    multi_disambiguated_share: float | None = None
    criterion_breakdown: list[CriterionIterationCountsDTO] = Field(default_factory=list)


class IterationMetricsResponse(BaseModel):
    """Dashboard-friendly metrics for one project and its resubmit chain."""

    anchor_project_id: str
    chain_length: int
    chain_submission_span_hours: float | None = None
    iteration_fix_policy_version: str | None = None
    metadata_summary_counts: dict[str, Any] | None = None
    metadata_summary_status: str | None = None
    anchor: AnchorChainMetricsBlockDTO
    chain_rollup: ChainRollupMetricsDTO
    by_iteration: list[IterationStepMetricsDTO] = Field(default_factory=list)


class RecentIterationMetricRowDTO(BaseModel):
    project_id: str
    last_resolution_at: str | None = None
    total_issues_addressed: int = 0
    rates: FixRatesDTO
    multi_disambiguated_count: int = 0
    multi_disambiguated_share: float | None = None


class RecentIterationMetricsResponse(BaseModel):
    items: list[RecentIterationMetricRowDTO] = Field(default_factory=list)


class GlobalCriterionRollupResponse(BaseModel):
    """Sampled global aggregation of iteration resolutions by criterion_code."""

    sampled_resolution_rows: int
    max_rows_cap: int
    full_scan: bool = False
    overall_rates: FixRatesDTO
    by_criterion: list[CriterionIterationCountsDTO] = Field(default_factory=list)


class ChangelogEntryDTO(BaseModel):
    version: str
    items: list[str] = Field(default_factory=list, description="Bullet lines (markdown) under this version heading")


class ChangelogResponse(BaseModel):
    package_version: str
    source_path: str = "CHANGELOG.md"
    entries: list[ChangelogEntryDTO] = Field(default_factory=list)


class StudentAssistantSourceDTO(BaseModel):
    label: str
    source_kind: Literal[
        "project_doc",
        "course_base",
        "notebook_memory",
        "criteria",
        "senior_solution",
        "reviewer_style",
        "accepted_pattern",
        "external_web",
    ]
    excerpt: str
    score: float
    artifact_id: str | None = None
    url: str | None = None
    citation: str | None = None


class StudentAssistantChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)


class StudentAssistantChatResponse(BaseModel):
    answer: str
    sources: list[StudentAssistantSourceDTO] = Field(default_factory=list)
    needs_teacher: bool = False
    mode: Literal["extractive", "llm"] = "extractive"
    intent: str = "unknown"
    confidence: float = 0.0
    context_summary: str = ""
    used_memory: bool = False
    needs_teacher_reason: str | None = None
