from pathlib import Path

from app.parsers.notebook import NotebookParser


def test_notebook_parser_assigns_sections(tmp_path):
    nb_path = Path("examples/sample_notebook.ipynb")
    parser = NotebookParser()
    artifacts, _ = parser.parse(str(nb_path))
    sections = [a.section_name for a in artifacts if a.artifact_type in ("markdown_cell", "code_cell")]
    assert any(s for s in sections if s)
