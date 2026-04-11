from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class NotebookExecutionResult:
    ok: bool
    output_path: str | None
    duration_ms: float
    error_type: str | None = None
    error_message: str | None = None
    traceback: str | None = None
    skipped: bool = False
    skip_reason: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "notebook_execution_ok": self.ok,
            "notebook_execution_skipped": self.skipped,
            "notebook_execution_skip_reason": self.skip_reason,
            "notebook_executed_path": self.output_path,
            "notebook_execution_duration_ms": round(self.duration_ms, 2),
            "notebook_execution_error_type": self.error_type,
            "notebook_execution_error_message": self.error_message,
            "notebook_execution_traceback": self.traceback,
        }


def execute_notebook_to_file(
    source_path: str,
    output_path: str,
    cwd: str | Path | None = None,
    timeout_sec: float = 120.0,
) -> NotebookExecutionResult:
    """
    Execute all code cells with nbclient and write the notebook with outputs to output_path.
    """
    import time

    t0 = time.perf_counter()
    cwd_path = Path(cwd) if cwd else Path(source_path).parent

    try:
        import nbformat
        from nbclient import NotebookClient
    except ImportError as exc:
        dur = (time.perf_counter() - t0) * 1000
        logger.warning("Notebook execution unavailable: %s", exc)
        return NotebookExecutionResult(
            ok=False,
            output_path=None,
            duration_ms=dur,
            skipped=True,
            skip_reason=f"import_error: {exc}",
        )

    try:
        nb = nbformat.read(source_path, as_version=4)
    except Exception as exc:
        dur = (time.perf_counter() - t0) * 1000
        return NotebookExecutionResult(
            ok=False,
            output_path=None,
            duration_ms=dur,
            error_type=type(exc).__name__,
            error_message=str(exc),
            traceback=traceback.format_exc(),
        )

    try:
        client = NotebookClient(
            nb,
            timeout=int(timeout_sec),
            kernel_name="python3",
            resources={"metadata": {"path": str(cwd_path)}},
        )
        client.execute()
    except Exception as exc:
        dur = (time.perf_counter() - t0) * 1000
        err_name = type(exc).__name__
        msg = str(exc)
        if err_name == "CellExecutionError" or "CellExecutionError" in str(type(exc)):
            err_name = "CellExecutionError"
        return NotebookExecutionResult(
            ok=False,
            output_path=None,
            duration_ms=dur,
            error_type=err_name,
            error_message=msg,
            traceback=traceback.format_exc(),
        )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        nbformat.write(nb, str(out))
    except Exception as exc:
        dur = (time.perf_counter() - t0) * 1000
        return NotebookExecutionResult(
            ok=False,
            output_path=None,
            duration_ms=dur,
            error_type=type(exc).__name__,
            error_message=str(exc),
            traceback=traceback.format_exc(),
        )

    dur = (time.perf_counter() - t0) * 1000
    return NotebookExecutionResult(ok=True, output_path=str(out), duration_ms=dur)
