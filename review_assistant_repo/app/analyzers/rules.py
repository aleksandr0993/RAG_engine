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

        min_len = rule.get("min_normalized_length")

        for artifact in artifacts:
            if artifact_types and artifact["artifact_type"] not in artifact_types:
                continue
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
