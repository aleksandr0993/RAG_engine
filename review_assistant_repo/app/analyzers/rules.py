from __future__ import annotations

from app.analyzers.rule_matching import find_rule_match
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
        match = find_rule_match(artifacts, criterion)
        if match is not None:
            meta = {"mode": "rule", "source_stage": "rule"}
            if str((criterion.get("rule") or {}).get("match_scope") or "artifact") == "project":
                meta["match_scope"] = "project"
            return {
                "status": "pass",
                "confidence": 0.98,
                "anchor_position_idx": match.get("anchor_position_idx"),
                "evidence": match.get("evidence") or [],
                "metadata": meta,
            }

        return {
            "status": "fail" if criterion.get("severity") == "required" else "warn",
            "confidence": 0.96,
            "anchor_position_idx": None,
            "evidence": [],
            "metadata": {"mode": "rule", "source_stage": "rule"},
        }
