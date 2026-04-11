from __future__ import annotations

from pathlib import Path

import fitz

from app.parsers.base import ParsedArtifact
from app.utils.image_regions import segment_dashboard_image


class PDFParser:
    KEYWORDS = {
        "filter": ["фильтр", "filter", "срез"],
        "metric": ["kpi", "метрик", "выруч", "доход", "прибыл", "ctr", "retention"],
        "chart": ["график", "chart", "legend", "ось", "линейный", "bar", "line"],
        "table": ["таблиц", "table", "top", "итого"],
    }

    def parse(self, pdf_path: str, output_dir: str | None = None) -> tuple[list[ParsedArtifact], dict]:
        doc = fitz.open(pdf_path)
        artifacts: list[ParsedArtifact] = []
        signal_counts = {key: 0 for key in self.KEYWORDS}
        region_counts = {"filter": 0, "metric": 0, "chart": 0, "table": 0, "text": 0}
        image_region_counts: dict[str, int] = {"header": 0, "filter": 0, "metric": 0, "chart": 0, "table": 0, "panel": 0}
        generated_files: list[dict] = []

        page_images_dir = None
        if output_dir:
            page_images_dir = Path(output_dir) / "pdf_pages"
            page_images_dir.mkdir(parents=True, exist_ok=True)

        for page_index, page in enumerate(doc):
            page_text = page.get_text("text") or ""
            blocks = page.get_text("blocks") or []
            page_width = float(page.rect.width or 1.0)
            page_height = float(page.rect.height or 1.0)
            page_image_path = None

            if page_images_dir is not None:
                page_image_path = page_images_dir / f"page_{page_index + 1}.png"
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                pix.save(page_image_path)
                generated_files.append(
                    {
                        "kind": "pdf_page_image",
                        "storage_path": str(page_image_path),
                        "mime_type": "image/png",
                        "page_no": page_index,
                        "metadata_json": {"source": "pdf_render", "width": pix.width, "height": pix.height},
                    }
                )
                artifacts.append(
                    ParsedArtifact(
                        artifact_type="pdf_page_image",
                        position_idx=page_index * 1000,
                        raw_text=str(page_image_path),
                        normalized_text=f"pdf_page_image page={page_index + 1}",
                        metadata={"page_no": page_index, "path": str(page_image_path)},
                    )
                )

                overlay_path = page_images_dir / f"page_{page_index + 1}_overlay.png"
                segmentation = segment_dashboard_image(str(page_image_path), str(overlay_path))
                for region_idx, region in enumerate(segmentation.get("regions") or [], start=1):
                    region_kind = region["region_kind"]
                    image_region_counts[region_kind] = image_region_counts.get(region_kind, 0) + 1
                    artifacts.append(
                        ParsedArtifact(
                            artifact_type="pdf_image_region",
                            position_idx=page_index * 1000 + 700 + region_idx,
                            raw_text=f"image_region:{region_kind}",
                            normalized_text=f"image_region {region_kind} page={page_index + 1}",
                            metadata={
                                "page_no": page_index,
                                "region_id": region.get("region_id"),
                                "region_kind": region_kind,
                                "tags": region.get("tags") or [region_kind],
                                "bbox": region["bbox"],
                                "bbox_normalized": region["bbox_normalized"],
                                "region_confidence": region.get("region_confidence"),
                                "source": "image_segmentation",
                                "source_type": region.get("source_type", "image"),
                                "image_path": str(page_image_path),
                            },
                        )
                    )
                if segmentation.get("overlay_path"):
                    generated_files.append(
                        {
                            "kind": "pdf_page_overlay",
                            "storage_path": segmentation["overlay_path"],
                            "mime_type": "image/png",
                            "page_no": page_index,
                            "metadata_json": {"source": "image_segmentation", "region_count": len(segmentation.get("regions") or [])},
                        }
                    )
                    artifacts.append(
                        ParsedArtifact(
                            artifact_type="pdf_page_overlay",
                            position_idx=page_index * 1000 + 2,
                            raw_text=segmentation["overlay_path"],
                            normalized_text=f"pdf_page_overlay page={page_index + 1}",
                            metadata={"page_no": page_index, "path": segmentation["overlay_path"], "region_count": len(segmentation.get("regions") or [])},
                        )
                    )

            artifacts.append(
                ParsedArtifact(
                    artifact_type="pdf_page",
                    position_idx=page_index * 1000 + 1,
                    raw_text=page_text,
                    normalized_text=page_text.strip(),
                    metadata={"page_no": page_index, "char_count": len(page_text.strip())},
                )
            )

            for block_idx, block in enumerate(blocks, start=1):
                x0, y0, x1, y1, text, *_ = block
                text = (text or "").strip()
                if len(text) < 3:
                    continue
                lower = text.lower()
                tags = []
                region_kind = "text"
                for signal, keywords in self.KEYWORDS.items():
                    if any(keyword in lower for keyword in keywords):
                        tags.append(signal)
                        signal_counts[signal] += 1
                if tags:
                    region_kind = tags[0]
                region_counts[region_kind] += 1

                bbox = [round(float(x0), 2), round(float(y0), 2), round(float(x1), 2), round(float(y1), 2)]
                bbox_norm = [round(float(x0) / page_width, 4), round(float(y0) / page_height, 4), round(float(x1) / page_width, 4), round(float(y1) / page_height, 4)]

                artifacts.append(
                    ParsedArtifact(
                        artifact_type="pdf_text_block",
                        position_idx=page_index * 1000 + 100 + block_idx,
                        raw_text=text,
                        normalized_text=text,
                        metadata={"page_no": page_index, "tags": tags},
                    )
                )
                artifacts.append(
                    ParsedArtifact(
                        artifact_type="pdf_region",
                        position_idx=page_index * 1000 + 500 + block_idx,
                        raw_text=text,
                        normalized_text=text,
                        metadata={
                            "page_no": page_index,
                            "region_kind": region_kind,
                            "tags": tags,
                            "bbox": bbox,
                            "bbox_normalized": bbox_norm,
                        },
                    )
                )

            summary_tokens = []
            page_lower = page_text.lower()
            for signal, keywords in self.KEYWORDS.items():
                if any(keyword in page_lower for keyword in keywords):
                    summary_tokens.append(signal)
            artifacts.append(
                ParsedArtifact(
                    artifact_type="pdf_page_summary",
                    position_idx=page_index * 1000 + 999,
                    raw_text=" ".join(summary_tokens),
                    normalized_text=" ".join(summary_tokens),
                    metadata={"page_no": page_index, "signals": summary_tokens},
                )
            )

        meta = {
            "pages": len(doc),
            "signal_counts": signal_counts,
            "region_counts": region_counts,
            "image_region_counts": image_region_counts,
            "generated_files": generated_files,
        }
        return artifacts, meta
