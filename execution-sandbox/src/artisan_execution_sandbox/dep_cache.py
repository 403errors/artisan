"""GCS-backed dependency cache (Gate 2 exec-env generalization). Every attempt is a fresh clone
in a fresh container (gate2.py's retry loop triggers a new Cloud Run Job execution per attempt),
so without a cache each attempt cold-installs node_modules / site-packages / cargo crates — the
dominant attempt-latency cost on real repos. This module tars dependency directories keyed by the
repo's lockfile hash: a retry (or a future ticket on the same repo with unchanged deps) restores
a warm cache instead of re-downloading the internet.

Two kinds of cached content, with different semantics:
- repo-local dirs (`node_modules`, `.venv`) are FINAL install state — when one restores, main.py
  skips the install step entirely (sound because the key is the lockfile hash: the tar was
  created from a post-install state with byte-identical lockfiles).
- home dirs (uv/yarn/pnpm/cargo/go/maven/gradle caches) are WARM CACHES — install still runs,
  just fast. They never justify skipping install (e.g. `uv pip install --system` lands in
  site-packages, which is neither a repo dir nor cached).

Strictly best-effort: every failure is logged and swallowed — a cache problem must never fail an
attempt (mirrors main.py's always-return-data contract). Disabled entirely when
ARTISAN_DEP_CACHE_BUCKET is unset (local dev, tests).

Tarball layout (paths relative to two roots):
  repo/<dir>   -> extracted under the checkout (node_modules, .venv)
  home/<dir>   -> extracted under $HOME (toolchain caches)
"""

import hashlib
import os
import tarfile
import tempfile
from pathlib import Path

from artisan_execution_sandbox.config import DEP_CACHE_BUCKET

# Lockfiles whose contents form the cache key — any dependency change invalidates the cache.
_LOCKFILES = (
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "requirements.txt",
    "uv.lock",
    "go.sum",
    "Cargo.lock",
    "pom.xml",
)

# Final install state, relative to the checkout. Restoring one of these lets main.py skip the
# install step.
_REPO_DIRS = ("node_modules", ".venv")

# Toolchain caches, relative to $HOME. Restored for warmth only — install still runs.
_HOME_DIRS = (
    ".cache/uv",
    ".cache/yarn",
    ".local/share/pnpm",
    ".cargo/registry",
    ".cache/go-build",
    "go/pkg/mod",
    ".m2",
    ".gradle",
)


def current_key(workdir: Path) -> str | None:
    """sha256 over the sorted (name, content) of every lockfile present. None when the repo has
    no lockfiles — there's nothing sensible to key a cache on, so caching is skipped."""
    digest = hashlib.sha256()
    found = False
    for name in _LOCKFILES:
        path = workdir / name
        try:
            if path.is_file():
                found = True
                digest.update(name.encode())
                digest.update(path.read_bytes())
        except OSError:
            return None
    return digest.hexdigest() if found else None


def restore(workdir: Path, repo: str) -> list[str]:
    """Downloads and extracts the cache tarball for the repo's current lockfile hash. Returns the
    repo-local dep dirs that were restored (e.g. ["node_modules"]) — a non-empty return means
    main.py may skip the install step. Empty on disabled, miss, or any error."""
    if not DEP_CACHE_BUCKET:
        return []
    key = current_key(workdir)
    if key is None:
        return []
    try:
        from google.api_core.exceptions import NotFound

        blob = _client().bucket(DEP_CACHE_BUCKET).blob(_object_name(repo, key))
        with tempfile.TemporaryFile() as tmp:
            try:
                blob.download_to_file(tmp)
            except NotFound:
                return []  # cache miss — the normal cold-start case, not an error
            tmp.seek(0)
            restored = _extract(tmp, workdir)
        if restored:
            print(f"[artisan-execution-sandbox] dep cache hit: restored {restored}")
        return restored
    except Exception as exc:  # noqa: BLE001 — best-effort by design
        print(f"[artisan-execution-sandbox] dep cache restore failed (ignored): {exc}")
        return []


def save(workdir: Path, repo: str, *, skip_key: str | None = None) -> str | None:
    """Tars existing dep dirs and uploads them under the repo's current lockfile hash. Returns
    the cache key on a successful save, None otherwise. No-op (returning skip_key) when the
    lockfiles haven't changed since a previous save/restore this attempt — the cached tarball
    under that key already reflects this exact dependency state."""
    if not DEP_CACHE_BUCKET:
        return None
    key = current_key(workdir)
    if key is None:
        return None
    if skip_key is not None and key == skip_key:
        return skip_key
    try:
        with tempfile.TemporaryFile() as tmp:
            added = _archive(workdir, tmp)
            if not added:
                return None  # no dep dirs exist — nothing worth storing
            tmp.seek(0)
            _client().bucket(DEP_CACHE_BUCKET).blob(_object_name(repo, key)).upload_from_file(tmp)
        print(f"[artisan-execution-sandbox] dep cache saved: {added}")
        return key
    except Exception as exc:  # noqa: BLE001 — best-effort by design
        print(f"[artisan-execution-sandbox] dep cache save failed (ignored): {exc}")
        return None


def _object_name(repo: str, key: str) -> str:
    return f"{repo}/{key}.tar.gz"


def _client():
    # Constructed per call (the job is short-lived; connection pooling buys nothing) and a
    # separate function so tests can monkeypatch it without a real GCP project.
    from google.cloud import storage

    return storage.Client()


def _archive(workdir: Path, dest) -> list[str]:
    """Writes the tar.gz of all existing dep dirs into `dest` (a seekable file). Returns the
    archived dir names — empty means nothing existed and the caller skips the upload."""
    added: list[str] = []
    home = Path.home()
    with tarfile.open(fileobj=dest, mode="w:gz") as tar:
        for name in _REPO_DIRS:
            path = workdir / name
            if path.exists():
                tar.add(path, arcname=f"repo/{name}")
                added.append(name)
        for name in _HOME_DIRS:
            path = home / name
            if path.exists():
                tar.add(path, arcname=f"home/{name}")
                added.append(name)
    return added


def _extract(source, workdir: Path) -> list[str]:
    """Extracts a cache tarball read from `source` (a seekable file). repo/ entries land under
    the checkout, home/ entries under $HOME. Returns the repo-local dep dirs restored. The
    "data" filter refuses absolute/parent-escaping members — the bucket is private and the tar
    is our own, but defense in depth is free here."""
    restored: list[str] = []
    home = Path.home()
    with tarfile.open(fileobj=source, mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.name.startswith("repo/"):
                member.name = member.name[len("repo/"):]
                tar.extract(member, workdir, filter="data")
                top = member.name.split("/", 1)[0]
                if top in _REPO_DIRS and top not in restored:
                    restored.append(top)
            elif member.name.startswith("home/"):
                member.name = member.name[len("home/"):]
                tar.extract(member, home, filter="data")
    return restored
