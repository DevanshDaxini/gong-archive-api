# Gong Archive API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI service that serves archived Gong call data from `.tar.xz` archives with a "Time Machine" feature: a persisted day-offset gates calls by comparing `ended + offset` against real UTC-now, and remaps response timestamps into virtual time.

**Architecture:** FastAPI app with a lifespan that loads `Config` (env vars + `offset.json` persistence) and builds an in-memory call index (`call_id → (tar_path, member_name)`). Two endpoints—`POST /v2/calls/extensive` (date-range metadata list) and `POST /v2/calls/transcript` (per-call transcript)—use the index and time-machine helpers to filter and remap records from `.tar.xz` archives via `python-xz` with sequential fallback.

**Tech Stack:** Python 3.9+, FastAPI 0.104, python-xz 0.6.4, python-dateutil 2.8.2, Pydantic v2, pytest 7.4, httpx 0.25

---

## File Map

| File | Responsibility |
|------|----------------|
| `requirements.txt` | Pinned dependencies |
| `src/__init__.py` | Package marker |
| `src/config.py` | Env-var loading, `offset.json` persistence, `TIME_OFFSET` calculation |
| `src/reader.py` | `ArchiveReader`: read/list `.tar.xz` members via python-xz with sequential fallback |
| `src/index.py` | `build_index()`: scans archives, extracts `call_id → (tar_path, member_name)` |
| `src/time_machine.py` | `remap_datetime()`, `should_exclude_call()`, `remap_record()` |
| `src/models.py` | Pydantic request models |
| `src/endpoints.py` | `POST /v2/calls/extensive` and `POST /v2/calls/transcript` |
| `src/main.py` | FastAPI app, lifespan (config + index load), health endpoint, router mount |
| `tests/__init__.py` | Package marker |
| `tests/conftest.py` | `make_tar_xz` fixture, `archive_root` fixture, `client` fixture |
| `tests/test_config.py` | Config loading and offset persistence unit tests |
| `tests/test_reader.py` | `ArchiveReader` unit tests |
| `tests/test_index.py` | `build_index()` unit tests |
| `tests/test_time_machine.py` | Time machine logic unit tests |
| `tests/test_endpoints.py` | Endpoint integration tests via `TestClient` |

---

### Task 1: Project Scaffold + Config

**Files:**
- Create: `requirements.txt`
- Create: `src/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `src/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Create requirements.txt**

```
fastapi==0.104.1
uvicorn[standard]==0.24.0
python-dateutil==2.8.2
python-xz==0.6.4
pydantic==2.5.0
pytest==7.4.3
httpx==0.25.0
```

- [ ] **Step 2: Install dependencies**

Run: `pip install -r requirements.txt`
Expected: All packages install without errors.

- [ ] **Step 3: Create package markers and conftest skeleton**

Create `src/__init__.py` — empty file.
Create `tests/__init__.py` — empty file.

Create `tests/conftest.py`:

```python
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
```

- [ ] **Step 4: Write failing config tests**

Create `tests/test_config.py`:

```python
import json
import pytest


def test_config_creates_offset_file(tmp_path, monkeypatch):
    offset_file = tmp_path / "offset.json"
    monkeypatch.setenv("ARCHIVE_ROOT", str(tmp_path / "archive"))
    monkeypatch.setenv("ARCHIVE_START_DATE", "2024-05-01")
    monkeypatch.setenv("VIRTUAL_START_DATE", "2026-05-06")
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "OFFSET_FILE", offset_file)

    config = cfg_mod.Config()

    assert offset_file.exists()
    assert json.loads(offset_file.read_text())["offset_days"] == 730
    assert config.offset_days == 730


def test_config_reads_existing_offset_ignores_env(tmp_path, monkeypatch):
    offset_file = tmp_path / "offset.json"
    offset_file.write_text('{"offset_days": 100}')
    monkeypatch.setenv("ARCHIVE_ROOT", str(tmp_path / "archive"))
    monkeypatch.setenv("ARCHIVE_START_DATE", "2024-05-01")
    monkeypatch.setenv("VIRTUAL_START_DATE", "2026-05-06")
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "OFFSET_FILE", offset_file)

    config = cfg_mod.Config()

    assert config.offset_days == 100  # persisted value wins over env-derived 730


def test_config_archive_root_from_env(tmp_path, monkeypatch):
    offset_file = tmp_path / "offset.json"
    monkeypatch.setenv("ARCHIVE_ROOT", str(tmp_path / "myarchive"))
    monkeypatch.setenv("ARCHIVE_START_DATE", "2024-05-01")
    monkeypatch.setenv("VIRTUAL_START_DATE", "2026-05-06")
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "OFFSET_FILE", offset_file)

    config = cfg_mod.Config()

    assert config.archive_root == tmp_path / "myarchive"
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: `ModuleNotFoundError: No module named 'src.config'`

- [ ] **Step 6: Implement src/config.py**

```python
import json
import logging
import os
from pathlib import Path

from dateutil import parser as dateutil_parser

logger = logging.getLogger(__name__)

OFFSET_FILE = Path("./offset.json")


class Config:
    def __init__(self) -> None:
        self.archive_root = Path(
            os.environ.get("ARCHIVE_ROOT", str(Path.home() / ".archive"))
        )
        archive_start_str = os.environ.get("ARCHIVE_START_DATE", "2024-05-01")
        virtual_start_str = os.environ.get("VIRTUAL_START_DATE", "2026-05-06")

        archive_start = dateutil_parser.parse(archive_start_str).replace(tzinfo=None)
        virtual_start = dateutil_parser.parse(virtual_start_str).replace(tzinfo=None)

        if OFFSET_FILE.exists():
            data = json.loads(OFFSET_FILE.read_text())
            self.offset_days: int = data["offset_days"]
        else:
            self.offset_days = (virtual_start - archive_start).days
            OFFSET_FILE.write_text(json.dumps({"offset_days": self.offset_days}))
            logger.info(
                f"TIME_OFFSET: {self.offset_days} days, shifted from "
                f"{archive_start_str} to {virtual_start_str}"
            )
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: 3 PASSED

- [ ] **Step 8: Commit**

```bash
git add requirements.txt src/__init__.py tests/__init__.py tests/conftest.py src/config.py tests/test_config.py
git commit -m "feat: project scaffold with config loading and offset.json persistence"
```

---

### Task 2: Archive Reader

**Files:**
- Create: `src/reader.py`
- Create: `tests/test_reader.py`

- [ ] **Step 1: Write failing reader tests**

Create `tests/test_reader.py`:

```python
import json
import pytest
from src.reader import ArchiveReader


@pytest.fixture
def sample_archive(tmp_path, make_tar_xz):
    members = {
        "05/call001.metadata.jsonl": json.dumps({"metaData": {"id": "call001"}}) + "\n",
        "05/call001.tx.jsonl": json.dumps({"speakerId": "u1", "text": "Hello", "start_ms": 1000}) + "\n",
        "05/call002.metadata.jsonl": json.dumps({"metaData": {"id": "call002"}}) + "\n",
    }
    p = tmp_path / "05.tar.xz"
    p.write_bytes(make_tar_xz(members))
    return p


def test_list_members_returns_all_files(sample_archive):
    reader = ArchiveReader()
    members = reader.list_members(str(sample_archive))
    assert "05/call001.metadata.jsonl" in members
    assert "05/call001.tx.jsonl" in members
    assert "05/call002.metadata.jsonl" in members


def test_read_member_returns_content(sample_archive):
    reader = ArchiveReader()
    content = reader.read_member(str(sample_archive), "05/call001.metadata.jsonl")
    assert json.loads(content.strip())["metaData"]["id"] == "call001"


def test_read_member_raises_on_missing(sample_archive):
    reader = ArchiveReader()
    with pytest.raises(FileNotFoundError):
        reader.read_member(str(sample_archive), "05/does-not-exist.jsonl")


def test_read_tx_member(sample_archive):
    reader = ArchiveReader()
    content = reader.read_member(str(sample_archive), "05/call001.tx.jsonl")
    assert json.loads(content.strip())["text"] == "Hello"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reader.py -v`
Expected: `ModuleNotFoundError: No module named 'src.reader'`

- [ ] **Step 3: Implement src/reader.py**

```python
import tarfile
import logging

logger = logging.getLogger(__name__)

try:
    import xz as _xz
    _HAS_XZ = True
except ImportError:
    _HAS_XZ = False


class ArchiveReader:
    def read_member(self, tar_path: str, member_name: str) -> str:
        if _HAS_XZ:
            try:
                with _xz.open(tar_path) as xz_file:
                    with tarfile.open(fileobj=xz_file) as tar:
                        return self._extract(tar, member_name, tar_path)
            except (FileNotFoundError, KeyError):
                raise
            except Exception:
                pass  # fall through to sequential decompress
        with tarfile.open(tar_path, "r:xz") as tar:
            return self._extract(tar, member_name, tar_path)

    def list_members(self, tar_path: str) -> list[str]:
        if _HAS_XZ:
            try:
                with _xz.open(tar_path) as xz_file:
                    with tarfile.open(fileobj=xz_file) as tar:
                        return [m.name for m in tar.getmembers() if m.isfile()]
            except Exception:
                pass
        with tarfile.open(tar_path, "r:xz") as tar:
            return [m.name for m in tar.getmembers() if m.isfile()]

    def _extract(self, tar: tarfile.TarFile, member_name: str, tar_path: str) -> str:
        try:
            f = tar.extractfile(member_name)
        except KeyError:
            raise FileNotFoundError(f"Member {member_name!r} not in {tar_path}")
        if f is None:
            raise FileNotFoundError(f"Member {member_name!r} not in {tar_path}")
        return f.read().decode("utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reader.py -v`
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/reader.py tests/test_reader.py
git commit -m "feat: add archive reader with python-xz random-access and sequential fallback"
```

---

### Task 3: Startup Index

**Files:**
- Create: `src/index.py`
- Create: `tests/test_index.py`

- [ ] **Step 1: Write failing index tests**

Create `tests/test_index.py`:

```python
import json
import pytest
from pathlib import Path


@pytest.fixture
def config_with_archive(tmp_path, make_tar_xz, monkeypatch):
    gong = tmp_path / "gong" / "2024"
    gong.mkdir(parents=True)

    members = {
        "05/call001.metadata.jsonl": json.dumps({
            "metaData": {"id": "call001", "started": "2024-05-03T10:00:00Z",
                         "ended": "2024-05-03T11:00:00Z", "duration": 3600}
        }) + "\n",
        "05/call002.metadata.jsonl": json.dumps({
            "metaData": {"id": "call002", "started": "2024-05-04T10:00:00Z",
                         "ended": "2024-05-04T11:00:00Z", "duration": 3600}
        }) + "\n",
        "05/call001.tx.jsonl": '{"speakerId": "u1", "text": "Hello", "start_ms": 1000}\n',
    }
    (gong / "05.tar.xz").write_bytes(make_tar_xz(members))

    offset_file = tmp_path / "offset.json"
    monkeypatch.setenv("ARCHIVE_ROOT", str(tmp_path))
    monkeypatch.setenv("ARCHIVE_START_DATE", "2024-05-01")
    monkeypatch.setenv("VIRTUAL_START_DATE", "2026-05-06")
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "OFFSET_FILE", offset_file)
    return cfg_mod.Config()


def test_build_index_finds_all_calls(config_with_archive):
    from src.index import build_index
    index = build_index(config_with_archive)
    assert "call001" in index
    assert "call002" in index


def test_build_index_entry_structure(config_with_archive):
    from src.index import build_index
    index = build_index(config_with_archive)
    tar_path, member_name = index["call001"]
    assert tar_path.endswith("05.tar.xz")
    assert member_name == "05/call001.metadata.jsonl"


def test_build_index_skips_malformed_json(tmp_path, make_tar_xz, monkeypatch):
    gong = tmp_path / "gong" / "2024"
    gong.mkdir(parents=True)
    members = {
        "05/call003.metadata.jsonl": (
            "NOT_JSON\n" +
            json.dumps({"metaData": {"id": "call003", "started": "2024-05-05T10:00:00Z"}}) + "\n"
        ),
    }
    (gong / "05.tar.xz").write_bytes(make_tar_xz(members))

    offset_file = tmp_path / "offset.json"
    monkeypatch.setenv("ARCHIVE_ROOT", str(tmp_path))
    monkeypatch.setenv("ARCHIVE_START_DATE", "2024-05-01")
    monkeypatch.setenv("VIRTUAL_START_DATE", "2026-05-06")
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "OFFSET_FILE", offset_file)
    config = cfg_mod.Config()

    from src.index import build_index
    index = build_index(config)
    assert "call003" in index  # second (valid) line parsed successfully


def test_build_index_empty_when_no_archives(tmp_path, monkeypatch):
    offset_file = tmp_path / "offset.json"
    monkeypatch.setenv("ARCHIVE_ROOT", str(tmp_path))
    monkeypatch.setenv("ARCHIVE_START_DATE", "2024-05-01")
    monkeypatch.setenv("VIRTUAL_START_DATE", "2026-05-06")
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "OFFSET_FILE", offset_file)
    config = cfg_mod.Config()

    from src.index import build_index
    assert build_index(config) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_index.py -v`
Expected: `ModuleNotFoundError: No module named 'src.index'`

- [ ] **Step 3: Implement src/index.py**

```python
import json
import logging
from src.config import Config
from src.reader import ArchiveReader

logger = logging.getLogger(__name__)


def build_index(config: Config) -> dict[str, tuple[str, str]]:
    index: dict[str, tuple[str, str]] = {}
    reader = ArchiveReader()
    archive_gong = config.archive_root / "gong"

    if not archive_gong.exists():
        logger.warning(f"Archive directory not found: {archive_gong}")
        return index

    for tar_path in sorted(archive_gong.glob("*/*.tar.xz")):
        try:
            members = reader.list_members(str(tar_path))
        except Exception as exc:
            logger.warning(f"Cannot list {tar_path}: {exc}")
            continue

        for member_name in members:
            if not member_name.endswith(".metadata.jsonl"):
                continue
            try:
                content = reader.read_member(str(tar_path), member_name)
            except Exception as exc:
                logger.warning(f"Cannot read {member_name} from {tar_path}: {exc}")
                continue

            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    meta = record.get("metaData", record)
                    call_id = meta.get("id")
                    if call_id:
                        index[call_id] = (str(tar_path), member_name)
                except json.JSONDecodeError:
                    logger.warning(f"Malformed JSON line in {member_name}")

    return index
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_index.py -v`
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/index.py tests/test_index.py
git commit -m "feat: add startup index builder scanning all .tar.xz archives"
```

---

### Task 4: Time Machine Logic

**Files:**
- Create: `src/time_machine.py`
- Create: `tests/test_time_machine.py`

- [ ] **Step 1: Write failing time machine tests**

Create `tests/test_time_machine.py`:

```python
from datetime import datetime, timedelta
import pytest


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


def test_should_exclude_future_call():
    # ended 2024-06-01 + 730d ≈ 2026-05-31 > utcnow (2026-05-08) → exclude
    from src.time_machine import should_exclude_call
    record = {"metaData": {"id": "f", "started": "2024-06-01T10:00:00Z",
                           "ended": "2024-06-01T11:00:00Z", "duration": 3600}}
    assert should_exclude_call(record, 730) is True


def test_should_include_past_call():
    # ended 2024-04-01 + 730d ≈ 2026-03-31 < utcnow (2026-05-08) → include
    from src.time_machine import should_exclude_call
    record = {"metaData": {"id": "p", "started": "2024-04-01T10:00:00Z",
                           "ended": "2024-04-01T11:00:00Z", "duration": 3600}}
    assert should_exclude_call(record, 730) is False


def test_should_exclude_uses_duration_when_no_ended():
    # started 2024-05-20 + 3600s = 2024-05-20T11:00 + 730d ≈ 2026-05-19 > now → exclude
    from src.time_machine import should_exclude_call
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_time_machine.py -v`
Expected: `ModuleNotFoundError: No module named 'src.time_machine'`

- [ ] **Step 3: Implement src/time_machine.py**

```python
import copy
import logging
from datetime import datetime, timedelta

from dateutil import parser as dateutil_parser

logger = logging.getLogger(__name__)

_DATETIME_FIELDS = {"started", "ended", "scheduled", "created", "updated"}


def remap_datetime(dt_str: str, offset_days: int) -> str:
    try:
        dt = dateutil_parser.parse(dt_str).replace(tzinfo=None)
        return (dt + timedelta(days=offset_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        logger.warning(f"Could not parse datetime: {dt_str!r}")
        return dt_str


def should_exclude_call(record: dict, offset_days: int) -> bool:
    try:
        meta = record.get("metaData", record)
        ended_str = meta.get("ended")

        if ended_str:
            ended = dateutil_parser.parse(ended_str).replace(tzinfo=None)
            return (ended + timedelta(days=offset_days)) > datetime.utcnow()

        started_str = meta.get("started")
        duration = meta.get("duration", 0)
        if started_str:
            started = dateutil_parser.parse(started_str).replace(tzinfo=None)
            ended = started + timedelta(seconds=int(duration))
            return (ended + timedelta(days=offset_days)) > datetime.utcnow()

        return False
    except Exception as exc:
        logger.warning(f"Gating error: {exc}")
        return False


def _remap_dict(d: dict, offset_days: int) -> dict:
    for key, value in d.items():
        if isinstance(value, str) and key in _DATETIME_FIELDS:
            d[key] = remap_datetime(value, offset_days)
        elif isinstance(value, dict):
            d[key] = _remap_dict(value, offset_days)
    return d


def remap_record(record: dict, offset_days: int) -> dict:
    return _remap_dict(copy.deepcopy(record), offset_days)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_time_machine.py -v`
Expected: 8 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/time_machine.py tests/test_time_machine.py
git commit -m "feat: add time machine remap and gating logic"
```

---

### Task 5: FastAPI App + Endpoints + Integration Tests

**Files:**
- Create: `src/models.py`
- Create: `src/endpoints.py`
- Create: `src/main.py`
- Create: `tests/test_endpoints.py`

- [ ] **Step 1: Write failing endpoint tests**

Create `tests/test_endpoints.py`:

```python
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
    # Original started 2024-04-01, after +730d should be in 2026
    assert past["metaData"]["started"].startswith("2026-")


def test_extensive_returns_total_records(client):
    resp = client.post("/v2/calls/extensive", json={
        "filter": {"fromDateTime": "2026-03-01T00:00:00Z", "toDateTime": "2026-05-01T00:00:00Z"}
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["records"]["totalRecords"] == len(data["calls"])


def test_extensive_future_range_returns_400(client):
    # hist_from = 2030-01-01 - 730d ≈ 2028-01-01 > utcnow → 400
    resp = client.post("/v2/calls/extensive", json={
        "filter": {"fromDateTime": "2030-01-01T00:00:00Z", "toDateTime": "2030-02-01T00:00:00Z"}
    })
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "Invalid date range"
    assert "future" in body["message"].lower()


def test_extensive_400_includes_offset_details(client):
    resp = client.post("/v2/calls/extensive", json={
        "filter": {"fromDateTime": "2030-01-01T00:00:00Z", "toDateTime": "2030-02-01T00:00:00Z"}
    })
    assert resp.status_code == 400
    details = resp.json()["details"]
    assert "730" in details["offset"]


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_endpoints.py -v`
Expected: `ModuleNotFoundError: No module named 'src.main'` (or similar import error)

- [ ] **Step 3: Create src/models.py**

```python
from __future__ import annotations
from pydantic import BaseModel


class DateFilter(BaseModel):
    fromDateTime: str
    toDateTime: str


class ExtensiveRequest(BaseModel):
    filter: DateFilter


class CallIdFilter(BaseModel):
    callIds: list[str]


class TranscriptRequest(BaseModel):
    filter: CallIdFilter
```

- [ ] **Step 4: Create src/endpoints.py**

```python
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from dateutil import parser as dateutil_parser
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.models import ExtensiveRequest, TranscriptRequest
from src.reader import ArchiveReader
from src.time_machine import remap_record, should_exclude_call

logger = logging.getLogger(__name__)
router = APIRouter()


def _archive_months(archive_root: Path, from_dt: datetime, to_dt: datetime) -> list[Path]:
    paths = []
    current = from_dt.replace(day=1)
    while current <= to_dt:
        p = archive_root / "gong" / str(current.year) / f"{current.month:02d}.tar.xz"
        if p.exists():
            paths.append(p)
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return paths


@router.post("/v2/calls/extensive")
async def extensive(request: Request, body: ExtensiveRequest) -> JSONResponse:
    config = request.app.state.config
    reader = ArchiveReader()
    offset = config.offset_days

    from_dt = dateutil_parser.parse(body.filter.fromDateTime).replace(tzinfo=None)
    to_dt = dateutil_parser.parse(body.filter.toDateTime).replace(tzinfo=None)
    hist_from = from_dt - timedelta(days=offset)
    hist_to = to_dt - timedelta(days=offset)

    if hist_from > datetime.utcnow():
        return JSONResponse(
            status_code=400,
            content={
                "error": "Invalid date range",
                "message": "Requested date range is entirely in the future",
                "details": {
                    "requested": f"{from_dt.date()} to {to_dt.date()}",
                    "offset": f"{offset} days",
                },
            },
        )

    calls = []
    for tar_path in _archive_months(config.archive_root, hist_from, hist_to):
        try:
            members = reader.list_members(str(tar_path))
        except Exception as exc:
            logger.warning(f"Cannot list {tar_path}: {exc}")
            continue
        for member_name in members:
            if not member_name.endswith(".metadata.jsonl"):
                continue
            try:
                content = reader.read_member(str(tar_path), member_name)
            except Exception as exc:
                logger.warning(f"Cannot read {member_name}: {exc}")
                continue
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if not should_exclude_call(record, offset):
                        calls.append(remap_record(record, offset))
                except json.JSONDecodeError:
                    logger.warning(f"Malformed JSON in {member_name}")

    return JSONResponse(content={
        "calls": calls,
        "records": {"totalRecords": len(calls), "cursor": ""},
    })


@router.post("/v2/calls/transcript")
async def transcript_endpoint(request: Request, body: TranscriptRequest) -> JSONResponse:
    config = request.app.state.config
    index = request.app.state.index
    reader = ArchiveReader()
    offset = config.offset_days

    results = []
    for call_id in body.filter.callIds:
        if call_id not in index:
            return JSONResponse(
                status_code=404,
                content={"error": "Call not found", "message": f"Call {call_id!r} not found"},
            )

        tar_path, member_name = index[call_id]

        try:
            meta_content = reader.read_member(tar_path, member_name)
            first_line = next(
                (l for l in meta_content.splitlines() if l.strip()), ""
            )
            if first_line:
                meta_record = json.loads(first_line)
                if should_exclude_call(meta_record, offset):
                    return JSONResponse(
                        status_code=404,
                        content={
                            "error": "Call not found",
                            "message": "This call has not occurred yet",
                        },
                    )
        except Exception as exc:
            logger.warning(f"Cannot read metadata for {call_id}: {exc}")

        tx_member = member_name.replace(".metadata.jsonl", ".tx.jsonl")
        tx_lines: list[dict] = []
        try:
            tx_content = reader.read_member(tar_path, tx_member)
            for line in tx_content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    tx_lines.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning(f"Malformed JSON in transcript {call_id}")
        except Exception as exc:
            logger.warning(f"No transcript found for {call_id}: {exc}")

        results.append({"callId": call_id, "transcript": tx_lines})

    return JSONResponse(content={"callTranscripts": results})
```

- [ ] **Step 5: Create src/main.py**

```python
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config import Config
from src.endpoints import router
from src.index import build_index

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = Config()
    logger.info(f"TIME_OFFSET: {config.offset_days} days")
    index = build_index(config)
    logger.info(f"Index built: {len(index)} calls indexed")
    app.state.config = config
    app.state.index = index
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 6: Run all tests**

Run: `pytest -v`
Expected: All tests across test_config.py, test_reader.py, test_index.py, test_time_machine.py, test_endpoints.py pass. Minimum 19 tests PASSED, 0 FAILED.

- [ ] **Step 7: Commit**

```bash
git add src/models.py src/endpoints.py src/main.py tests/test_endpoints.py
git commit -m "feat: add FastAPI app with extensive and transcript endpoints"
```

---

### Task 6: Smoke Test + Final Verification

**Files:**
- No new files

- [ ] **Step 1: Set env vars and start server**

```bash
export ARCHIVE_ROOT=~/.archive
export ARCHIVE_START_DATE=2024-05-01
export VIRTUAL_START_DATE=2026-05-06
python -m uvicorn src.main:app --reload --port 8000
```

Expected log output:
```
INFO src.config: TIME_OFFSET: 730 days, shifted from 2024-05-01 to 2026-05-06
INFO src.main: Index built: N calls indexed
INFO:     Application startup complete.
```

If `~/.archive` doesn't exist or is empty, `N = 0` is acceptable. The server must start without crashing.

- [ ] **Step 2: Verify health endpoint**

```bash
curl -s http://localhost:8000/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 3: Verify offset.json was created**

```bash
cat ./offset.json
```

Expected: `{"offset_days": 730}`

- [ ] **Step 4: Restart server and verify offset.json is reused (not recalculated)**

Stop the server (Ctrl+C). Modify env var to a different virtual start:
```bash
export VIRTUAL_START_DATE=2027-01-01
python -m uvicorn src.main:app --port 8000
```

Expected log: No "TIME_OFFSET: ... days" INFO from config (offset.json already exists, env var ignored).

Confirm: `cat ./offset.json` still shows `{"offset_days": 730}`, not 610.

- [ ] **Step 5: Run full test suite one final time**

```bash
pytest -v --tb=short
```

Expected: All tests PASSED, 0 errors.

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "chore: final verification pass, all tests green"
```

---

## Self-Review

### Spec Coverage

| Spec Requirement | Task |
|---|---|
| FastAPI app + health endpoint | Task 5 (main.py) |
| ARCHIVE_ROOT / ARCHIVE_START_DATE / VIRTUAL_START_DATE env vars | Task 1 (config.py) |
| TIME_OFFSET calculation | Task 1 (config.py) |
| offset.json auto-create on first run | Task 1 (config.py) |
| offset.json read on subsequent runs (immutable) | Task 1 (config.py) |
| Startup logging of offset | Task 1 (config.py) |
| python-xz random access | Task 2 (reader.py) |
| Sequential fallback for single-block archives | Task 2 (reader.py) |
| Startup indexing: CallID → (tar_path, member_name) | Task 3 (index.py) |
| Skip malformed JSONL lines | Task 3 (index.py) + Task 5 (endpoints.py) |
| Skip missing archives | Task 3 (index.py) + Task 5 (endpoints.py) |
| remap_datetime: original + offset, Z suffix | Task 4 (time_machine.py) |
| Gating: ended + offset > utcnow → exclude | Task 4 (time_machine.py) |
| Gating: started + duration fallback | Task 4 (time_machine.py) |
| Gating: include when no timestamps | Task 4 (time_machine.py) |
| remap_record: deep copy + remap all datetime fields | Task 4 (time_machine.py) |
| POST /v2/calls/extensive: date range filter | Task 5 (endpoints.py) |
| POST /v2/calls/extensive: reverse-remap dates to historical | Task 5 (endpoints.py) |
| POST /v2/calls/extensive: 400 for future range | Task 5 (endpoints.py) |
| POST /v2/calls/extensive: 400 response format with details | Task 5 (endpoints.py) |
| POST /v2/calls/transcript: lookup by call_id | Task 5 (endpoints.py) |
| POST /v2/calls/transcript: 404 for unknown call | Task 5 (endpoints.py) |
| POST /v2/calls/transcript: 404 with "not occurred yet" for future call | Task 5 (endpoints.py) |
| Transcript: no timestamp remapping on transcript lines | Task 5 (endpoints.py) — tx.jsonl lines returned as-is |

All requirements covered.

### Type Consistency

- `Config.offset_days: int` — used as `int` everywhere (`timedelta(days=offset)`, `f"{offset} days"`)
- `build_index()` returns `dict[str, tuple[str, str]]` — consumed as `tar_path, member_name = index[call_id]` ✓
- `ArchiveReader.read_member()` returns `str` — splitlines() called on result ✓
- `remap_record()` returns `dict` — appended to `calls: list` ✓
- `should_exclude_call()` returns `bool` — used in `if not should_exclude_call(...)` ✓
