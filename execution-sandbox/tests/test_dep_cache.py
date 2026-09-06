"""Tests for dep_cache: lockfile-key derivation, the disabled/best-effort contract (a cache
problem must never fail an attempt), the skip_key no-op, and a save/restore round-trip against a
fake in-memory GCS client."""

import shutil
from pathlib import Path

import pytest
from artisan_execution_sandbox import dep_cache


class _FakeBlob:
    def __init__(self, store: dict, name: str) -> None:
        self._store = store
        self._name = name

    def download_to_file(self, fileobj) -> None:
        from google.api_core.exceptions import NotFound

        if self._name not in self._store:
            raise NotFound("cache miss")
        fileobj.write(self._store[self._name])

    def upload_from_file(self, fileobj) -> None:
        self._store[self._name] = fileobj.read()


class _FakeClient:
    def __init__(self, store: dict) -> None:
        self._store = store

    def bucket(self, _name: str) -> "_FakeBucket":
        store = self._store

        class _FakeBucket:
            def blob(self, name: str) -> _FakeBlob:
                return _FakeBlob(store, name)

        return _FakeBucket()


@pytest.fixture
def store() -> dict:
    return {}


@pytest.fixture(autouse=True)
def fake_gcs(monkeypatch, store) -> None:
    monkeypatch.setattr(dep_cache, "DEP_CACHE_BUCKET", "test-bucket")
    monkeypatch.setattr(dep_cache, "_client", lambda: _FakeClient(store))


@pytest.fixture(autouse=True)
def fake_home(monkeypatch, tmp_path) -> Path:
    """dep_cache tars toolchain caches found under Path.home() — without this, a test save would
    archive the developer's REAL ~/.cache/uv / ~/go/pkg/mod (multi-GB, effectively a hang). Every
    test gets a hermetic, per-test home directory."""
    home = tmp_path / "fake_home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


# --------------------------------------------------------------------------- key derivation


def test_current_key_is_stable_and_content_sensitive(tmp_path) -> None:
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion": 3}')
    key1 = dep_cache.current_key(tmp_path)
    assert key1 == dep_cache.current_key(tmp_path)

    (tmp_path / "package-lock.json").write_text('{"lockfileVersion": 3, "changed": true}')
    assert dep_cache.current_key(tmp_path) != key1


def test_current_key_ignores_non_lockfiles(tmp_path) -> None:
    (tmp_path / "package-lock.json").write_text("x")
    key = dep_cache.current_key(tmp_path)
    (tmp_path / "README.md").write_text("not a lockfile")
    assert dep_cache.current_key(tmp_path) == key


def test_current_key_is_none_without_lockfiles(tmp_path) -> None:
    (tmp_path / "main.py").write_text("print('hi')")
    assert dep_cache.current_key(tmp_path) is None


# --------------------------------------------------------------------------- disabled / best-effort


def test_cache_is_disabled_when_bucket_is_unset(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(dep_cache, "DEP_CACHE_BUCKET", "")
    (tmp_path / "package-lock.json").write_text("x")
    assert dep_cache.restore(tmp_path, "acme/demo") == []
    assert dep_cache.save(tmp_path, "acme/demo") is None


def test_client_errors_are_swallowed(monkeypatch, tmp_path) -> None:
    def boom():
        raise RuntimeError("GCS is down")

    monkeypatch.setattr(dep_cache, "_client", boom)
    (tmp_path / "package-lock.json").write_text("x")
    assert dep_cache.restore(tmp_path, "acme/demo") == []
    assert dep_cache.save(tmp_path, "acme/demo") is None


def test_cache_miss_restores_nothing(tmp_path) -> None:
    (tmp_path / "package-lock.json").write_text("x")
    assert dep_cache.restore(tmp_path, "acme/demo") == []


def test_save_is_a_no_op_when_lockfiles_match_skip_key(tmp_path, store) -> None:
    (tmp_path / "package-lock.json").write_text("x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lodash.js").write_text("module.exports = 1")
    key = dep_cache.current_key(tmp_path)

    result = dep_cache.save(tmp_path, "acme/demo", skip_key=key)

    assert result == key
    assert dep_cache._object_name("acme/demo", key) not in store  # nothing uploaded


def test_save_without_dep_dirs_uploads_nothing(tmp_path, store) -> None:
    (tmp_path / "package-lock.json").write_text("x")
    assert dep_cache.save(tmp_path, "acme/demo") is None
    assert store == {}


# --------------------------------------------------------------------------- round-trip


def test_save_then_restore_round_trips_repo_local_dirs(tmp_path, store) -> None:
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text('{"lockfileVersion": 3}')
    (tmp_path / "node_modules" / "lodash").mkdir(parents=True)
    (tmp_path / "node_modules" / "lodash" / "index.js").write_text("module.exports = {}")

    key = dep_cache.save(tmp_path, "acme/demo")
    assert key is not None
    assert dep_cache._object_name("acme/demo", key) in store

    # A fresh checkout with the same lockfile (the retry-attempt shape) restores node_modules.
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "package-lock.json").write_text('{"lockfileVersion": 3}')

    restored = dep_cache.restore(fresh, "acme/demo")

    assert restored == ["node_modules"]
    assert (fresh / "node_modules" / "lodash" / "index.js").read_text() == "module.exports = {}"


def test_restore_with_changed_lockfile_is_a_miss(tmp_path, store) -> None:
    (tmp_path / "package-lock.json").write_text("v1")
    (tmp_path / "node_modules").mkdir()
    dep_cache.save(tmp_path, "acme/demo")

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "package-lock.json").write_text("v2 — deps changed")

    assert dep_cache.restore(fresh, "acme/demo") == []
    assert not (fresh / "node_modules").exists()


def test_home_cache_dirs_round_trip_without_counting_as_install_state(
    tmp_path, store, fake_home
) -> None:
    """Toolchain caches under $HOME (e.g. uv's) are restored for warmth but must NOT count as
    restored repo-local install state — `uv pip install --system` lands in site-packages, which
    is not cached, so main.py must still run the install step."""
    (fake_home / ".cache" / "uv").mkdir(parents=True)
    (fake_home / ".cache" / "uv" / "wheel.whl").write_text("bytes")

    workdir = tmp_path / "checkout"
    workdir.mkdir()
    (workdir / "requirements.txt").write_text("flask\n")

    key = dep_cache.save(workdir, "acme/demo")
    assert key is not None

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "requirements.txt").write_text("flask\n")
    shutil.rmtree(fake_home / ".cache")  # wipe the warm cache — restore must bring it back

    restored = dep_cache.restore(fresh, "acme/demo")

    assert restored == []  # home dirs only — install must still run
    assert (fake_home / ".cache" / "uv" / "wheel.whl").read_text() == "bytes"
