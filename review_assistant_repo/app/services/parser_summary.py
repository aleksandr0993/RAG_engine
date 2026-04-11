from __future__ import annotations

from typing import Any


def build_parser_summary(project_metadata: dict[str, Any], source_type: str) -> dict[str, Any]:
    """High-level parser output summary for debugging (keys vary by source_type)."""
    base: dict[str, Any] = {"source_type": source_type}
    if source_type == "sql":
        base["query_count"] = project_metadata.get("query_count")
    if source_type == "pdf":
        base["page_signal_summary"] = {k: project_metadata.get(k) for k in ("signal_counts", "region_counts") if k in project_metadata}
    if source_type == "datalens":
        base.update(
            {
                "capture_status": project_metadata.get("capture_status"),
                "screenshot_paths_count": len(project_metadata.get("screenshot_paths") or []),
            }
        )
    if source_type == "html":
        base["source_flavor"] = project_metadata.get("source_flavor")
        base["char_count"] = project_metadata.get("char_count")
        base["practicum_revisor_html_detected"] = project_metadata.get("practicum_revisor_html_detected")
        base["practicum_revisor_detection_confidence"] = project_metadata.get("practicum_revisor_detection_confidence")
        base["practicum_revisor_detection_reasons"] = project_metadata.get("practicum_revisor_detection_reasons")
        base["practicum_input_channel"] = project_metadata.get("practicum_input_channel")
    base["extra_keys"] = sorted(project_metadata.keys())[:40]
    return base
