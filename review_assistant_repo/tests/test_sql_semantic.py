from app.analyzers.sql_ast import analyze_sql_query
from app.analyzers.sql_semantic import run_sql_semantic


def test_ast_detects_unsafe_division():
    r = analyze_sql_query("SELECT a / b AS x FROM t")
    types = {i.problem_type for i in r.issues}
    assert "division_without_nullif" in types


def test_sql_semantic_division_task():
    artifacts = [
        {
            "artifact_type": "sql_query",
            "position_idx": 0,
            "raw_text": "SELECT 1/0",
            "normalized_text": "SELECT 1/0",
            "metadata_json": {},
        }
    ]
    crit = {"severity": "required", "code": "division_without_nullif"}
    out = run_sql_semantic("division_without_nullif", artifacts, crit, llm=None)
    assert out["status"] == "fail"
