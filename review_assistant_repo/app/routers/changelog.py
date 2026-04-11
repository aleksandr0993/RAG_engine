from __future__ import annotations

import importlib.metadata

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ChangelogEntryDTO, ChangelogResponse
from app.utils.changelog import changelog_file_path, load_changelog_entries

router = APIRouter(tags=["changelog"])


def _package_version() -> str:
    try:
        return importlib.metadata.version("review-assistant-practicum")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


@router.get("/changelog", response_model=ChangelogResponse)
def get_changelog(
    limit: int | None = Query(
        default=None,
        ge=1,
        le=200,
        description="Max number of version sections (newest first as in CHANGELOG.md)",
    ),
):
    path = changelog_file_path()
    if not path.is_file():
        raise HTTPException(status_code=503, detail="Changelog file is not available on this deployment")

    entries = load_changelog_entries(limit=limit)
    return ChangelogResponse(
        package_version=_package_version(),
        source_path=str(path.name),
        entries=[ChangelogEntryDTO(version=v, items=items) for v, items in entries],
    )
