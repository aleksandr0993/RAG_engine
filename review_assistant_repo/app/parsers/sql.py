from __future__ import annotations

import re

import sqlglot

from app.analyzers.sql_ast import analyze_sql_query
from app.parsers.base import ParsedArtifact


class SQLParser:
    def parse(self, sql_path: str) -> tuple[list[ParsedArtifact], dict]:
        sql_text = open(sql_path, encoding="utf-8").read()
        chunks = [part.strip() for part in re.split(r";\s*(?:\n|$)", sql_text) if part.strip()]
        artifacts: list[ParsedArtifact] = []

        for idx, query in enumerate(chunks):
            metadata = {
                "has_division": "/" in query,
                "has_nullif": "nullif(" in query.lower(),
                "has_join": " join " in query.lower(),
            }
            try:
                parsed = sqlglot.parse_one(query)
                normalized = parsed.sql(pretty=True)
                metadata["parse_error"] = False
            except Exception:
                normalized = query
                metadata["parse_error"] = True

            ast = analyze_sql_query(query)
            metadata["ast_report"] = {
                "issues": [
                    {
                        "problem_type": i.problem_type,
                        "offending_sql_excerpt": i.offending_sql_excerpt,
                        "recommended_fix_hint": i.recommended_fix_hint,
                        "metadata": i.metadata,
                    }
                    for i in ast.issues
                ],
                "parse_error": ast.parse_error,
                "join_count": ast.join_count,
                "left_join_count": ast.left_join_count,
                "group_by_exprs": ast.group_by_exprs,
            }

            artifacts.append(
                ParsedArtifact(
                    artifact_type="sql_query",
                    position_idx=idx,
                    raw_text=query,
                    normalized_text=normalized,
                    metadata=metadata,
                )
            )

        return artifacts, {"query_count": len(artifacts)}
