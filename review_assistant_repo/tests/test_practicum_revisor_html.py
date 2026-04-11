from __future__ import annotations

from bs4 import BeautifulSoup

from app.parsers.practicum_revisor_html import analyze_practicum_revisor_html


def test_notion_disables_revisor_detection():
    soup = BeautifulSoup("<html><body>https://practicum.yandex.ru/foo</body></html>", "lxml")
    raw = soup.prettify()
    r = analyze_practicum_revisor_html(raw, soup, is_notion=True)
    assert r["practicum_revisor_detection_confidence"] == "none"
    assert r["practicum_revisor_html_detected"] is False
