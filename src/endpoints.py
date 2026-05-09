import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dateutil import parser as dateutil_parser
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.models import ExtensiveRequest, TranscriptRequest
from src.reader import ArchiveReader
from src.time_machine import remap_record, should_exclude_call

logger = logging.getLogger(__name__)
router = APIRouter()


def _wrap_call_record(remapped_record: dict) -> dict:
    meta = remapped_record.get("metaData", remapped_record)
    return {
        "id": meta.get("id"),
        "started": meta.get("started"),
        "ended": meta.get("ended"),
        "title": meta.get("title"),
        "raw": remapped_record,
    }


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

    try:
        from_dt = dateutil_parser.parse(body.filter.fromDateTime).replace(tzinfo=None)
        to_dt = dateutil_parser.parse(body.filter.toDateTime).replace(tzinfo=None)
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Invalid date range",
                "message": "fromDateTime or toDateTime could not be parsed",
                "details": {
                    "fromDateTime": body.filter.fromDateTime,
                    "toDateTime": body.filter.toDateTime,
                },
            },
        )
    hist_from = from_dt - timedelta(days=offset)
    hist_to = to_dt - timedelta(days=offset)

    if hist_from > datetime.now(UTC).replace(tzinfo=None):
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
                        remapped = remap_record(record, offset)
                        calls.append(_wrap_call_record(remapped))
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
