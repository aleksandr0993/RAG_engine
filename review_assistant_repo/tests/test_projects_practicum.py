from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path


def test_list_projects_filter_practicum_input_channel(client):
    sql_path = Path("examples/sample_query.sql")
    with sql_path.open("rb") as f:
        r1 = client.post(
            "/api/v1/projects/upload",
            files={"file": ("a.sql", f, "application/sql")},
            data={"practicum_input_channel": "revisor"},
        )
    assert r1.status_code == 200
    with sql_path.open("rb") as f:
        r2 = client.post(
            "/api/v1/projects/upload",
            files={"file": ("b.sql", f, "application/sql")},
        )
    assert r2.status_code == 200

    rev_only = client.get("/api/v1/projects", params={"practicum_input_channel": "revisor", "limit": 50})
    assert rev_only.status_code == 200
    rev_ids = {p["id"] for p in rev_only.json()}
    assert r1.json()["project_id"] in rev_ids
    assert r2.json()["project_id"] not in rev_ids

    allp = client.get("/api/v1/projects", params={"limit": 50})
    assert len(allp.json()) >= 2


def test_list_projects_cursor_pagination(client):
    sql_path = Path("examples/sample_query.sql")
    ids: list[str] = []
    for i in range(5):
        with sql_path.open("rb") as f:
            up = client.post("/api/v1/projects/upload", files={"file": (f"k{i}.sql", f, "application/sql")})
        assert up.status_code == 200
        ids.append(up.json()["project_id"])

    r1 = client.get("/api/v1/projects", params={"source_type": "sql", "limit": 2})
    assert r1.status_code == 200
    assert r1.headers.get("x-next-cursor")
    p1 = {p["id"] for p in r1.json()}
    assert len(p1) == 2

    r2 = client.get(
        "/api/v1/projects",
        params={"source_type": "sql", "limit": 2, "cursor": r1.headers["x-next-cursor"]},
    )
    assert r2.status_code == 200
    p2 = {p["id"] for p in r2.json()}
    assert len(p2) == 2
    assert p1.isdisjoint(p2)

    r3 = client.get(
        "/api/v1/projects",
        params={"source_type": "sql", "limit": 2, "cursor": r2.headers["x-next-cursor"]},
    )
    assert r3.status_code == 200
    p3 = {p["id"] for p in r3.json()}
    assert len(p3) == 1
    assert p1 | p2 | p3 == set(ids)
    assert r3.headers.get("x-next-cursor") is None


def test_list_projects_cursor_with_offset_rejected(client):
    payload = json.dumps(
        {"t": datetime.now(UTC).isoformat(), "i": "00000000-0000-0000-0000-000000000001"},
        separators=(",", ":"),
    )
    cur = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    bad = client.get("/api/v1/projects", params={"limit": 5, "offset": 1, "cursor": cur})
    assert bad.status_code == 400


def test_list_projects_invalid_cursor(client):
    r = client.get("/api/v1/projects", params={"cursor": "not-a-valid-cursor"})
    assert r.status_code == 400


def test_list_projects_x_total_count_header(client):
    sql_path = Path("examples/sample_query.sql")
    for name in ("c1.sql", "c2.sql", "c3.sql"):
        with sql_path.open("rb") as f:
            up = client.post("/api/v1/projects/upload", files={"file": (name, f, "application/sql")})
        assert up.status_code == 200
    r = client.get("/api/v1/projects", params={"source_type": "sql", "limit": 2, "offset": 0})
    assert r.status_code == 200
    assert len(r.json()) == 2
    assert r.headers.get("x-total-count") == "3"
    assert r.headers.get("x-total-count-truncated") is None

    with sql_path.open("rb") as f:
        client.post(
            "/api/v1/projects/upload",
            files={"file": ("rev.sql", f, "application/sql")},
            data={"practicum_input_channel": "revisor"},
        )
    with sql_path.open("rb") as f:
        client.post("/api/v1/projects/upload", files={"file": ("plain.sql", f, "application/sql")})
    rv = client.get("/api/v1/projects", params={"practicum_input_channel": "revisor", "limit": 50})
    assert rv.status_code == 200
    assert rv.headers.get("x-total-count") == "1"


def test_list_projects_include_total_false_skips_count_headers(client):
    sql_path = Path("examples/sample_query.sql")
    with sql_path.open("rb") as f:
        client.post("/api/v1/projects/upload", files={"file": ("only.sql", f, "application/sql")})
    r = client.get("/api/v1/projects", params={"limit": 10, "include_total": "false"})
    assert r.status_code == 200
    assert r.headers.get("x-total-count") is None
    assert r.headers.get("x-total-count-truncated") is None


def test_list_projects_offset_pagination(client):
    sql_path = Path("examples/sample_query.sql")
    ids: list[str] = []
    for name in ("p1.sql", "p2.sql", "p3.sql"):
        with sql_path.open("rb") as f:
            up = client.post("/api/v1/projects/upload", files={"file": (name, f, "application/sql")})
        assert up.status_code == 200
        ids.append(up.json()["project_id"])

    r0 = client.get("/api/v1/projects", params={"source_type": "sql", "limit": 1, "offset": 0})
    r1 = client.get("/api/v1/projects", params={"source_type": "sql", "limit": 1, "offset": 1})
    r2 = client.get("/api/v1/projects", params={"source_type": "sql", "limit": 1, "offset": 2})
    assert r0.status_code == r1.status_code == r2.status_code == 200
    assert {r0.json()[0]["id"], r1.json()[0]["id"], r2.json()[0]["id"]} == set(ids)


def test_debug_practicum_stats_shape(client):
    r = client.get("/api/v1/debug/practicum_stats", params={"limit": 10})
    assert r.status_code == 200
    data = r.json()
    assert data["sample_size"] >= 0
    assert data.get("filters") == {
        "source_type": None,
        "status": None,
        "practicum_input_channel": None,
    }
    assert "by_practicum_input_channel" in data
    assert "by_revisor_html_confidence" in data
    assert "by_source_type" in data
    assert "by_project_status" in data
    assert "by_final_verdict" in data
    assert "practicum_revisor_html_detected_count" in data

    filt = client.get(
        "/api/v1/debug/practicum_stats",
        params={"limit": 50, "source_type": "sql", "status": "uploaded"},
    )
    assert filt.status_code == 200
    fd = filt.json()
    assert fd["filters"] == {
        "source_type": "sql",
        "status": "uploaded",
        "practicum_input_channel": None,
    }
    bad = client.get("/api/v1/debug/practicum_stats", params={"source_type": "cobol"})
    assert bad.status_code == 400

    sql_path = Path("examples/sample_query.sql")
    with sql_path.open("rb") as f:
        client.post(
            "/api/v1/projects/upload",
            files={"file": ("rev.sql", f, "application/sql")},
            data={"practicum_input_channel": "revisor"},
        )
    with sql_path.open("rb") as f:
        client.post("/api/v1/projects/upload", files={"file": ("plain.sql", f, "application/sql")})
    ch = client.get("/api/v1/debug/practicum_stats", params={"limit": 50, "practicum_input_channel": "revisor"})
    assert ch.status_code == 200
    cd = ch.json()
    assert cd["filters"]["practicum_input_channel"] == "revisor"
    assert cd["sample_size"] >= 1
    assert cd["by_practicum_input_channel"] == {"revisor": cd["sample_size"]}


def test_list_projects_filter_source_type_and_status(client):
    sql_path = Path("examples/sample_query.sql")
    with sql_path.open("rb") as f:
        up = client.post("/api/v1/projects/upload", files={"file": ("f.sql", f, "application/sql")})
    assert up.status_code == 200
    pid = up.json()["project_id"]
    client.post(f"/api/v1/projects/{pid}/review")

    sql_only = client.get("/api/v1/projects", params={"source_type": "sql", "limit": 50})
    assert sql_only.status_code == 200
    assert all(p["source_type"] == "sql" for p in sql_only.json())

    done_only = client.get("/api/v1/projects", params={"status": "done", "limit": 50})
    assert done_only.status_code == 200
    assert all(p["status"] == "done" for p in done_only.json())

    bad = client.get("/api/v1/projects", params={"source_type": "cobol"})
    assert bad.status_code == 400
    bad2 = client.get("/api/v1/projects", params={"status": "cooking"})
    assert bad2.status_code == 400
