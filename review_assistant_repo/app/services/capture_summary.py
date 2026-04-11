from __future__ import annotations

from typing import Any


def build_capture_summary(project_metadata: dict[str, Any]) -> dict[str, Any]:
    """Normalize capture-related fields from project.metadata_json for debug endpoints."""
    keys = (
        "capture_status",
        "capture_method",
        "capture_available",
        "capture_skipped",
        "loaded_ok",
        "title",
        "number_of_screenshots",
        "discovered_tabs",
        "extracted_text_length",
        "capture_errors",
        "screenshot_paths",
        "capture_step_log",
        "capture_wall_duration_ms",
        "source_url",
        "domain",
    )
    return {k: project_metadata.get(k) for k in keys}
