from __future__ import annotations

import json
import logging
from typing import Any


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """
    Emit one JSON object per line (message field) for log aggregators.
    """
    payload = {"event": event, **{k: v for k, v in fields.items() if v is not None}}
    try:
        line = json.dumps(payload, ensure_ascii=False, default=str)
    except TypeError:
        line = json.dumps({"event": event, "error": "serialize_failed"}, ensure_ascii=False)
    logger.log(level, line)
