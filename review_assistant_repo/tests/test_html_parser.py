from pathlib import Path

import pytest

from app.parsers.html import HTMLParser


@pytest.fixture()
def parser() -> HTMLParser:
    return HTMLParser()


def test_plain_html_artifacts(parser: HTMLParser, tmp_path: Path) -> None:
    p = tmp_path / "doc.html"
    p.write_text(
        """<!DOCTYPE html><html><body>
        <h1>Main</h1>
        <h3>Sub</h3>
        <p>""" + "x" * 85 + """</p>
        <p>Second paragraph for length.</p>
        <pre><code>a = 1</code></pre>
        <table><tr><td>1</td></tr></table>
        <img src="a.png" alt="fig" />
        </body></html>""",
        encoding="utf-8",
    )
    arts, meta = parser.parse(str(p))
    types = [a.artifact_type for a in arts]
    assert "html_heading" in types
    assert "html_intro_paragraph" in types
    assert "html_code_block" in types
    assert "html_table" in types
    assert "html_image" in types
    assert "html_document" in types
    assert meta["source_flavor"] == "html"
    assert meta.get("practicum_revisor_html_detected") is False
    assert meta.get("practicum_revisor_detection_confidence") == "none"


def test_practicum_domain_sets_revisor_hint(parser: HTMLParser, tmp_path: Path) -> None:
    p = tmp_path / "rev.html"
    p.write_text(
        """<!DOCTYPE html><html><body>
        <h1>Ревью</h1>
        <p>""" + "д" * 85 + """</p>
        <a href="https://practicum.yandex.ru/foo">Практикум</a>
        </body></html>""",
        encoding="utf-8",
    )
    arts, meta = parser.parse(str(p))
    assert meta["practicum_revisor_html_detected"] is True
    assert meta["practicum_revisor_detection_confidence"] == "strong"
    assert "yandex_practicum_url_in_dom_attribute" in meta["practicum_revisor_detection_reasons"]
    assert meta["source_flavor"] == "practicum_revisor_html"


def test_pasted_practicum_url_in_text_is_medium(parser: HTMLParser, tmp_path: Path) -> None:
    p = tmp_path / "paste.html"
    p.write_text(
        """<!DOCTYPE html><html><body><h1>Rep</h1><p>"""
        + "b" * 85
        + """ Ссылка https://practicum.yandex.ru/learn/courses</p></body></html>""",
        encoding="utf-8",
    )
    _, meta = parser.parse(str(p))
    assert meta["practicum_revisor_detection_confidence"] == "medium"
    assert meta["practicum_revisor_html_detected"] is True
    assert "yandex_practicum_url_in_markup" in meta["practicum_revisor_detection_reasons"]


def test_cyrylic_revisor_practicum_only_weak(parser: HTMLParser, tmp_path: Path) -> None:
    """Без URL Практикума — только слабый сигнал; канал и flavor не «revisor»."""
    p = tmp_path / "weak.html"
    body = "<p>" + "x" * 30 + " ревизор " + "y" * 30 + " практикум " + "z" * 30 + "</p>"
    p.write_text(f"<!DOCTYPE html><html><body>{body}</body></html>", encoding="utf-8")
    _, meta = parser.parse(str(p))
    assert meta["practicum_revisor_detection_confidence"] == "weak"
    assert meta["practicum_revisor_html_detected"] is False
    assert meta["source_flavor"] == "html"


def test_notion_meta_generator(parser: HTMLParser, tmp_path: Path) -> None:
    p = tmp_path / "notion.html"
    p.write_text(
        """<html><head>
        <meta name="generator" content="Notion 2.45.1" />
        </head><body><h1>N</h1><p>""" + "z" * 30 + """</p></body></html>""",
        encoding="utf-8",
    )
    _, meta = parser.parse(str(p))
    assert meta["source_flavor"] == "notion"


def test_notion_body_class(parser: HTMLParser, tmp_path: Path) -> None:
    p = tmp_path / "notion2.html"
    p.write_text(
        """<html><body><div class="notion-body"><h1>T</h1><p>"""
        + "q" * 90
        + """</p></div></body></html>""",
        encoding="utf-8",
    )
    arts, meta = parser.parse(str(p))
    assert meta["source_flavor"] == "notion"
    # Scoped to .notion-body: headings inside
    assert any(a.normalized_text and a.normalized_text.startswith("h1:") for a in arts)


def test_sample_file(parser: HTMLParser) -> None:
    path = Path("examples/sample_html_practicum.html")
    arts, meta = parser.parse(str(path))
    assert meta["source_flavor"] == "html"
    assert meta.get("practicum_revisor_html_detected") is False
    assert meta.get("practicum_revisor_detection_confidence") == "none"
    types = {a.artifact_type for a in arts}
    assert {"html_heading", "html_intro_paragraph", "html_code_block", "html_table", "html_image"} <= types
