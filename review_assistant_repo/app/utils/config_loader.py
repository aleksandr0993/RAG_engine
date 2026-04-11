from collections import defaultdict
from pathlib import Path

from app.utils.files import load_json

_REPO_ROOT = Path(__file__).resolve().parents[2]
CRITERIA_DIR = _REPO_ROOT / "configs" / "criteria_maps"
STYLE_DIR = _REPO_ROOT / "configs" / "style_profiles"


def list_criteria_maps() -> list[str]:
    return sorted(p.stem for p in CRITERIA_DIR.glob("*.json"))


def list_style_profiles() -> list[str]:
    return sorted(p.stem for p in STYLE_DIR.glob("*.json"))


def load_criteria_map(code: str) -> list[dict]:
    if code not in list_criteria_maps():
        raise ValueError(f"Unknown criteria map: {code!r}")
    return load_json(CRITERIA_DIR / f"{code}.json")["criteria"]


def build_criteria_categories_index() -> dict[str, list[str]]:
    """Category code → sorted unique criterion codes across all maps."""
    by_cat: dict[str, set[str]] = defaultdict(set)
    for map_code in list_criteria_maps():
        for c in load_criteria_map(map_code):
            cat = c.get("category")
            code = c.get("code")
            if isinstance(cat, str) and cat and isinstance(code, str) and code:
                by_cat[cat].add(code)
    return {k: sorted(v) for k, v in sorted(by_cat.items())}


def load_style_profile(code: str) -> dict:
    if code not in list_style_profiles():
        raise ValueError(f"Unknown style profile: {code!r}")
    return load_json(STYLE_DIR / f"{code}.json")
