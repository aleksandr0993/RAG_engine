from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp


@dataclass
class SqlAstIssue:
    problem_type: str
    offending_sql_excerpt: str
    recommended_fix_hint: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SqlAstReport:
    issues: list[SqlAstIssue] = field(default_factory=list)
    parse_error: bool = False
    has_cte: bool = False
    join_count: int = 0
    left_join_count: int = 0
    group_by_exprs: list[str] = field(default_factory=list)


def _excerpt(node: exp.Expression | None, sql: str, max_len: int = 220) -> str:
    if node is None:
        return sql[:max_len]
    try:
        frag = node.sql()
    except Exception:
        frag = sql
    return frag.strip()[:max_len]


def analyze_sql_query(sql: str) -> SqlAstReport:
    """AST-level scan for common analytic-SQL risks (explainable, heuristic)."""
    report = SqlAstReport()
    try:
        parsed = sqlglot.parse_one(sql)
    except Exception:
        report.parse_error = True
        report.issues.append(
            SqlAstIssue(
                problem_type="parse_error",
                offending_sql_excerpt=sql[:220],
                recommended_fix_hint="Проверь синтаксис SQL; при сложной логике нужен ручной разбор.",
            )
        )
        return report

    report.has_cte = parsed.find(exp.With) is not None

    joins = list(parsed.find_all(exp.Join))
    report.join_count = len(joins)
    report.left_join_count = sum(1 for j in joins if str(j.args.get("side") or "").upper() == "LEFT")

    for node in parsed.find_all(exp.Div):
        if isinstance(node.expression, exp.Nullif):
            continue
        report.issues.append(
            SqlAstIssue(
                problem_type="division_without_nullif",
                offending_sql_excerpt=_excerpt(node, sql),
                recommended_fix_hint="Оберни знаменатель в NULLIF(denominator, 0) или используй безопасное деление, принятое в вашей СУБД.",
                metadata={"ast_node": "Div"},
            )
        )

    for node in parsed.find_all(exp.Count):
        inner = node.this
        if isinstance(inner, exp.Distinct):
            args = inner.expressions
            if any(isinstance(a, exp.Star) for a in args):
                report.issues.append(
                    SqlAstIssue(
                        problem_type="count_logic_mismatch",
                        offending_sql_excerpt=_excerpt(node, sql),
                        recommended_fix_hint="COUNT(DISTINCT *) обычно некорректен; укажи конкретный столбец в DISTINCT.",
                    )
                )

    if report.left_join_count >= 2 and report.join_count >= 2:
        report.issues.append(
            SqlAstIssue(
                problem_type="risky_left_join",
                offending_sql_excerpt=sql[:220],
                recommended_fix_hint="Цепочка LEFT JOIN может размножать строки; проверь ключи и агрегируй в подзапросе/CTE при необходимости.",
                metadata={"left_join_count": report.left_join_count, "join_count": report.join_count},
            )
        )

    group = parsed.args.get("group")
    if isinstance(group, exp.Group):
        report.group_by_exprs = [e.sql() for e in group.expressions]

    selects = list(parsed.find_all(exp.Select))
    if len(selects) == 1 and report.group_by_exprs:
        sel = selects[0]
        gb_set = {g.lower().strip() for g in report.group_by_exprs}
        naked_cols: list[str] = []
        for proj in sel.expressions:
            if isinstance(proj, exp.Column):
                naked_cols.append(proj.sql())
            elif isinstance(proj, exp.Alias) and isinstance(proj.this, exp.Column):
                naked_cols.append(proj.this.sql())
        for col in naked_cols:
            if col.lower() not in gb_set and col.lower().split(".")[-1] not in gb_set:
                report.issues.append(
                    SqlAstIssue(
                        problem_type="suspicious_group_by",
                        offending_sql_excerpt=_excerpt(sel, sql),
                        recommended_fix_hint="Столбец в SELECT не покрыт GROUP BY; возможна ошибка SQL или нужен ANY_VALUE/MIN/MAX — требуется ручная проверка.",
                        metadata={"column": col},
                    )
                )
                break

    agg_aliases: dict[str, int] = {}
    for sel in selects:
        for proj in sel.expressions:
            if isinstance(proj, exp.Alias):
                name = proj.alias
                inner = proj.this
                if isinstance(inner, (exp.AggFunc, exp.Count, exp.AnonymousAggFunc)):
                    agg_aliases[name] = agg_aliases.get(name, 0) + 1
    dup = [k for k, v in agg_aliases.items() if v > 1]
    if dup:
        report.issues.append(
            SqlAstIssue(
                problem_type="ambiguous_metric_calculation",
                offending_sql_excerpt=sql[:220],
                recommended_fix_hint="Одинаковые алиасы агрегатов встречаются несколько раз; переименуй метрики и проверь, что они считают разное.",
                metadata={"duplicate_aliases": dup[:5]},
            )
        )

    return report
