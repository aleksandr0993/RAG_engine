from __future__ import annotations

from pathlib import Path

import nbformat


class NotebookCommentInserter:
    def insert_comments(self, notebook: dict, insertions: list[dict]) -> dict:
        if not insertions:
            return notebook

        insertions = sorted(insertions, key=lambda item: item["anchor_position_idx"])
        offset = 0
        cells = notebook["cells"]

        for item in insertions:
            anchor_idx = max(0, item["anchor_position_idx"]) + offset
            comment_cell = nbformat.v4.new_markdown_cell(item["comment_html"])
            cells.insert(anchor_idx + 1, comment_cell)
            offset += 1

        notebook["cells"] = cells
        return notebook

    def save(self, notebook: dict, output_path: str) -> str:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        nbformat.write(notebook, output)
        return str(output)
