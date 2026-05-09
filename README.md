# Gong Archive API

A FastAPI service that serves archived Gong call data with a **Time Machine** feature — historical call timestamps are shifted forward so the archive appears to be a live, ongoing dataset.

## Status

✅ **Complete.** All 5 phases implemented and tested:
- **Phase 1:** Config + FastAPI (dynamic offset calculation, no persistence)
- **Phase 2:** Archive reader with python-xz + O(1) indexing
- **Phase 3:** Time machine logic (remapping + gating)
- **Phase 4:** REST endpoints (`/v2/calls/extensive`, `/v2/calls/transcript`)
- **Phase 5:** Test suite (32 tests, all passing)

## How It Works

### Time Machine Engine (Dynamic)

On every startup, the service calculates a fresh `TIME_OFFSET = (today - ARCHIVE_START_DATE).days`. This offset is **never persisted** — it's recalculated each time the service starts, ensuring the data window continuously advances with real time.

All API responses return timestamps shifted forward by the offset. Calls whose shifted end time is still in the future are hidden (gated out), making the archive feel like a live feed that grows incrementally.

**Example:**
- Archive contains call from 2025-05-01 10:00 AM
- ARCHIVE_START_DATE: 2025-01-01
- Day 1 (May 8, 2026): TIME_OFFSET = 493 days → call appears as 2026-05-08 10:00 AM
- Day 2 (May 9, 2026): TIME_OFFSET = 494 days → same call appears as 2026-05-09 10:00 AM
- Current system time used as gating boundary — calls beyond current time are excluded
- **Key benefit:** Archive automatically appears to have new data each day. Solves "not running once a month" issue.

### Architecture

| Component | Purpose |
|-----------|---------|
| `config.py` | Load environment config, calculate TIME_OFFSET dynamically at each startup |
| `reader.py` | Stream XZ-compressed tar archives without full decompression (python-xz + fallback) |
| `index.py` | Build in-memory call ID → tar path + member name mapping at startup (O(1) lookup) |
| `time_machine.py` | Remap timestamps (ISO 8601 strings) and apply gating logic |
| `endpoints.py` | REST API handlers for `/v2/calls/extensive` and `/v2/calls/transcript` |
| `models.py` | Pydantic request/response schemas |

### Archive Reading with python-xz

The `ArchiveReader` uses **python-xz** for random access to `.xz` files rather than decompressing the entire archive on each request. This is crucial for large archives:

- **python-xz**: Attempts to seek within multi-block `.xz` files for random access
- **Fallback**: If random access fails (single-block archives), transparently falls back to sequential decompression via tarfile's built-in xz support
- **Benefit**: Avoids keeping large decompressed archives in memory or on disk

### Timestamp Remapping

The service remaps ISO 8601 datetime fields (`started`, `ended`, `scheduled`, `created`, `updated`) by:

1. Parsing with `python-dateutil` (handles `Z` suffix and timezone variants)
2. Adding TIME_OFFSET days
3. Returning as ISO 8601 string with `Z` suffix

Non-ISO 8601 fields (Unix timestamps, date strings) are not remapped and remain unchanged. Unparseable timestamps are logged and returned as-is.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Set these environment variables before starting the server:

| Variable | Description | Example |
|----------|-------------|---------|
| `ARCHIVE_ROOT` | Path to your archive directory | `/data/gong-archive` |
| `ARCHIVE_START_DATE` | Real date your oldest call data begins (ISO 8601) | `2025-01-01` |

The offset is calculated dynamically: `TIME_OFFSET = (today - ARCHIVE_START_DATE).days`. No configuration needed for the target date — it always uses the current system time.

The archive must be structured as:
```
ARCHIVE_ROOT/gong/{year}/{month}.tar.xz
```

Each `.tar.xz` contains `.metadata.jsonl` and `.tx.jsonl` files per call.

## Running

```bash
export ARCHIVE_ROOT=/path/to/archive
export ARCHIVE_START_DATE=2025-01-01

uvicorn src.main:app --reload --port 8000
```

On startup, the service will:
1. Calculate TIME_OFFSET dynamically from ARCHIVE_START_DATE
2. Scan and index all calls in the archive
3. Start listening on port 8000
4. Log: `TIME_OFFSET: {N} days (calculated from ARCHIVE_START_DATE: 2025-01-01)`

## Endpoints

### `GET /health`
Returns `{"status": "ok"}`. Use to verify the service is running.

### `POST /v2/calls/extensive`
Returns calls within a virtual date range, with timestamps remapped.

**Request:**
```json
{
  "filter": {
    "fromDateTime": "2026-01-01T00:00:00Z",
    "toDateTime": "2026-05-08T00:00:00Z"
  }
}
```

**Response (200 OK):**
```json
{
  "calls": [
    {
      "id": "call-123",
      "started": "2026-05-03T10:00:00Z",
      "ended": "2026-05-03T11:00:00Z",
      "title": "Q2 Planning",
      "raw": {
        "metaData": { "id": "call-123", "started": "2026-05-03T10:00:00Z", ... },
        "participants": [...],
        ...
      }
    }
  ],
  "records": { "totalRecords": 1, "cursor": "" }
}
```

**Behavior:**
- Reverse-remaps request dates to find historical archives
- Excludes calls whose remapped end time is in the future (gating logic)
- Returns 400 if entire date range is in the future (no archives to search)

### `POST /v2/calls/transcript`
Returns transcript segments for specific call IDs.

**Request:**
```json
{
  "filter": {
    "callIds": ["call-123", "call-456"]
  }
}
```

**Response (200 OK):**
```json
{
  "callTranscripts": [
    {
      "callId": "call-123",
      "transcript": [
        { "speakerId": "speaker-a", "text": "Hello everyone", "start_ms": 1000 },
        { "speakerId": "speaker-b", "text": "Hi there", "start_ms": 3000 }
      ]
    }
  ]
}
```

**Behavior:**
- Uses startup index for O(1) call lookup
- Returns 404 if call doesn't exist or hasn't occurred yet (gating check)
- Transcript times (`start_ms`) are relative to call start and are NOT remapped

## Dependencies

| Library | Version | Purpose |
|---------|---------|---------|
| **FastAPI** | 0.104.1 | Modern async HTTP framework with automatic OpenAPI schema generation |
| **uvicorn** | 0.24.0 | ASGI server for running FastAPI |
| **python-dateutil** | 2.8.2 | Robust ISO 8601 datetime parsing; handles timezone variants and `Z` suffix (Python 3.9+ compatibility) |
| **python-xz** | 0.6.4 | Random access decompression of multi-block `.xz` files; avoids full decompression overhead |
| **pydantic** | 2.5.0 | Request validation and JSON schema generation |
| **pytest** | 7.4.3 | Testing framework |

## Performance Considerations

### Index Startup
On startup, the service scans all `.metadata.jsonl` files in the archive and builds an in-memory map of call ID → tar location. For large archives, this may take several seconds but enables O(1) lookups for transcript requests.

### Archive Decompression
- **Multi-block `.xz` files**: python-xz enables seeking, so only the needed tar member is decompressed
- **Single-block `.xz` files**: Falls back to sequential decompression (full archive decompressed into memory)
- **Recommendation**: For archives >1GB, consider creating multi-block `.xz` files during archival

### Gating Logic
Future calls are excluded before JSON parsing to avoid unnecessary work. The `ended` field is checked first; if missing, the service falls back to `started + duration_seconds`.

## Testing

Run all tests:
```bash
pytest -v
```

**Test Coverage (32 tests):**
- **Config** (3): Dynamic offset calculation, fresh calculation on each startup, env loading
- **Endpoints** (11): Health check, extensive queries, transcript lookup, future call gating, error responses
- **Index** (4): Index building, entry structure, malformed JSON handling, empty archives
- **Reader** (5): Member listing, content reading, missing file handling, fallback decompression
- **Time Machine** (9): Datetime remapping, time-of-day preservation, gating logic, record remapping

All tests use mocked current time (2026-05-08) for reproducibility. Run after changes to verify:
- Timestamp remapping correctness (offset applied correctly)
- Gating logic (future calls excluded, past calls included)
- Archive reading and indexing (O(1) lookup, fallback handling)
- Error handling (malformed JSON, missing archives, invalid dates, future date ranges)
