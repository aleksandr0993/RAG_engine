from __future__ import annotations

from typing import Any


def observation_to_jsonable(obs: Any) -> dict[str, Any]:
    """Convert a Gymnasium observation into a JSON-friendly dict for API responses."""
    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore[assignment]

    if np is not None and isinstance(obs, np.ndarray):
        return {
            "kind": "ndarray",
            "dtype": str(obs.dtype),
            "shape": list(obs.shape),
            "values": obs.tolist(),
        }
    if isinstance(obs, (bool, int, float)):
        return {"kind": "scalar", "value": obs}
    if isinstance(obs, dict):
        return {k: observation_to_jsonable(v) for k, v in obs.items()}
    if isinstance(obs, (list, tuple)):
        return {"kind": "sequence", "values": [observation_to_jsonable(x) for x in obs]}
    return {"kind": "repr", "value": repr(obs)[:2000]}
