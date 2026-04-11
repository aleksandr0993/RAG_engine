from __future__ import annotations

from pathlib import Path

from app.capture.datalens import DataLensCaptureService
from app.parsers.base import ParsedArtifact
from app.utils.image_regions import segment_dashboard_image


class DataLensParser:
    def __init__(self):
        self.capture_service = DataLensCaptureService()

    def parse(self, source_url: str, capture_dir: str | None = None) -> tuple[list[ParsedArtifact], dict]:
        capture_meta = self.capture_service.capture(source_url, capture_dir=capture_dir)
        summary_parts = [source_url, capture_meta.get("domain") or "", *(capture_meta.get("path_segments") or [])]
        if capture_meta.get("title"):
            summary_parts.append(capture_meta["title"])
        summary_text = " | ".join(part for part in summary_parts if part)

        artifacts = [
            ParsedArtifact(
                artifact_type="datalens_url",
                position_idx=0,
                raw_text=source_url,
                normalized_text=source_url,
                metadata={
                    "capture_status": capture_meta.get("capture_status"),
                    "capture_method": capture_meta.get("capture_method"),
                    "domain": capture_meta.get("domain"),
                },
            ),
            ParsedArtifact(
                artifact_type="datalens_capture_summary",
                position_idx=1,
                raw_text=summary_text,
                normalized_text=summary_text,
                metadata={
                    "capture_available": capture_meta.get("capture_available", False),
                    "capture_status": capture_meta.get("capture_status"),
                    "capture_skipped": capture_meta.get("capture_skipped", True),
                    "screenshot_count": len(capture_meta.get("screenshot_paths") or []),
                    "loaded_ok": capture_meta.get("loaded_ok", False),
                    "title": capture_meta.get("title"),
                    "number_of_screenshots": capture_meta.get("number_of_screenshots", 0),
                    "discovered_tabs": capture_meta.get("discovered_tabs") or [],
                    "extracted_text_length": capture_meta.get("extracted_text_length", 0),
                    "capture_errors": capture_meta.get("capture_errors") or [],
                    "capture_step_log": capture_meta.get("capture_step_log") or [],
                    "capture_wall_duration_ms": capture_meta.get("capture_wall_duration_ms", 0),
                },
            ),
        ]

        generated_files = list(capture_meta.get("generated_files") or [])

        for idx, screenshot_path in enumerate(capture_meta.get("screenshot_paths") or [], start=2):
            artifacts.append(
                ParsedArtifact(
                    artifact_type="datalens_capture_image",
                    position_idx=idx,
                    raw_text=screenshot_path,
                    normalized_text=f"datalens_capture_image {screenshot_path}",
                    metadata={"path": screenshot_path, "capture_status": capture_meta.get("capture_status")},
                )
            )

            overlay_path = None
            if screenshot_path and capture_dir:
                overlay_path = str(Path(capture_dir) / f"capture_overlay_{idx - 1}.png")
            segmentation = segment_dashboard_image(screenshot_path, overlay_path)
            for region_idx, region in enumerate(segmentation.get("regions") or [], start=1):
                artifacts.append(
                    ParsedArtifact(
                        artifact_type="datalens_image_region",
                        position_idx=1000 + idx * 100 + region_idx,
                        raw_text=f"image_region:{region['region_kind']}",
                        normalized_text=f"datalens_image_region {region['region_kind']}",
                        metadata={
                            "capture_index": idx - 2,
                            "page_no": idx - 2,
                            "region_id": region.get("region_id"),
                            "region_kind": region["region_kind"],
                            "tags": region.get("tags") or [region["region_kind"]],
                            "bbox": region["bbox"],
                            "bbox_normalized": region["bbox_normalized"],
                            "region_confidence": region.get("region_confidence"),
                            "source": "image_segmentation",
                            "source_type": region.get("source_type", "image"),
                            "image_path": screenshot_path,
                        },
                    )
                )
            if segmentation.get("overlay_path"):
                generated_files.append(
                    {
                        "kind": "capture_overlay",
                        "storage_path": segmentation["overlay_path"],
                        "mime_type": "image/png",
                        "page_no": idx - 2,
                        "metadata_json": {"source": "image_segmentation", "region_count": len(segmentation.get("regions") or [])},
                    }
                )
                artifacts.append(
                    ParsedArtifact(
                        artifact_type="datalens_capture_overlay",
                        position_idx=2000 + idx,
                        raw_text=segmentation["overlay_path"],
                        normalized_text=f"datalens_capture_overlay {segmentation['overlay_path']}",
                        metadata={"path": segmentation["overlay_path"], "region_count": len(segmentation.get("regions") or [])},
                    )
                )

        base_idx = 100
        for offset, fragment in enumerate(capture_meta.get("text_fragments") or [], start=0):
            fragment = (fragment or "").strip()
            if not fragment:
                continue
            lower = fragment.lower()
            region_kind = "text"
            tags = []
            if any(token in lower for token in ["filter", "фильтр", "segment", "срез"]):
                region_kind = "filter"
                tags.append("filter")
            elif any(token in lower for token in ["kpi", "revenue", "выруч", "ctr", "retention", "metric", "метрик"]):
                region_kind = "metric"
                tags.append("metric")
            elif any(token in lower for token in ["table", "таблиц", "top", "chart", "график"]):
                region_kind = "chart"
                tags.append("chart")

            artifacts.append(
                ParsedArtifact(
                    artifact_type="datalens_text_fragment",
                    position_idx=base_idx + offset,
                    raw_text=fragment,
                    normalized_text=fragment,
                    metadata={"capture_status": capture_meta.get("capture_status")},
                )
            )
            artifacts.append(
                ParsedArtifact(
                    artifact_type="datalens_region",
                    position_idx=base_idx + 100 + offset,
                    raw_text=fragment,
                    normalized_text=fragment,
                    metadata={"region_kind": region_kind, "tags": tags, "capture_status": capture_meta.get("capture_status")},
                )
            )

        capture_meta["generated_files"] = generated_files
        return artifacts, capture_meta
