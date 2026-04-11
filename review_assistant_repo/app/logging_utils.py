from __future__ import annotations

import json
import logging
from typing import Any


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """
    Emit a single JSON-compatible line for log aggregators (project_id, stage, duration_ms, ...).
    """
    payload = {"event": event, **{k: v for k, v in fields.items() if v is not None}}
    try:
        line = json.dumps(payload, ensure_ascii=False, default=str)
    except TypeError:
        line = json.dumps({"event": event, "error": "non_serializable_fields"}, ensure_ascii=False)
    logger.log(level, "%s", line)
