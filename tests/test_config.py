import json
from datetime import datetime


def test_config_creates_offset_file(tmp_path, monkeypatch):
    offset_file = tmp_path / "offset.json"
    archive_start = "2024-05-01"
    virtual_start = "2026-05-06"
    monkeypatch.setenv("ARCHIVE_ROOT", str(tmp_path / "archive"))
    monkeypatch.setenv("ARCHIVE_START_DATE", archive_start)
    monkeypatch.setenv("VIRTUAL_START_DATE", virtual_start)
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "OFFSET_FILE", offset_file)

    config = cfg_mod.Config()

    # expected offset is derived directly from the two env vars above
    expected_days = (datetime.fromisoformat(virtual_start) - datetime.fromisoformat(archive_start)).days
    assert offset_file.exists()
    assert json.loads(offset_file.read_text())["offset_days"] == expected_days
    assert config.offset_days == expected_days


def test_config_reads_existing_offset_ignores_env(tmp_path, monkeypatch):
    offset_file = tmp_path / "offset.json"
    offset_file.write_text('{"offset_days": 100}')
    monkeypatch.setenv("ARCHIVE_ROOT", str(tmp_path / "archive"))
    monkeypatch.setenv("ARCHIVE_START_DATE", "2024-05-01")
    monkeypatch.setenv("VIRTUAL_START_DATE", "2026-05-06")
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "OFFSET_FILE", offset_file)

    config = cfg_mod.Config()

    assert config.offset_days == 100  # persisted value wins over env-derived offset


def test_config_archive_root_from_env(tmp_path, monkeypatch):
    offset_file = tmp_path / "offset.json"
    monkeypatch.setenv("ARCHIVE_ROOT", str(tmp_path / "myarchive"))
    monkeypatch.setenv("ARCHIVE_START_DATE", "2024-05-01")
    monkeypatch.setenv("VIRTUAL_START_DATE", "2026-05-06")
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "OFFSET_FILE", offset_file)

    config = cfg_mod.Config()

    assert config.archive_root == tmp_path / "myarchive"
