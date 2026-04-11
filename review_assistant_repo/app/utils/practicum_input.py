from __future__ import annotations


def normalize_practicum_input_channel(
    raw: str | None,
    *,
    source_type: str,
) -> tuple[str, dict[str, bool]]:
    """
    Приводит значение формы к канону и возвращает флаги.

    Возвращает (channel_for_metadata, flags).
    channel_for_metadata: jupyter | revisor | <source_type> для прочих форматов.
    """
    v = (raw or "").strip().lower().replace("-", "_")
    if v in ("", "auto"):
        if source_type == "ipynb":
            return "jupyter", {"explicit": False}
        if source_type == "html":
            return "html", {"explicit": False}
        return source_type, {"explicit": False}

    if v in ("jupyter", "jupyter_notebook"):
        if source_type != "ipynb":
            raise ValueError(
                "practicum_input_channel=jupyter is only valid for .ipynb uploads (локальный Jupyter или экспорт ноутбука)."
            )
        return "jupyter", {"explicit": True}

    if v in ("revisor", "practicum_revisor"):
        return "revisor", {"explicit": True}

    raise ValueError(
        f"Invalid practicum_input_channel: {raw!r}. Use auto, jupyter, or revisor (или пусто)."
    )
