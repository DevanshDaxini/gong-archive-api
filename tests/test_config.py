from datetime import UTC, datetime

from dateutil import parser as dateutil_parser


def test_config_calculates_dynamic_offset(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHIVE_ROOT", str(tmp_path / "archive"))
    monkeypatch.setenv("ARCHIVE_START_DATE", "2025-01-01")
    import src.config as cfg_mod

    config = cfg_mod.Config()

    # Offset should be calculated as (today - archive_start).days
    today = datetime.now(UTC).date()
    archive_start = dateutil_parser.parse("2025-01-01").date()
    expected_days = (today - archive_start).days
    assert config.offset_days == expected_days


def test_config_offset_is_fresh_on_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHIVE_ROOT", str(tmp_path / "archive"))
    monkeypatch.setenv("ARCHIVE_START_DATE", "2025-06-01")
    import src.config as cfg_mod

    config1 = cfg_mod.Config()
    config2 = cfg_mod.Config()

    # Both should calculate offset dynamically (could be same or differ by 1 if a day passed)
    # Main point: not persisted, recalculated each time
    assert isinstance(config1.offset_days, int)
    assert isinstance(config2.offset_days, int)
    # They should be close (within 1 day due to time passage during test)
    assert abs(config1.offset_days - config2.offset_days) <= 1


def test_config_archive_root_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHIVE_ROOT", str(tmp_path / "myarchive"))
    monkeypatch.setenv("ARCHIVE_START_DATE", "2025-01-01")
    import src.config as cfg_mod

    config = cfg_mod.Config()

    assert config.archive_root == tmp_path / "myarchive"
