from tests.conftest import PAST_CALL_ID, FUTURE_CALL_ID


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_extensive_returns_past_calls(client):
    # Virtual range 2026-03-01 to 2026-05-01 → historical 2024-02-29 to 2024-04-30
    # Hits 2024/04.tar.xz which contains PAST_CALL_ID
    resp = client.post("/v2/calls/extensive", json={
        "filter": {"fromDateTime": "2026-03-01T00:00:00Z", "toDateTime": "2026-05-01T00:00:00Z"}
    })
    assert resp.status_code == 200
    ids = [c["metaData"]["id"] for c in resp.json()["calls"]]
    assert PAST_CALL_ID in ids


def test_extensive_excludes_future_calls(client):
    # Range covers both 04 and 06 archives; FUTURE_CALL_ID gated out
    resp = client.post("/v2/calls/extensive", json={
        "filter": {"fromDateTime": "2026-03-01T00:00:00Z", "toDateTime": "2026-08-01T00:00:00Z"}
    })
    assert resp.status_code == 200
    ids = [c["metaData"]["id"] for c in resp.json()["calls"]]
    assert FUTURE_CALL_ID not in ids


def test_extensive_remaps_timestamps(client):
    resp = client.post("/v2/calls/extensive", json={
        "filter": {"fromDateTime": "2026-03-01T00:00:00Z", "toDateTime": "2026-05-01T00:00:00Z"}
    })
    assert resp.status_code == 200
    calls = resp.json()["calls"]
    past = next(c for c in calls if c["metaData"]["id"] == PAST_CALL_ID)
    # Original started 2024-04-01, after +735d should be in 2026
    assert past["metaData"]["started"].startswith("2026-")


def test_extensive_returns_total_records(client):
    resp = client.post("/v2/calls/extensive", json={
        "filter": {"fromDateTime": "2026-03-01T00:00:00Z", "toDateTime": "2026-05-01T00:00:00Z"}
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["records"]["totalRecords"] == len(data["calls"])


def test_extensive_future_range_returns_400(client):
    # hist_from = 2030-01-01 - 735d ≈ 2027-12-27 > utcnow → 400
    resp = client.post("/v2/calls/extensive", json={
        "filter": {"fromDateTime": "2030-01-01T00:00:00Z", "toDateTime": "2030-02-01T00:00:00Z"}
    })
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "Invalid date range"
    assert "future" in body["message"].lower()


def test_extensive_400_includes_offset_details(client):
    from datetime import datetime
    resp = client.post("/v2/calls/extensive", json={
        "filter": {"fromDateTime": "2030-01-01T00:00:00Z", "toDateTime": "2030-02-01T00:00:00Z"}
    })
    assert resp.status_code == 400
    details = resp.json()["details"]
    archive_start = datetime.fromisoformat("2024-05-01")
    virtual_start = datetime.fromisoformat("2026-05-06")
    expected_days = (virtual_start - archive_start).days
    assert f"{expected_days} days" == details["offset"]


def test_transcript_returns_past_call(client):
    resp = client.post("/v2/calls/transcript", json={
        "filter": {"callIds": [PAST_CALL_ID]}
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["callTranscripts"]) == 1
    ct = data["callTranscripts"][0]
    assert ct["callId"] == PAST_CALL_ID
    assert len(ct["transcript"]) == 2
    assert ct["transcript"][0]["text"] == "Hello"


def test_transcript_future_call_returns_404(client):
    resp = client.post("/v2/calls/transcript", json={
        "filter": {"callIds": [FUTURE_CALL_ID]}
    })
    assert resp.status_code == 404
    assert "not occurred yet" in resp.json()["message"]


def test_transcript_unknown_call_returns_404(client):
    resp = client.post("/v2/calls/transcript", json={
        "filter": {"callIds": ["nonexistent-id"]}
    })
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"] == "Call not found"


def test_extensive_invalid_dates_returns_400(client):
    resp = client.post("/v2/calls/extensive", json={
        "filter": {"fromDateTime": "not-a-date", "toDateTime": "also-not-a-date"}
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "Invalid date range"
