# Gong Archive API

A FastAPI service that serves archived Gong call data with a **Time Machine** feature — historical call timestamps are shifted forward so the archive appears to be a live, ongoing dataset.

## How It Works

### Time Machine Engine

On startup, the service calculates a `TIME_OFFSET` (the difference between `ARCHIVE_START_DATE` and `VIRTUAL_START_DATE`). This offset is persisted to `offset.json` and never recalculated, ensuring consistent results across restarts.

All API responses return timestamps shifted forward by the offset. Calls whose shifted end time is still in the future are hidden (gated out), making the archive feel like a live feed.

**Example:**
- Archive contains call from 2024-05-03 10:00 AM
- ARCHIVE_START_DATE: 2024-05-01, VIRTUAL_START_DATE: 2026-05-06
- TIME_OFFSET: 735 days
- Call appears to user as 2026-05-08 10:00 AM
- Current system time used as gating boundary — calls beyond current time are excluded

### Architecture

| Component | Purpose |
|-----------|---------|
| `config.py` | Load environment config, calculate and persist TIME_OFFSET |
| `reader.py` | Stream XZ-compressed tar archives without full decompression |
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
| `ARCHIVE_START_DATE` | Real date your oldest call data begins | `2024-05-01` |
| `VIRTUAL_START_DATE` | Date you want the archive to appear to start from | `2026-05-06` |

The archive must be structured as:
```
ARCHIVE_ROOT/gong/{year}/{month}.tar.xz
```

Each `.tar.xz` contains `.metadata.jsonl` and `.tx.jsonl` files per call.

## Running

```bash
export ARCHIVE_ROOT=/path/to/archive
export ARCHIVE_START_DATE=2024-05-01
export VIRTUAL_START_DATE=2026-05-06

uvicorn src.main:app --reload --port 8000
```

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

## Tests

```bash
pytest -v
```

Run tests after changes to verify:
- Timestamp remapping correctness
- Gating logic (future calls excluded, past calls included)
- Archive reading and indexing
- Error handling (malformed JSON, missing archives, invalid dates)
