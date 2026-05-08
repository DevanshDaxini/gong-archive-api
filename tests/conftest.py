import io
import json
import lzma
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


PAST_CALL_ID = "call-past-001"
FUTURE_CALL_ID = "call-future-001"

# offset=730 days; cutoff = utcnow() - 730d ≈ 2024-05-08
# Past call ended 2024-04-01: 2024-04-01+730 ≈ 2026-03-31 < now → include
# Future call ended 2024-06-01: 2024-06-01+730 ≈ 2026-05-31 > now → exclude
PAST_META = {
    "metaData": {
        "id": PAST_CALL_ID,
        "started": "2024-04-01T10:00:00Z",
        "ended": "2024-04-01T11:00:00Z",
        "duration": 3600,
        "title": "Past Call",
    }
}
FUTURE_META = {
    "metaData": {
        "id": FUTURE_CALL_ID,
        "started": "2024-06-01T10:00:00Z",
        "ended": "2024-06-01T11:00:00Z",
        "duration": 3600,
        "title": "Future Call",
    }
}
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
def client(archive_root, tmp_path, monkeypatch):
    offset_file = tmp_path / "offset.json"
    monkeypatch.setenv("ARCHIVE_ROOT", str(archive_root))
    monkeypatch.setenv("ARCHIVE_START_DATE", "2024-05-01")
    monkeypatch.setenv("VIRTUAL_START_DATE", "2026-05-06")

    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "OFFSET_FILE", offset_file)

    from src.main import app
    with TestClient(app) as c:
        yield c
