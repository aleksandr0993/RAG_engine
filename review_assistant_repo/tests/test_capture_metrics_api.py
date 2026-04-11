def test_debug_capture_metrics_endpoint(client):
    r = client.get("/api/v1/debug/capture_metrics")
    assert r.status_code == 200
    data = r.json()
    assert "submitted" in data
    assert "completed_ok" in data
    assert "pool_timeouts" in data
