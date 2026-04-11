from __future__ import annotations


def build_review_markdown(
    project_type: str,
    positives: list[str],
    required_fixes: list[str],
    extra_recommendations: list[str],
    verdict_label: str,
    sql_fix_section: str | None = None,
    sql_after_patch_note: str | None = None,
) -> str:
    lines = []

    if project_type == "sql":
        lines.append("Вот подробное ревью по задаче")
    else:
        lines.append("Вот подробное ревью по проекту")

    lines.append("")
    lines.append("## ✅ Что сделано хорошо")
    if positives:
        lines.extend([f"- {item}" for item in positives])
    else:
        lines.append("- Есть базовая структура решения.")

    if required_fixes:
        lines.append("")
        lines.append("## ❌ Корректировка решения")
        lines.extend([f"- {item}" for item in required_fixes])

    if extra_recommendations:
        lines.append("")
        lines.append("## 💡 Дополнительная рекомендация")
        lines.extend([f"- {item}" for item in extra_recommendations])

    if project_type == "sql":
        lines.append("")
        lines.append("## 🔧 Решение")
        if sql_fix_section:
            lines.append(sql_fix_section)
        else:
            lines.append(
                "- Автоматически переписанный SQL здесь намеренно не приводится: "
                "при неоднозначной логике метрик и JOIN нужен ручной разбор. "
                "Ниже — безопасные направления правок без выдуманного кода."
            )
            lines.append(
                "- Проверь знаменатель делений через `NULLIF(column, 0)` или аналог."
            )
            lines.append(
                "- Убедись, что `GROUP BY` согласован с неагрегированными столбцами в `SELECT`."
            )
            lines.append(
                "- Для цепочек `LEFT JOIN` проверь кардинальность ключей и при необходимости агрегируй в подзапросе."
            )
        lines.append("")
        lines.append("## 🟢 Версия после правки")
        lines.append(
            sql_after_patch_note
            or "- После внесения правок прогони запрос на тестовой выборке и приложи финальный SQL в репозиторий."
        )

    lines.append("")
    lines.append("## 📌 Вывод")
    lines.append(f"- Итог: **{verdict_label}**")

    return "\n".join(lines)


def build_iteration_fix_markdown_section(summary: dict) -> str | None:
    """
    Markdown block appended after the main review (before/after LLM polish handled by caller).
    """
    if not summary:
        return None
    status = summary.get("status")
    if status in (None, "no_parent_link"):
        return None

    lines: list[str] = [
        "## 🔄 Проверка исправлений прошлой итерации",
        "",
    ]

    if status == "no_parent_review_snapshot":
        lines.append(f"- {summary.get('message', 'Нет снимка прошлого ревью.')}")
        return "\n".join(lines)

    if status == "nothing_to_verify":
        lines.append(f"- {summary.get('message', 'Нечего сверять.')}")
        return "\n".join(lines)

    counts = summary.get("counts") or {}
    lines.append(
        f"- Всего замечаний прошлой итерации (не pass): **{counts.get('total_previous_issues', 0)}**; "
        f"исправлено: **{counts.get('fixed', 0)}**, "
        f"частично: **{counts.get('partially_fixed', 0)}**, "
        f"не исправлено: **{counts.get('not_fixed', 0)}**, "
        f"нельзя подтвердить запуском: **{counts.get('cannot_verify', 0)}**."
    )
    lines.append("")

    for item in summary.get("items") or []:
        code = item.get("criterion_code", "?")
        res = item.get("resolution_status", "?")
        cur = item.get("current_status")
        parent_st = item.get("parent_status")
        parts = [f"было: {parent_st}"]
        if cur is not None:
            parts.append(f"сейчас: {cur}")
        suffix = f" ({', '.join(parts)})"
        lines.append(f"- `{code}` — **{res}**{suffix}")

    return "\n".join(lines)
