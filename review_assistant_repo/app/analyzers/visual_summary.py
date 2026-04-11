from __future__ import annotations

from collections import Counter
from typing import Any

from app.models import Artifact, ProjectFile

REGION_ARTIFACT_TYPES = frozenset(
    {"pdf_region", "pdf_image_region", "datalens_region", "datalens_image_region"}
)


def build_visual_debug_payload(artifact_rows: list[Artifact], file_rows: list[ProjectFile]) -> dict[str, Any]:
    """
    Aggregate visual pipeline stats for explorer API: region kinds, low-quality pages, preview linkage.
    """
    image_region_count = 0
    text_region_count = 0
    region_kind_counts: Counter[str] = Counter()
    low_text_pages: list[int | None] = []
    low_confidence_pages: list[int | None] = []

    for row in artifact_rows:
        if row.artifact_type not in REGION_ARTIFACT_TYPES:
            continue
        meta = row.metadata_json or {}
        rk = meta.get("region_kind") or "unknown"
        region_kind_counts[rk] += 1
        if "image" in row.artifact_type:
            image_region_count += 1
            conf = meta.get("region_confidence")
            page = meta.get("page_no")
            if page is None:
                page = meta.get("capture_index")
            if conf is not None and float(conf) < 0.45:
                low_confidence_pages.append(page)
        else:
            text_region_count += 1

    for row in artifact_rows:
        if row.artifact_type != "pdf_page":
            continue
        meta = row.metadata_json or {}
        page = meta.get("page_no")
        char_count = int(meta.get("char_count") or 0)
        if char_count < 12:
            low_text_pages.append(page)

    overlay_by_page: dict[Any, str] = {}
    base_by_page: dict[Any, str] = {}
    for f in file_rows:
        if f.kind == "pdf_page_image" and f.page_no is not None:
            base_by_page[f.page_no] = f.id
        if f.kind in {"pdf_page_overlay", "capture_overlay"} and f.page_no is not None:
            overlay_by_page[f.page_no] = f.id

    preview_pairs_meta: list[dict[str, Any]] = []
    for page in sorted(set(base_by_page) | set(overlay_by_page), key=lambda x: (-1 if x is None else x)):
        preview_pairs_meta.append(
            {
                "page_no": page,
                "base_file_id": base_by_page.get(page),
                "overlay_file_id": overlay_by_page.get(page),
            }
        )

    return {
        "region_kind_counts": dict(region_kind_counts),
        "image_region_count": image_region_count,
        "text_region_count": text_region_count,
        "low_text_extraction_pages": sorted({p for p in low_text_pages if p is not None}),
        "low_region_confidence_pages": sorted({p for p in low_confidence_pages if p is not None}),
        "preview_pairs_meta": preview_pairs_meta,
    }
