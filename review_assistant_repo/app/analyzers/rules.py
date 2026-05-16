from __future__ import annotations

from app.analyzers.semantic import SemanticAnalyzer
from app.analyzers.visual import VisualAnalyzer


class RuleEngine:
    def __init__(self):
        self.semantic = SemanticAnalyzer()
        self.visual = VisualAnalyzer()

    def run(self, artifacts: list[dict], criteria: list[dict]) -> list[dict]:
        results = []

        for criterion in criteria:
            mode = criterion.get("detection_mode", "rule")

            if mode == "rule":
                results.append(self._run_rule(artifacts, criterion))
            elif mode == "hybrid":
                task = criterion.get("hybrid_check", {}).get("task")
                results.append(self.semantic.check(task, artifacts, criterion))
            elif mode == "visual":
                task = criterion.get("visual_check", {}).get("task")
                results.append(self.visual.check(task, artifacts, criterion))
            else:
                results.append(
                    {
                        "status": "unknown",
                        "confidence": 0.2,
                        "anchor_position_idx": None,
                        "evidence": [],
                        "metadata": {"reason": f"unsupported mode {mode}", "source_stage": "rule"},
                    }
                )

        return results

    def _run_rule(self, artifacts: list[dict], criterion: dict) -> dict:
        rule = criterion.get("rule", {})
        artifact_types = set(rule.get("artifact_types", []))
        patterns_any = [p.lower() for p in rule.get("patterns_any", [])]
        patterns_all = [p.lower() for p in rule.get("patterns_all", [])]
        match_scope = str(rule.get("match_scope") or "artifact")

        min_len = rule.get("min_normalized_length")
        candidates = [
            artifact
            for artifact in artifacts
            if not artifact_types or artifact["artifact_type"] in artifact_types
            if not (artifact.get("metadata_json") or artifact.get("metadata") or {}).get("is_practicum_instruction")
        ]

        if match_scope == "project":
            chunks = []
            for artifact in candidates:
                norm = artifact.get("normalized_text") or ""
                if min_len is not None and len(norm) < int(min_len):
                    continue
                chunks.append((artifact, norm))

            text = "\n\n".join(norm for _, norm in chunks).lower()
            any_ok = True if not patterns_any else any(p in text for p in patterns_any)
            all_ok = True if not patterns_all else all(p in text for p in patterns_all)
            if chunks and any_ok and all_ok:
                anchor_patterns = patterns_any or patterns_all
                anchor = next(
                    (
                        artifact
                        for artifact, norm in chunks
                        if any(p in norm.lower() for p in anchor_patterns)
                    ),
                    chunks[0][0],
                )
                return {
                    "status": "pass",
                    "confidence": 0.98,
                    "anchor_position_idx": anchor.get("position_idx"),
                    "evidence": [{"excerpt": (anchor.get("normalized_text") or "")[:250]}],
                    "metadata": {"mode": "rule", "source_stage": "rule", "match_scope": "project"},
                }

        for artifact in candidates:
            norm = artifact.get("normalized_text") or ""
            if min_len is not None and len(norm) < int(min_len):
                continue
            text = norm.lower()
            any_ok = True if not patterns_any else any(p in text for p in patterns_any)
            all_ok = True if not patterns_all else all(p in text for p in patterns_all)
            if any_ok and all_ok:
                return {
                    "status": "pass",
                    "confidence": 0.98,
                    "anchor_position_idx": artifact.get("position_idx"),
                    "evidence": [{"excerpt": (artifact.get("normalized_text") or "")[:250]}],
                    "metadata": {"mode": "rule", "source_stage": "rule"},
                }

        return {
            "status": "fail" if criterion.get("severity") == "required" else "warn",
            "confidence": 0.96,
            "anchor_position_idx": None,
            "evidence": [],
            "metadata": {"mode": "rule", "source_stage": "rule"},
        }
