from __future__ import annotations

from app.analyzers.rule_matching import find_rule_match, find_rule_matches
from app.analyzers.rules import RuleEngine


def test_rule_match_prefers_best_global_evidence_over_first_cell():
    artifacts = [
        {
            "artifact_type": "markdown_cell",
            "position_idx": 1,
            "normalized_text": "Нужно выделить топ-7 platform через value_counts head(7)",
            "metadata_json": {},
        },
        {
            "artifact_type": "code_cell",
            "position_idx": 20,
            "normalized_text": "top_platforms = df_actual['platform'].value_counts().head(7)\ndisplay(top_platforms)",
            "metadata_json": {"has_outputs": True},
        },
    ]
    criterion = {
        "code": "games_top7_platforms",
        "order_policy": "anywhere",
        "rule": {
            "artifact_types": ["markdown_cell", "code_cell"],
            "patterns_any": ["value_counts"],
            "patterns_all": ["platform", "head(7"],
        },
    }

    matches = find_rule_matches(artifacts, criterion)
    best = find_rule_match(artifacts, criterion)

    assert len(matches) == 2
    assert best is not None
    assert best["anchor_position_idx"] == 20
    assert best["match_count"] == 2


def test_rule_engine_marks_anywhere_order_policy_metadata():
    artifacts = [
        {
            "artifact_type": "code_cell",
            "position_idx": 7,
            "normalized_text": "df_actual = df[df['year_of_release'].between(2000, 2013)]",
            "metadata_json": {},
        }
    ]
    criterion = {
        "code": "games_actual_period_filter",
        "severity": "required",
        "order_policy": "anywhere",
        "detection_mode": "rule",
        "rule": {
            "artifact_types": ["code_cell"],
            "patterns_all": ["2000", "2013", "year"],
        },
    }

    result = RuleEngine().run(artifacts, [criterion])[0]

    assert result["status"] == "pass"
    assert result["anchor_position_idx"] == 7
    assert result["metadata"]["order_policy"] == "anywhere"
    assert result["metadata"]["global_rule_match"] is True
