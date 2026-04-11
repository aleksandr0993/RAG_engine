"""Optional retrieval of past review examples (local stub by default)."""

from app.retrieval.comment_catalog import build_catalog, catalog_to_markdown, write_catalog_json
from app.retrieval.interface import RetrievalBackend, ReviewExample
from app.retrieval.local_examples import LocalFileRetrievalBackend, get_retrieval_backend
from app.retrieval.notebook_training import extract_rows_from_ipynb, merge_write_jsonl

__all__ = [
    "ReviewExample",
    "RetrievalBackend",
    "LocalFileRetrievalBackend",
    "get_retrieval_backend",
    "extract_rows_from_ipynb",
    "merge_write_jsonl",
    "build_catalog",
    "catalog_to_markdown",
    "write_catalog_json",
]
