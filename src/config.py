import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from dateutil import parser as dateutil_parser

logger = logging.getLogger(__name__)


class Config:
    def __init__(self) -> None:
        self.archive_root = Path(
            os.environ.get("ARCHIVE_ROOT", str(Path.home() / ".archive"))
        )
        # ARCHIVE_START_DATE: real date your oldest call data begins (e.g. "2025-01-01")
        # TIME_OFFSET is calculated fresh at every startup:
        # TIME_OFFSET = (today - ARCHIVE_START_DATE).days
        archive_start_str = os.environ.get("ARCHIVE_START_DATE", "2025-01-01")
        archive_start = dateutil_parser.parse(archive_start_str).replace(tzinfo=None).date()

        self.offset_days: int = (datetime.now(UTC).date() - archive_start).days
        logger.info(
            f"TIME_OFFSET: {self.offset_days} days (calculated from ARCHIVE_START_DATE: {archive_start_str})"
        )
