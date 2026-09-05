"""Held-out oracle tests — injected by the eval harness AFTER the pipeline finishes, never
visible to the coding agent. They fail on the seeded bug and pass on a correct fix."""

import pytest

from filesrv import storage


@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path / "uploads")
    storage.UPLOAD_DIR.mkdir()
    (tmp_path / "secret.txt").write_text("top secret")
    return storage.UPLOAD_DIR


@pytest.mark.parametrize(
    "name",
    ["../secret.txt", "../../secret.txt", "sub/../../secret.txt", "/etc/passwd"],
)
def test_traversal_variants_rejected(upload_dir, name):
    with pytest.raises(ValueError):
        storage.read_user_file(name)


def test_normal_names_still_work(upload_dir):
    storage.write_user_file("report.csv", "a,b,c")
    assert storage.read_user_file("report.csv") == "a,b,c"


def test_write_also_rejects_traversal(upload_dir):
    with pytest.raises(ValueError):
        storage.write_user_file("../evil.txt", "pwned")
