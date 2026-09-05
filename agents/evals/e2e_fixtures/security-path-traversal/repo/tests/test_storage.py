import pytest

from filesrv import storage


@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path / "uploads")
    storage.UPLOAD_DIR.mkdir()
    return storage.UPLOAD_DIR


def test_read_roundtrip(upload_dir):
    storage.write_user_file("hello.txt", "hi there")
    assert storage.read_user_file("hello.txt") == "hi there"


def test_traversal_is_rejected(upload_dir):
    # Repro for the reported issue: names escaping the upload dir must be refused.
    (upload_dir.parent / "secret.txt").write_text("top secret")
    with pytest.raises(ValueError):
        storage.read_user_file("../secret.txt")


def test_missing_file_raises_file_not_found(upload_dir):
    with pytest.raises(FileNotFoundError):
        storage.read_user_file("nope.txt")
