# Gong Archive API

A FastAPI service that serves archived Gong call data with a **Time Machine** feature — historical call timestamps are shifted forward so the archive appears to be a live, ongoing dataset.

## How It Works

On startup, the service calculates a `TIME_OFFSET` (the difference between `ARCHIVE_START_DATE` and `VIRTUAL_START_DATE`). This offset is persisted to `offset.json` and never recalculated, ensuring consistent results across restarts.

All API responses return timestamps shifted forward by the offset. Calls whose shifted end time is still in the future are hidden, making the archive feel like a live feed.

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
Returns `{"status": "ok"}`.

### `POST /v2/calls/extensive`
Returns calls within a virtual date range, with timestamps remapped.

```json
{
  "filter": {
    "fromDateTime": "2026-01-01T00:00:00Z",
    "toDateTime": "2026-05-08T00:00:00Z"
  }
}
```

### `POST /v2/calls/transcript`
Returns the transcript for one or more call IDs.

```json
{
  "filter": {
    "callIds": ["abc123", "def456"]
  }
}
```

Returns 404 if a call doesn't exist or hasn't occurred yet in virtual time.

## Tests

```bash
pytest -v
```
