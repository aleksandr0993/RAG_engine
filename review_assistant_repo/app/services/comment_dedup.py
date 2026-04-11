from __future__ import annotations


def dedupe_notebook_insertions(insertions: list[dict]) -> list[dict]:
    """
    Remove duplicate reviewer cells: same HTML body or same anchor+body.
    Preserves first occurrence (typically earlier anchor).
    """
    seen_html: set[str] = set()
    seen_pair: set[tuple[int, str]] = set()
    out: list[dict] = []
    for item in insertions:
        html = item.get("comment_html") or ""
        anchor = int(item.get("anchor_position_idx") or 0)
        key_pair = (anchor, html)
        if html in seen_html:
            continue
        if key_pair in seen_pair:
            continue
        seen_html.add(html)
        seen_pair.add(key_pair)
        out.append(item)
    return out
