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
