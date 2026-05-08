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
