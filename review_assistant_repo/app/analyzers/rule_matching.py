from __future__ import annotations

from typing import Any


def _patterns(spec: dict[str, Any], key: str) -> list[str]:
    return [str(p).lower() for p in spec.get(key, []) if str(p).strip()]


def _rule_specs(rule: dict[str, Any]) -> list[dict[str, Any]]:
    acceptable = rule.get("acceptable_patterns")
    specs = [item for item in acceptable if isinstance(item, dict)] if isinstance(acceptable, list) else []
    return specs or [rule]


def _matches(text: str, spec: dict[str, Any]) -> bool:
    patterns_any = _patterns(spec, "patterns_any")
    patterns_all = _patterns(spec, "patterns_all")
    any_ok = True if not patterns_any else any(p in text for p in patterns_any)
    all_ok = True if not patterns_all else all(p in text for p in patterns_all)
    return any_ok and all_ok


def _anchor_patterns(spec: dict[str, Any]) -> list[str]:
    return _patterns(spec, "patterns_any") or _patterns(spec, "patterns_all")


def find_rule_match(artifacts: list[dict[str, Any]], criterion: dict[str, Any]) -> dict[str, Any] | None:
    rule = criterion.get("rule", {})
    artifact_types = set(rule.get("artifact_types", []))
    match_scope = str(rule.get("match_scope") or "artifact")
    min_len = rule.get("min_normalized_length")
    candidates = [
        artifact
        for artifact in artifacts
        if not artifact_types or artifact["artifact_type"] in artifact_types
        if not (artifact.get("metadata_json") or artifact.get("metadata") or {}).get("is_practicum_instruction")
    ]

    for spec in _rule_specs(rule):
        if match_scope == "project":
            chunks = []
            for artifact in candidates:
                norm = artifact.get("normalized_text") or ""
                if min_len is not None and len(norm) < int(min_len):
                    continue
                chunks.append((artifact, norm))

            text = "\n\n".join(norm for _, norm in chunks).lower()
            if chunks and _matches(text, spec):
                anchor_patterns = _anchor_patterns(spec)
                anchor = next(
                    (
                        artifact
                        for artifact, norm in chunks
                        if any(p in norm.lower() for p in anchor_patterns)
                    ),
                    chunks[0][0],
                )
                return {
                    "anchor_position_idx": anchor.get("position_idx"),
                    "evidence": [{"excerpt": (anchor.get("normalized_text") or "")[:250]}],
                }

        for artifact in candidates:
            norm = artifact.get("normalized_text") or ""
            if min_len is not None and len(norm) < int(min_len):
                continue
            if _matches(norm.lower(), spec):
                return {
                    "anchor_position_idx": artifact.get("position_idx"),
                    "evidence": [{"excerpt": (artifact.get("normalized_text") or "")[:250]}],
                }

    return None
