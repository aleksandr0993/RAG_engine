from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

REGION_COLORS: dict[str, tuple[int, int, int]] = {
    "header": (30, 144, 255),
    "filter": (255, 140, 0),
    "metric": (50, 205, 50),
    "chart": (186, 85, 211),
    "table": (220, 20, 60),
    "panel": (128, 128, 128),
}


def _segments(values: list[float], threshold: float, min_len: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    start: int | None = None
    for idx, value in enumerate(values):
        if value >= threshold and start is None:
            start = idx
        elif value < threshold and start is not None:
            if idx - start >= min_len:
                out.append((start, idx - 1))
            start = None
    if start is not None and len(values) - start >= min_len:
        out.append((start, len(values) - 1))
    return out


def _classify_region(x0: int, y0: int, x1: int, y1: int, width: int, height: int) -> str:
    w = max(1, x1 - x0 + 1)
    h = max(1, y1 - y0 + 1)
    width_norm = w / max(width, 1)
    height_norm = h / max(height, 1)
    top_norm = y0 / max(height, 1)

    if top_norm < 0.14 and height_norm < 0.12 and width_norm > 0.45:
        return "header"
    if width_norm > 0.62 and height_norm < 0.16:
        return "filter"
    if width_norm < 0.34 and height_norm < 0.22:
        return "metric"
    if width_norm > 0.30 and height_norm > 0.18:
        return "chart"
    if width_norm > 0.35 and height_norm < 0.22:
        return "table"
    return "panel"


def _region_confidence(w: int, h: int, img_w: int, img_h: int, region_kind: str) -> float:
    area = (w * h) / max(img_w * img_h, 1)
    base = 0.42 + min(area * 2.5, 0.45)
    if region_kind in {"chart", "table"}:
        base += 0.05
    return round(min(0.95, max(0.35, base)), 4)


def _crop_bbox(mask: list[list[int]], x0: int, y0: int, x1: int, y1: int) -> tuple[int, int, int, int]:
    min_x, min_y = x1, y1
    max_x, max_y = x0, y0
    found = False
    for y in range(y0, y1 + 1):
        row = mask[y]
        for x in range(x0, x1 + 1):
            if row[x]:
                found = True
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y
    if not found:
        return x0, y0, x1, y1
    return min_x, min_y, max_x, max_y


def _try_font(size: int = 12) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size=size)
    except OSError:
        try:
            return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=size)
        except OSError:
            return ImageFont.load_default()


def segment_dashboard_image(image_path: str, overlay_output_path: str | None = None) -> dict[str, Any]:
    """
    Heuristic dashboard region segmentation with typed overlays, confidence scores,
    and noise rejection for tiny rectangles.
    """
    try:
        original = Image.open(image_path).convert("RGB")
    except Exception as exc:
        return {"regions": [], "overlay_path": None, "error": f"open_failed:{type(exc).__name__}"}

    width, height = original.size
    scale = min(1.0, 700.0 / max(width, 1))
    analysis_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    analysis = original.resize(analysis_size).convert("L") if scale < 1.0 else original.convert("L")
    aw, ah = analysis.size
    px = analysis.load()

    threshold = 245
    mask = [[1 if px[x, y] < threshold else 0 for x in range(aw)] for y in range(ah)]

    total_nonwhite = sum(sum(row) for row in mask)
    if total_nonwhite == 0:
        return {"regions": [], "overlay_path": None, "error": "blank_image"}

    row_density = [sum(row) / max(aw, 1) for row in mask]
    row_threshold = max(0.01, min(0.10, total_nonwhite / max(aw * ah, 1) * 1.2))
    bands = _segments(row_density, row_threshold, min_len=max(12, ah // 40))

    regions_small: list[tuple[int, int, int, int]] = []
    for y0, y1 in bands:
        col_density: list[float] = []
        band_height = y1 - y0 + 1
        for x in range(aw):
            black = 0
            for y in range(y0, y1 + 1):
                black += mask[y][x]
            col_density.append(black / max(band_height, 1))
        col_threshold = max(0.01, min(0.12, sum(col_density) / max(len(col_density), 1) * 0.9 + 0.01))
        cols = _segments(col_density, col_threshold, min_len=max(18, aw // 30))
        if not cols:
            cols = [(0, aw - 1)]
        for x0, x1 in cols:
            bx0, by0, bx1, by1 = _crop_bbox(mask, x0, y0, x1, y1)
            min_w = max(36, aw // 16)
            min_h = max(28, ah // 28)
            if (bx1 - bx0 + 1) < min_w or (by1 - by0 + 1) < min_h:
                continue
            regions_small.append((bx0, by0, bx1, by1))

    if not regions_small:
        xs, ys = [], []
        for y in range(ah):
            for x in range(aw):
                if mask[y][x]:
                    xs.append(x)
                    ys.append(y)
        if xs and ys:
            regions_small.append((min(xs), min(ys), max(xs), max(ys)))

    deduped: list[tuple[int, int, int, int]] = []
    for box in regions_small:
        x0, y0, x1, y1 = box
        keep = True
        for ex in deduped:
            ex0, ey0, ex1, ey1 = ex
            inter_x0, inter_y0 = max(x0, ex0), max(y0, ey0)
            inter_x1, inter_y1 = min(x1, ex1), min(y1, ey1)
            if inter_x1 >= inter_x0 and inter_y1 >= inter_y0:
                inter = (inter_x1 - inter_x0 + 1) * (inter_y1 - inter_y0 + 1)
                area = (x1 - x0 + 1) * (y1 - y0 + 1)
                ex_area = (ex1 - ex0 + 1) * (ey1 - ey0 + 1)
                overlap = inter / max(min(area, ex_area), 1)
                if overlap > 0.65:
                    keep = False
                    break
        if keep:
            deduped.append(box)

    regions: list[dict[str, Any]] = []
    draw = ImageDraw.Draw(original)
    font = _try_font(11)
    legend_y = 8
    legend_items: list[str] = []

    for idx, (x0, y0, x1, y1) in enumerate(deduped, start=1):
        ox0 = int(round(x0 / scale)) if scale else x0
        oy0 = int(round(y0 / scale)) if scale else y0
        ox1 = int(round(x1 / scale)) if scale else x1
        oy1 = int(round(y1 / scale)) if scale else y1
        ox0 = max(0, min(width - 1, ox0))
        oy0 = max(0, min(height - 1, oy0))
        ox1 = max(ox0, min(width - 1, ox1))
        oy1 = max(oy0, min(height - 1, oy1))
        region_kind = _classify_region(ox0, oy0, ox1, oy1, width, height)
        color = REGION_COLORS.get(region_kind, (200, 50, 50))
        draw.rectangle([ox0, oy0, ox1, oy1], outline=color, width=3)
        rw, rh = ox1 - ox0 + 1, oy1 - oy0 + 1
        conf = _region_confidence(rw, rh, width, height, region_kind)
        label = f"r{idx}:{region_kind}"
        label_y = max(0, oy0 - 18)
        draw.text((ox0 + 4, label_y), label, fill=color, font=font)
        legend_items.append(f"{label} ({conf})")
        regions.append(
            {
                "region_id": f"r{idx}",
                "bbox": [ox0, oy0, ox1, oy1],
                "bbox_normalized": [
                    round(ox0 / max(width, 1), 4),
                    round(oy0 / max(height, 1), 4),
                    round(ox1 / max(width, 1), 4),
                    round(oy1 / max(height, 1), 4),
                ],
                "region_kind": region_kind,
                "tags": [region_kind, "image_region"],
                "region_confidence": conf,
                "source_type": "image",
            }
        )

    if legend_items:
        legend_text = "Regions: " + "; ".join(legend_items[:6])
        if len(legend_items) > 6:
            legend_text += "…"
        draw.rectangle([4, legend_y, min(width - 4, 520), legend_y + 22], fill=(248, 248, 248))
        draw.text((8, legend_y + 4), legend_text[:180], fill=(20, 20, 20), font=font)

    overlay_path = None
    if overlay_output_path:
        overlay_path = str(Path(overlay_output_path))
        Path(overlay_path).parent.mkdir(parents=True, exist_ok=True)
        original.save(overlay_path)

    return {
        "regions": regions,
        "overlay_path": overlay_path,
        "error": None,
        "base_image_path": image_path,
        "metadata": {"region_count": len(regions), "segmentation": "projection_heuristic"},
    }
