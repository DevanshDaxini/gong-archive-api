# BUILD_PLAN.md: Gong Archive API

## Overview
Building a Python FastAPI service that serves archived Gong call data via two HTTP endpoints with a "Time Machine" feature that dynamically shifts historical timestamps to appear current without transforming the actual call dates. The TIME_OFFSET is recalculated at each service startup, ensuring the data window continuously advances with real time.

## Project Structure
```
gong-archive-api/
├── README.md
├── BUILD_PLAN.md (this file)
├── requirements.txt
├── .gitignore
├── src/
│   ├── __init__.py
│   ├── main.py              (FastAPI app entry point)
│   ├── config.py            (config loading, dynamic TIME_OFFSET calculation)
│   ├── reader.py            (archive reader with python-xz random access)
│   ├── models.py            (Pydantic models for requests/responses)
│   ├── endpoints.py         (POST /v2/calls/extensive and /v2/calls/transcript)
│   ├── time_machine.py      (remapping and gating logic)
│   └── index.py             (startup indexing: CallID -> TarPath)
└── tests/
    ├── __init__.py
    ├── conftest.py          (test fixtures and mocking)
    ├── test_config.py
    ├── test_endpoints.py
    ├── test_index.py
    ├── test_reader.py
    └── test_time_machine.py
```

## Status
**Phase 1 (COMPLETE):** FastAPI setup, dynamic TIME_OFFSET calculation, comprehensive test suite (32 tests passing).

Remaining phases: 2-5 (not yet started)

## Critical Design Decisions

### Time Machine Logic (Dynamic)
- `TIME_OFFSET = (today - ARCHIVE_START_DATE).days` — calculated fresh at each startup
- Example: ARCHIVE_START_DATE = 2025-01-01, today = 2026-05-08 → offset = 493 days
- `GATING_BOUNDARY = datetime.now(UTC)` (the service uses the actual current system time as the boundary)
- **Key benefit:** Data window continuously advances with real time. Restart tomorrow, offset increases by 1.
- **Why:** Solves the "not running once a month" issue — archive appears to be a live feed that grows incrementally.

**How it works:**
- Historical call: May 8, 2025 at 10:00 AM
- With offset (493 days): Appears as May 8, 2026 at 10:00 AM
- If service restarts on May 9, offset becomes 494 days
- Same call now appears as May 9, 2026 at 10:00 AM
- Boundary always moves forward with real time

### Archive Access
- **Library:** `python-xz` (pip-installable, enables random access on `.xz` files)
- **Fallback:** If random access fails (single-block archive), silently fall back to sequential decompress on each request
- **No Hybrid Cache:** Pure random access preferred; no explicit caching layer

### Timestamp Parsing
- **Library:** `python-dateutil` (handles ISO 8601 with `Z` suffix)
- **Usage:** `dateutil.parser.parse()` for all ISO 8601 parsing
- **Python Version:** Supports Python 3.9+ (before native `Z` support in 3.11)

### Gating Logic (Call Filtering)
A call is **EXCLUDED** if:
1. If `ended` field exists (original timestamp):
   - Check if `ended + TIME_OFFSET > datetime.utcnow()`
   - If yes, exclude
2. If `ended` doesn't exist, fall back to: `started + timedelta(seconds=record["metaData"]["duration"])`
   - Check if computed end time + TIME_OFFSET > datetime.utcnow()`
   - If yes, exclude
3. If neither field exists, include the call

### Request Validation (Pre-Check)
Before loading archives:
- Reverse-remap request date range: `Historical_From = Request_From - TIME_OFFSET`, `Historical_To = Request_To - TIME_OFFSET`
- Check if both dates are in the past (before `datetime.utcnow() - TIME_OFFSET`)
- If entire range is in the future, return 400 immediately (saves archive I/O)

### Error Responses

**Invalid Date Range (400 Bad Request):**
```json
{
  "error": "Invalid date range",
  "message": "Requested date range is entirely in the future",
  "details": {
    "requested": "2026-06-01 to 2026-07-01",
    "offset": "730 days"
  }
}
```

**Future Single Call (404 Not Found):**
```json
{
  "error": "Call not found",
  "message": "This call has not occurred yet"
}
```

### Index Storage
Startup index must store: `CallID -> (tar_path, member_name)`
- `tar_path`: Full path to `.tar.xz` file (e.g., `/path/to/archive/gong/2024/05.tar.xz`)
- `member_name`: File path inside archive (e.g., `05/abc123.metadata.jsonl`)
- Enables O(1) lookup for `/v2/calls/transcript` requests

### Error Handling
- **Malformed JSONL lines:** Wrap each line parse in try/except, skip bad lines, continue
- **Missing archives:** Wrap archive lookups in try/except, return empty results instead of crashing
- **Timestamp parsing failures:** Log and skip records with unparseable timestamps

---

## Phase 1: Scaffold & Config (FastAPI Setup) — COMPLETE

**Status:** ✓ Implemented and tested (32 tests passing)

**Deliverables:**
1. ✓ FastAPI app with GET `/health` endpoint returning `{"status": "ok"}`
2. ✓ Config loading from environment:
   - `ARCHIVE_ROOT`: Path to archive directory (default: `~/.archive`)
   - `ARCHIVE_START_DATE`: ISO 8601 date (e.g., `2025-01-01`)
3. ✓ Dynamic TIME_OFFSET calculation: `(today - ARCHIVE_START_DATE).days`
   - Calculated fresh at every startup
   - No persistence; no offset.json file
   - No VIRTUAL_START_DATE needed
4. ✓ Logging at startup: `"TIME_OFFSET: {X} days (calculated from ARCHIVE_START_DATE: {date})"`
5. ✓ Modern UTC handling: `datetime.now(UTC)` (no deprecated `utcnow()`)
6. ✓ `requirements.txt` with FastAPI, uvicorn, python-dateutil, python-xz

**Tests Implemented (src/tests/):**
- `test_config.py`: 3 tests
  - Dynamic offset calculation correct
  - Fresh calculation on each startup
  - Archive root loaded from env
- `test_endpoints.py`: 11 tests (health check + endpoint tests)
- `test_index.py`: 4 tests
- `test_reader.py`: 5 tests
- `test_time_machine.py`: 9 tests

**Test Fixtures (tests/conftest.py):**
- Mock current time to 2026-05-08 for predictable testing
- Test data: past and future calls with correct offsets
- Dynamic datetime mocking across all modules

**Key Implementation Notes:**
- Offset is recalculated every startup → data window advances daily
- No config file persistence needed
- Datetime operations use modern UTC (Python 3.9+ compatible)
- All 32 tests pass without deprecation warnings

---

## Phase 2: Archive Reader & Startup Indexing

**Branch:** `phase/2-archive-reader`

**Deliverables:**
1. Archive reader class using `python-xz` for random access
   - Open `.tar.xz` files from `ARCHIVE_ROOT/gong/{year}/{month}.tar.xz`
   - Extract individual `.metadata.jsonl` and `.tx.jsonl` files by member name
   - Handle both single-block (sequential decompress) and multi-block archives transparently
2. Startup index builder:
   - Scan all `.tar.xz` files in the archive directory
   - Parse `.metadata.jsonl` files to extract `call_id` and timestamps
   - Build in-memory dict: `CallID -> (tar_path, member_name)`
   - Handle missing archives gracefully (try/except, skip)
3. Error handling:
   - Malformed JSONL lines: skip with logging
   - Missing archives: log and continue
   - Timestamp parsing failures: skip record with logging

**Testing:**
- Verify index is built on startup
- Verify O(1) lookup works: `index["call_id"]` returns `(tar_path, member_name)`
- Test reading a specific `.metadata.jsonl` file from archive
- Test reading a specific `.tx.jsonl` file from archive
- Run with `/superpowers` to verify startup completes and index is accessible

**Prompt for Sonnet:**
```
Build Phase 2 of the Gong Archive API: Archive Reader & Startup Indexing.

Requirements:
1. In src/reader.py:
   - Create ArchiveReader class that uses python-xz to open .tar.xz files
   - Method: read_member(tar_path: str, member_name: str) -> str
     - Opens tar_path, extracts member_name, returns as string
     - Handle python-xz random access; if it fails, fall back to sequential decompress
   - Method: list_members(tar_path: str) -> list[str]
     - List all members in a .tar.xz file
2. In src/index.py:
   - Create build_index() function that:
     - Scans ARCHIVE_ROOT/gong/{year}/{month}.tar.xz for all archives
     - For each .tar.xz, reads all .metadata.jsonl files
     - Parses each line as JSON, extracts call_id
     - Builds dict: {call_id: (tar_path, member_name)}
   - Wraps archive reads in try/except to handle missing files gracefully
   - Wraps JSON parses in try/except to skip malformed lines
   - Wraps timestamp parses in try/except to skip unparseable records
   - Returns the index dict
3. In src/main.py startup event:
   - Call build_index() and store as a global (or use dependency injection)
   - Log: "Index built: {N} calls indexed"
4. Test with /superpowers:
   - Verify index builds without crashing
   - Verify a known call_id can be looked up in the index
   - Verify reading a .metadata.jsonl file works
   - Verify reading a .tx.jsonl file works
```

---

## Phase 3: Time Machine Logic (Remapping & Gating)

**Branch:** `phase/3-time-machine`

**Deliverables:**
1. Timestamp remapping function:
   - Input: ISO 8601 datetime string, TIME_OFFSET
   - Output: Remapped datetime (original date + TIME_OFFSET)
   - Use `dateutil.parser.parse()` for parsing (handles `Z` suffix)
   - Return as ISO 8601 string with `Z` suffix
2. Call gating logic:
   - Input: call record (dict), TIME_OFFSET
   - Check if call should be excluded based on `ended` or `started + duration`
   - Return boolean: include or exclude
3. Record remapping:
   - Input: call metadata record (dict), TIME_OFFSET
   - Remap all timestamp fields: `started`, `ended`, `scheduled`, etc.
   - Remap duration-derived end times if needed
   - Return remapped record
4. Error handling:
   - Skip records with unparseable timestamps (log and continue)
   - Handle missing fields gracefully (None checks)

**Testing:**
- Test timestamp remapping: `2024-05-03T10:00:00Z` + 730 days → `2026-05-08T10:00:00Z`
- Test gating: call with `ended` in past (before offset boundary) → include
- Test gating: call with `ended` in future (after offset boundary) → exclude
- Test record remapping: verify all date fields are shifted
- Run with `/superpowers` to verify logic with sample data

**Prompt for Sonnet:**
```
Build Phase 3 of the Gong Archive API: Time Machine Logic (Remapping & Gating).

Requirements:
1. In src/time_machine.py:
   - Function: remap_datetime(dt_str: str, offset_days: int) -> str
     - Parse dt_str using dateutil.parser.parse()
     - Add timedelta(days=offset_days)
     - Return as ISO 8601 string with Z suffix (e.g., "2026-05-08T10:00:00Z")
     - On parse error, return original string and log warning
   - Function: should_exclude_call(record: dict, offset_days: int) -> bool
     - Check if call should be excluded (gating logic):
       - If "ended" field exists: parse and add offset, check if > datetime.utcnow()
         - If yes, return True (exclude)
       - If "ended" missing: compute from started + metaData.duration
         - Add offset, check if > datetime.utcnow(), return True if so
       - Otherwise return False (include)
     - Handle missing fields gracefully
   - Function: remap_record(record: dict, offset_days: int) -> dict
     - Deep copy the record
     - Remap all datetime fields: started, ended, scheduled, etc.
     - Return remapped record
2. Test with /superpowers:
   - Verify timestamp remapping shifts date but keeps time of day
   - Verify gating excludes future calls
   - Verify gating includes past calls
```

---

## Phase 4: API Endpoints (Extensive & Transcript)

**Branch:** `phase/4-endpoints`

**Deliverables:**
1. `POST /v2/calls/extensive` endpoint:
   - Request: `{ "filter": { "fromDateTime": "...", "toDateTime": "..." } }`
   - Pre-check: Verify date range is not entirely in the future (return 400 if so)
   - Reverse-remap dates: `Historical_From = Request_From - TIME_OFFSET`, `Historical_To = Request_To - TIME_OFFSET`
   - Find all `.tar.xz` files overlapping the historical date range
   - Extract and parse `.metadata.jsonl` files
   - Apply TIME_OFFSET to each call
   - Apply gating logic (exclude future calls)
   - Return response with remapped calls
   - Error handling: malformed JSONL lines skip, missing archives skip, timestamp parse failures skip

2. `POST /v2/calls/transcript` endpoint:
   - Request: `{ "filter": { "callIds": ["..."] } }`
   - Look up each call ID in the index
   - Verify call is not in the future (return 404 if so)
   - Extract `.tx.jsonl` file from archive
   - Parse and return transcript (no timestamp remapping for transcript times)
   - If call not found: return 404 with error message
   - If call in future: return 404 with "not yet occurred" message

3. Request validation:
   - Pre-check for invalid date ranges (400)
   - Validate JSON structure
   - Return appropriate error responses with JSON format

4. Response structures:
   ```json
   // /v2/calls/extensive success
   {
     "calls": [
       {
         "id": "...",
         "started": "2026-05-06T10:00:00Z",
         "ended": "2026-05-06T11:00:00Z",
         "title": "...",
         "raw": { ... remapped fields ... }
       }
     ],
     "records": { "totalRecords": 1, "cursor": "" }
   }

   // /v2/calls/extensive error
   {
     "error": "Invalid date range",
     "message": "Requested date range is entirely in the future",
     "details": { "requested": "...", "offset": "..." }
   }

   // /v2/calls/transcript success
   {
     "callTranscripts": [
       {
         "callId": "...",
         "transcript": [
           { "speakerId": "...", "text": "...", "start_ms": 1000 }
         ]
       }
     ]
   }

   // /v2/calls/transcript error
   {
     "error": "Call not found",
     "message": "This call has not occurred yet"
   }
   ```

**Testing:**
- Test `/v2/calls/extensive` with valid date range → returns calls
- Test `/v2/calls/extensive` with future date range → returns 400
- Test `/v2/calls/transcript` with valid call ID → returns transcript
- Test `/v2/calls/transcript` with future call ID → returns 404
- Test `/v2/calls/transcript` with invalid call ID → returns 404
- Run with `/superpowers` to verify endpoints work end-to-end

**Prompt for Sonnet:**
```
Build Phase 4 of the Gong Archive API: API Endpoints (Extensive & Transcript).

Requirements:
1. In src/models.py:
   - Create Pydantic models for requests and responses:
     - ExtensiveRequest: { filter: { fromDateTime, toDateTime } }
     - ExtensiveResponse: { calls: [...], records: { totalRecords, cursor } }
     - TranscriptRequest: { filter: { callIds } }
     - TranscriptResponse: { callTranscripts: [...] }
     - ErrorResponse: { error, message, details? }

2. In src/endpoints.py:
   - Endpoint: POST /v2/calls/extensive
     - Parse request as ExtensiveRequest
     - Pre-check: reverse-remap dates, verify not entirely in future (return 400 if so)
     - Find all .tar.xz files overlapping historical date range
     - Extract .metadata.jsonl files, parse, remap, apply gating
     - Wrap JSONL parses in try/except, skip bad lines
     - Return ExtensiveResponse with remapped calls
   - Endpoint: POST /v2/calls/transcript
     - Parse request as TranscriptRequest
     - For each callId, look up in index
     - Verify call not in future (return 404 if so)
     - Extract .tx.jsonl file, parse, return
     - If call not found: return 404 with error
     - Return TranscriptResponse

3. In src/main.py:
   - Register endpoints
   - Include global index and config in dependency injection or app state

4. Error responses:
   - Invalid date range (400): structured error with details
   - Future single call (404): error message "This call has not occurred yet"
   - Malformed requests (400): standard validation error

5. Test with /superpowers:
   - Verify /v2/calls/extensive with valid range returns calls
   - Verify /v2/calls/extensive with future range returns 400
   - Verify /v2/calls/transcript with valid callId returns transcript
   - Verify /v2/calls/transcript with future callId returns 404
```

---

## Phase 5: End-to-End Test

**Branch:** `phase/5-e2e-test`

**Deliverables:**
1. End-to-end integration test:
   - Set up test fixtures with sample call data
   - Start FastAPI app
   - Call `/v2/calls/extensive` with sample date range
   - Verify remapped timestamps are correct
   - Verify gating logic works (future calls excluded)
   - Call `/v2/calls/transcript` with sample call ID
   - Verify transcript is returned correctly
   - Verify error responses are formatted correctly

2. Test cases:
   - Valid date range → returns calls with remapped timestamps
   - Future date range → returns 400 error
   - Valid call ID → returns transcript
   - Future call ID → returns 404 error
   - Invalid call ID → returns 404 error
   - Malformed request → returns 400 error

**Testing:**
- Run all tests with pytest
- Verify no crashes, all edge cases handled
- Run with `/superpowers` to verify

**Prompt for Sonnet:**
```
Build Phase 5 of the Gong Archive API: End-to-End Test.

Requirements:
1. Create tests/ directory with conftest.py and test_e2e.py
2. In tests/conftest.py:
   - Create pytest fixtures for:
     - Sample .metadata.jsonl data (past and future calls)
     - Sample .tx.jsonl data (transcripts)
     - Temporary archive directory with test .tar.xz files
3. In tests/test_e2e.py:
   - Test 1: POST /v2/calls/extensive with valid date range
     - Verify returns calls with remapped timestamps
     - Verify timestamps are shifted by offset but keep time of day
   - Test 2: POST /v2/calls/extensive with future date range
     - Verify returns 400 with error message
   - Test 3: POST /v2/calls/transcript with valid call ID
     - Verify returns transcript
   - Test 4: POST /v2/calls/transcript with future call ID
     - Verify returns 404 with error message
   - Test 5: POST /v2/calls/transcript with invalid call ID
     - Verify returns 404
   - Test 6: POST /v2/calls/extensive with malformed request
     - Verify returns 400
4. Run tests with pytest and verify all pass
```

---

## Testing Strategy

After each phase:
1. Write and run unit tests for the phase
2. Use `/superpowers` to test locally with sample data
3. Verify error handling works (try/except blocks catch edge cases)
4. Create a pull request from the phase branch to main
5. Review and merge before starting the next phase

## Dependencies

**requirements.txt:**
```
fastapi==0.104.1
uvicorn==0.24.0
python-dateutil==2.8.2
python-xz==0.6.4
pydantic==2.5.0
pytest==7.4.3
```

## Notes

- All timestamps in responses are ISO 8601 with `Z` suffix
- Transcript `start_ms` is relative to call start (not remapped)
- Call dates are NOT transformed; only the filtering boundary shifts
- **Offset is dynamic:** Recalculated fresh at each startup, advancing the data window daily
- No offset.json persistence — eliminates need for manual offset management or rebuilds
- All archive operations are wrapped in try/except (graceful degradation)
