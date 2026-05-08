import json
import pytest

@pytest.fixture
def config_with_archive(tmp_path, make_tar_xz, monkeypatch):
    gong = tmp_path / "gong" / "2024"
    gong.mkdir(parents=True)

    members = {
        "05/call001.metadata.jsonl": json.dumps({
            "metaData": {"id": "call001", "started": "2024-05-03T10:00:00Z",
                         "ended": "2024-05-03T11:00:00Z", "duration": 3600}
        }) + "\n",
        "05/call002.metadata.jsonl": json.dumps({
            "metaData": {"id": "call002", "started": "2024-05-04T10:00:00Z",
                         "ended": "2024-05-04T11:00:00Z", "duration": 3600}
        }) + "\n",
        "05/call001.tx.jsonl": '{"speakerId": "u1", "text": "Hello", "start_ms": 1000}\n',
    }
    (gong / "05.tar.xz").write_bytes(make_tar_xz(members))

    offset_file = tmp_path / "offset.json"
    monkeypatch.setenv("ARCHIVE_ROOT", str(tmp_path))
    monkeypatch.setenv("ARCHIVE_START_DATE", "2024-05-01")
    monkeypatch.setenv("VIRTUAL_START_DATE", "2026-05-06")
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "OFFSET_FILE", offset_file)
    return cfg_mod.Config()


def test_build_index_finds_all_calls(config_with_archive):
    from src.index import build_index
    index = build_index(config_with_archive)
    assert "call001" in index
    assert "call002" in index


def test_build_index_entry_structure(config_with_archive):
    from src.index import build_index
    index = build_index(config_with_archive)
    tar_path, member_name = index["call001"]
    assert tar_path.endswith("05.tar.xz")
    assert member_name == "05/call001.metadata.jsonl"


def test_build_index_skips_malformed_json(tmp_path, make_tar_xz, monkeypatch):
    gong = tmp_path / "gong" / "2024"
    gong.mkdir(parents=True)
    members = {
        "05/call003.metadata.jsonl": (
            "NOT_JSON\n" +
            json.dumps({"metaData": {"id": "call003", "started": "2024-05-05T10:00:00Z"}}) + "\n"
        ),
    }
    (gong / "05.tar.xz").write_bytes(make_tar_xz(members))

    offset_file = tmp_path / "offset.json"
    monkeypatch.setenv("ARCHIVE_ROOT", str(tmp_path))
    monkeypatch.setenv("ARCHIVE_START_DATE", "2024-05-01")
    monkeypatch.setenv("VIRTUAL_START_DATE", "2026-05-06")
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "OFFSET_FILE", offset_file)
    config = cfg_mod.Config()

    from src.index import build_index
    index = build_index(config)
    assert "call003" in index  # second (valid) line parsed successfully


def test_build_index_empty_when_no_archives(tmp_path, monkeypatch):
    offset_file = tmp_path / "offset.json"
    monkeypatch.setenv("ARCHIVE_ROOT", str(tmp_path))
    monkeypatch.setenv("ARCHIVE_START_DATE", "2024-05-01")
    monkeypatch.setenv("VIRTUAL_START_DATE", "2026-05-06")
    import src.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "OFFSET_FILE", offset_file)
    config = cfg_mod.Config()

    from src.index import build_index
    assert build_index(config) == {}
