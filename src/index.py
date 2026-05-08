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
