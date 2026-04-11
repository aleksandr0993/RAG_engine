from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

# Официальные хосты Практикума в ссылках / ресурсах страницы.
_PRACTICUM_URL_IN_ATTR = re.compile(
    r"https?://(?:[\w.-]+\.)?(?:practicum|praktikum)\.yandex(?:\.ru)?(?:/|\?|#|$)",
    re.IGNORECASE,
)
# URL в сыром HTML (в т.ч. в тексте или data-*), без обязательного тега <a>.
_PRACTICUM_URL_IN_RAW = re.compile(
    r"(?:https?:)?//(?:[\w.-]+\.)?(?:practicum|praktikum)\.yandex(?:\.ru)?(?:/|\?|#|\"|'|\s|>|$)",
    re.IGNORECASE,
)


def _url_like_attributes(soup: BeautifulSoup) -> list[str]:
    out: list[str] = []
    for tag in soup.find_all(True):
        if tag.name == "meta":
            prop_raw = tag.get("property")
            prop = str(prop_raw or "").lower()
            if prop == "og:url":
                c = tag.get("content")
                if isinstance(c, str) and c.strip():
                    out.append(c.strip())
            continue
        for attr in ("href", "src", "action", "data-src", "data-href", "poster"):
            v = tag.get(attr)
            if isinstance(v, str) and v.strip():
                out.append(v.strip())
    return out


def analyze_practicum_revisor_html(
    raw: str,
    soup: BeautifulSoup,
    *,
    is_notion: bool,
) -> dict[str, Any]:
    """
    Многоуровневая эвристика Revisor / Практикум для сохранённого HTML.

    - **strong**: URL Практикума в атрибуте DOM (href/src/…).
    - **medium**: тот же хост в разметке (сырой HTML), без явного атрибута.
    - **weak**: только кириллические «ревизор» + «практикум» — не поднимает канал и не меняет flavor.

    ``practicum_revisor_html_detected`` = True только для medium/strong (обратная совместимость с апгрейдом канала).
    """
    empty = {
        "practicum_revisor_html_detected": False,
        "practicum_revisor_detection_confidence": "none",
        "practicum_revisor_detection_reasons": [],
        "practicum_revisor_score": 0,
    }
    if is_notion:
        return dict(empty)

    reasons: list[str] = []
    score = 0

    for val in _url_like_attributes(soup):
        if _PRACTICUM_URL_IN_ATTR.search(val):
            score = max(score, 4)
            reasons.append("yandex_practicum_url_in_dom_attribute")
            break

    if score < 4 and _PRACTICUM_URL_IN_RAW.search(raw):
        score = max(score, 3)
        if "yandex_practicum_url_in_markup" not in reasons:
            reasons.append("yandex_practicum_url_in_markup")

    lower_raw = raw.lower()
    if "ревизор" in raw and "практикум" in lower_raw and score < 3:
        score = max(score, 1)
        reasons.append("cyrylic_revisor_and_practicum")

    if score >= 4:
        confidence = "strong"
    elif score >= 3:
        confidence = "medium"
    elif score >= 1:
        confidence = "weak"
    else:
        confidence = "none"

    detected = confidence in ("strong", "medium")

    return {
        "practicum_revisor_html_detected": detected,
        "practicum_revisor_detection_confidence": confidence,
        "practicum_revisor_detection_reasons": reasons,
        "practicum_revisor_score": score,
    }
