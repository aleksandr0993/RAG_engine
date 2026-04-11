from fastapi import APIRouter

from app.utils.config_loader import (
    build_criteria_categories_index,
    list_criteria_maps,
    list_style_profiles,
    load_criteria_map,
    load_style_profile,
)

router = APIRouter(tags=["config"])


@router.get("/config/criteria")
def get_criteria():
    return {code: load_criteria_map(code) for code in list_criteria_maps()}


@router.get("/config/style_profiles")
def get_style_profiles():
    return {code: load_style_profile(code) for code in list_style_profiles()}


@router.get("/config/criteria_categories")
def get_criteria_categories() -> dict[str, list[str]]:
    """All category values and their criterion codes, aggregated across criteria maps."""
    return build_criteria_categories_index()
