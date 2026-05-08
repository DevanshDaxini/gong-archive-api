from datetime import datetime, timedelta, timezone
import pytest
from unittest.mock import patch


def test_remap_datetime_shifts_by_offset():
    from src.time_machine import remap_datetime
    result = remap_datetime("2024-05-03T10:00:00Z", 730)
    dt = datetime.strptime(result, "%Y-%m-%dT%H:%M:%SZ")
    expected = datetime(2024, 5, 3, 10, 0, 0) + timedelta(days=730)
    assert dt == expected


def test_remap_datetime_preserves_time_of_day():
    from src.time_machine import remap_datetime
    result = remap_datetime("2024-05-03T14:30:45Z", 730)
    assert "14:30:45" in result


def test_remap_datetime_returns_original_on_parse_error():
    from src.time_machine import remap_datetime
    result = remap_datetime("not-a-date", 730)
    assert result == "not-a-date"


def test_should_exclude_future_call(monkeypatch):
    # ended 2024-06-01 + 730d = 2026-05-31; mocked now = 2026-05-08 → exclude
    from src.time_machine import should_exclude_call
    import src.time_machine as tm
    monkeypatch.setattr(tm, "_utcnow", lambda: datetime(2026, 5, 8))
    record = {"metaData": {"id": "f", "started": "2024-06-01T10:00:00Z",
                           "ended": "2024-06-01T11:00:00Z", "duration": 3600}}
    assert should_exclude_call(record, 730) is True


def test_should_include_past_call(monkeypatch):
    # ended 2024-04-01 + 730d = 2026-03-31; mocked now = 2026-05-08 → include
    from src.time_machine import should_exclude_call
    import src.time_machine as tm
    monkeypatch.setattr(tm, "_utcnow", lambda: datetime(2026, 5, 8))
    record = {"metaData": {"id": "p", "started": "2024-04-01T10:00:00Z",
                           "ended": "2024-04-01T11:00:00Z", "duration": 3600}}
    assert should_exclude_call(record, 730) is False


def test_should_exclude_uses_duration_when_no_ended(monkeypatch):
    # started 2024-05-20 + 3600s + 730d = 2026-05-19T11:00; mocked now = 2026-05-08 → exclude
    from src.time_machine import should_exclude_call
    import src.time_machine as tm
    monkeypatch.setattr(tm, "_utcnow", lambda: datetime(2026, 5, 8))
    record = {"metaData": {"id": "d", "started": "2024-05-20T10:00:00Z", "duration": 3600}}
    assert should_exclude_call(record, 730) is True


def test_should_include_when_no_timestamps():
    from src.time_machine import should_exclude_call
    assert should_exclude_call({"metaData": {"id": "x"}}, 730) is False


def test_remap_record_shifts_started_and_ended():
    from src.time_machine import remap_record
    record = {"metaData": {"id": "c", "started": "2024-05-03T10:00:00Z",
                           "ended": "2024-05-03T11:00:00Z"}}
    result = remap_record(record, 730)
    expected_started = datetime(2024, 5, 3, 10, 0, 0) + timedelta(days=730)
    actual_started = datetime.strptime(result["metaData"]["started"], "%Y-%m-%dT%H:%M:%SZ")
    assert actual_started == expected_started


def test_remap_record_does_not_mutate_original():
    from src.time_machine import remap_record
    record = {"metaData": {"id": "c", "started": "2024-05-03T10:00:00Z"}}
    remap_record(record, 730)
    assert record["metaData"]["started"] == "2024-05-03T10:00:00Z"
