def build_notebook_comment_html(title: str, body: str, level: str = "warning") -> str:
    level_map = {
        "success": "alert-success",
        "warning": "alert-warning",
        "danger": "alert-danger",
    }
    alert_class = level_map.get(level, "alert-warning")
    return f"""<div class="alert {alert_class}">
<h2> Комментарий ревьюера <a class="tocSkip"> </h2>

<b>{title}</b>

{body}
</div>"""
