from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

from app.parsers.base import ParsedArtifact
from app.parsers.practicum_revisor_html import analyze_practicum_revisor_html


def _is_notion_export(soup: BeautifulSoup) -> bool:
    if soup.select_one(".notion-body"):
        return True
    meta = soup.find("meta", attrs={"name": "generator"})
    if meta and meta.get("content"):
        return bool(re.search(r"Notion", str(meta["content"]), re.I))
    return False


class HTMLParser:
    """Parse HTML (including Notion export) into review artifacts."""

    def parse(self, html_path: str) -> tuple[list[ParsedArtifact], dict]:
        raw = Path(html_path).read_text(encoding="utf-8")
        soup = BeautifulSoup(raw, "lxml")
        is_notion = _is_notion_export(soup)

        root = soup.select_one(".notion-body") if is_notion else soup.body
        if root is None:
            root = soup

        artifacts: list[ParsedArtifact] = []
        pos = 0

        def add(
            artifact_type: str,
            raw_text: str | None,
            normalized_text: str | None,
            metadata: dict | None = None,
        ) -> None:
            nonlocal pos
            artifacts.append(
                ParsedArtifact(
                    artifact_type=artifact_type,
                    position_idx=pos,
                    raw_text=raw_text,
                    normalized_text=normalized_text,
                    metadata=metadata or {},
                )
            )
            pos += 1

        # Headings h1–h4
        for tag in root.find_all(["h1", "h2", "h3", "h4"]):
            text = tag.get_text(" ", strip=True)
            if not text:
                continue
            level = int(tag.name[1])
            add(
                "html_heading",
                raw_text=str(tag),
                normalized_text=f"h{level}: {text}",
                metadata={"level": level, "tag": tag.name},
            )

        # Paragraphs (substantive)
        for tag in root.find_all("p"):
            text = tag.get_text(" ", strip=True)
            if len(text) < 20:
                continue
            add("html_paragraph", raw_text=str(tag), normalized_text=text)

        # Intro: only the first <p>; pass criterion if it is long enough
        first_p = root.find("p")
        if first_p is not None:
            intro_text = first_p.get_text(" ", strip=True)
            if len(intro_text) >= 80:
                add(
                    "html_intro_paragraph",
                    raw_text=str(first_p),
                    normalized_text=intro_text,
                    metadata={"role": "intro"},
                )

        # Code: <pre><code> blocks and standalone <code> (skip tiny inline noise)
        for tag in root.find_all("pre"):
            code = tag.find("code")
            block = (code or tag).get_text("\n", strip=True)
            if block:
                add("html_code_block", raw_text=str(tag), normalized_text=block)
        for tag in root.find_all("code"):
            if tag.find_parent("pre") is not None:
                continue
            block = tag.get_text("\n", strip=True)
            if len(block) >= 10:
                add("html_code_block", raw_text=str(tag), normalized_text=block)

        for _ in root.find_all("table"):
            add("html_table", raw_text=None, normalized_text="<table>")

        for img in root.find_all("img"):
            raw_alt = img.get("alt")
            alt = (raw_alt if isinstance(raw_alt, str) else str(raw_alt or "")).strip()
            add(
                "html_image",
                raw_text=None,
                normalized_text=alt or "<img>",
                metadata={"src": img.get("src")},
            )

        # Full visible text for length / global checks
        full_text = root.get_text(" ", strip=True)
        add(
            "html_document",
            raw_text=None,
            normalized_text=full_text,
            metadata={"char_count": len(full_text)},
        )

        rev = analyze_practicum_revisor_html(raw, soup, is_notion=is_notion)
        flavor = "notion" if is_notion else "html"
        if rev["practicum_revisor_html_detected"] and not is_notion:
            flavor = "practicum_revisor_html"

        meta = {
            "source_flavor": flavor,
            "artifact_count": len(artifacts),
            "char_count": len(full_text),
            **rev,
        }
        return artifacts, meta
