import json
import pytest
from src.reader import ArchiveReader


@pytest.fixture
def sample_archive(tmp_path, make_tar_xz):
    members = {
        "05/call001.metadata.jsonl": json.dumps({"metaData": {"id": "call001"}}) + "\n",
        "05/call001.tx.jsonl": json.dumps({"speakerId": "u1", "text": "Hello", "start_ms": 1000}) + "\n",
        "05/call002.metadata.jsonl": json.dumps({"metaData": {"id": "call002"}}) + "\n",
    }
    p = tmp_path / "05.tar.xz"
    p.write_bytes(make_tar_xz(members))
    return p


def test_list_members_returns_all_files(sample_archive):
    reader = ArchiveReader()
    members = reader.list_members(str(sample_archive))
    assert "05/call001.metadata.jsonl" in members
    assert "05/call001.tx.jsonl" in members
    assert "05/call002.metadata.jsonl" in members


def test_read_member_returns_content(sample_archive):
    reader = ArchiveReader()
    content = reader.read_member(str(sample_archive), "05/call001.metadata.jsonl")
    assert json.loads(content.strip())["metaData"]["id"] == "call001"


def test_read_member_raises_on_missing(sample_archive):
    reader = ArchiveReader()
    with pytest.raises(FileNotFoundError):
        reader.read_member(str(sample_archive), "05/does-not-exist.jsonl")


def test_read_tx_member(sample_archive):
    reader = ArchiveReader()
    content = reader.read_member(str(sample_archive), "05/call001.tx.jsonl")
    assert json.loads(content.strip())["text"] == "Hello"


def test_fallback_sequential_path(sample_archive, monkeypatch):
    import src.reader as reader_mod
    monkeypatch.setattr(reader_mod, "_HAS_XZ", False)
    reader = ArchiveReader()
    members = reader.list_members(str(sample_archive))
    assert "05/call001.metadata.jsonl" in members
    content = reader.read_member(str(sample_archive), "05/call001.metadata.jsonl")
    assert "call001" in content
