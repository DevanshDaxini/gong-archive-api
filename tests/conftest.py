import io
import json
import lzma
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


PAST_CALL_ID = "call-past-001"
FUTURE_CALL_ID = "call-future-001"

# Test setup: Mock current time to 2026-05-08, ARCHIVE_START_DATE = 2024-05-01
# Expected offset = 738 days
# Past call ended 2024-04-30: 2024-04-30+738 = 2026-05-07 < 2026-05-08 → include
# Future call ended 2024-05-15: 2024-05-15+738 = 2026-05-22 > 2026-05-08 → exclude
PAST_META = {
    "metaData": {
        "id": PAST_CALL_ID,
        "started": "2024-04-30T10:00:00Z",
        "ended": "2024-04-30T11:00:00Z",
        "duration": 3600,
        "title": "Past Call",
    }
}
FUTURE_META = {
    "metaData": {
        "id": FUTURE_CALL_ID,
        "started": "2024-05-15T10:00:00Z",
        "ended": "2024-05-15T11:00:00Z",
        "duration": 3600,
        "title": "Future Call",
    }
}
TEST_CURRENT_TIME = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
TRANSCRIPT_LINES = [
    {"speakerId": "u1", "text": "Hello", "start_ms": 1000},
    {"speakerId": "u2", "text": "Hi", "start_ms": 2000},
]


@pytest.fixture
def make_tar_xz():
    def _make(members: dict) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for name, content in members.items():
                data = content.encode("utf-8")
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return lzma.compress(buf.getvalue())
    return _make


@pytest.fixture
def archive_root(tmp_path, make_tar_xz):
    gong = tmp_path / "gong" / "2024"
    gong.mkdir(parents=True)

    past_tx = "\n".join(json.dumps(t) for t in TRANSCRIPT_LINES) + "\n"
    (gong / "04.tar.xz").write_bytes(make_tar_xz({
        f"04/{PAST_CALL_ID}.metadata.jsonl": json.dumps(PAST_META) + "\n",
        f"04/{PAST_CALL_ID}.tx.jsonl": past_tx,
    }))
    (gong / "06.tar.xz").write_bytes(make_tar_xz({
        f"06/{FUTURE_CALL_ID}.metadata.jsonl": json.dumps(FUTURE_META) + "\n",
        f"06/{FUTURE_CALL_ID}.tx.jsonl": past_tx,
    }))
    return tmp_path


@pytest.fixture
def client(archive_root, monkeypatch):
    monkeypatch.setenv("ARCHIVE_ROOT", str(archive_root))
    monkeypatch.setenv("ARCHIVE_START_DATE", "2024-05-01")

    # Mock datetime.now(UTC) to return a fixed time for test predictability
    import src.config as cfg_mod
    import src.time_machine as tm_mod
    import src.endpoints as ep_mod

    monkeypatch.setattr(cfg_mod, "datetime", _MockDatetime(TEST_CURRENT_TIME))
    monkeypatch.setattr(tm_mod, "datetime", _MockDatetime(TEST_CURRENT_TIME))
    monkeypatch.setattr(ep_mod, "datetime", _MockDatetime(TEST_CURRENT_TIME))

    from src.main import app
    with TestClient(app) as c:
        yield c


class _MockDatetime:
    def __init__(self, fixed_time):
        self.fixed_time = fixed_time

    def now(self, tz=None):
        return self.fixed_time

    def fromisoformat(self, date_string):
        return datetime.fromisoformat(date_string)
