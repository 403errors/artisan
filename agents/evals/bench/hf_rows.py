"""Minimal HuggingFace datasets-server /rows client — pure stdlib (urllib), no hub dependency.

The bench tooling only needs to READ small public datasets (50 frozen rows per benchmark), so a
full `datasets`/`huggingface_hub` install would be overkill. Gated datasets (HTTP 401/403) raise
GatedDatasetError with instructions rather than a raw HTTP error.
"""

import concurrent.futures
import http.client
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

_ROWS_URL = "https://datasets-server.huggingface.co/rows"
_PAGE = 100  # datasets-server max rows per request


def _ssl_context() -> ssl.SSLContext | None:
    """macOS framework Pythons ship without CA roots (the "Install Certificates.command" gap) —
    use certifi's bundle when it's around (it is, in the uv workspace venv), else the default."""
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


class GatedDatasetError(RuntimeError):
    pass


def _open(request: urllib.request.Request, *, timeout: int = 120, retries: int = 3) -> bytes:
    """urlopen + read with retries — HF intermittently truncates big JSONL bodies
    (IncompleteRead), which surfaces during read(), not urlopen()."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
                return response.read()
        except urllib.error.HTTPError:
            raise  # deterministic (401/403/404/500) — never retry; callers map these
        except (http.client.IncompleteRead, TimeoutError, ConnectionError, urllib.error.URLError) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"fetch failed after {retries} attempts: {request.full_url}: {last}")


def _get_json(url: str, token: str | None = None):
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    return json.loads(_open(request, timeout=60))


def fetch_jsonl_tree(dataset: str, *, token: str | None = None) -> list[dict]:
    """Fetches every row from a dataset stored as a tree of per-language JSONL files
    (Multi-SWE-bench's layout: <lang>/<org>__<repo>_dataset.jsonl) — such datasets aren't
    indexed by the datasets-server, so the /rows API 500s on them."""
    token = token or os.environ.get("HF_TOKEN")
    # The dataset id is part of the URL *path* here — its "/" separator must survive quoting.
    api = f"https://huggingface.co/api/datasets/{urllib.parse.quote(dataset, safe='/')}"
    try:
        top = _get_json(f"{api}/tree/main", token)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise GatedDatasetError(
                f"{dataset} is gated on HuggingFace — accept its terms in the browser, create a "
                f"token at https://huggingface.co/settings/tokens, and re-run with HF_TOKEN=..."
            ) from exc
        raise
    # Collect all (lang, path) pairs first, then download in parallel — sequential fetches of
    # dozens of multi-MB JSONL files took ~25 min; a small thread pool cuts it to minutes.
    targets: list[tuple[str, str]] = []
    for entry in top:
        if entry["type"] != "directory":
            continue
        lang = entry["path"]
        for file_entry in _get_json(f"{api}/tree/main/{lang}", token):
            if file_entry["path"].endswith(".jsonl"):
                targets.append((lang, file_entry["path"]))

    def download(target: tuple[str, str]) -> list[dict]:
        lang, path = target
        url = f"https://huggingface.co/datasets/{urllib.parse.quote(dataset, safe='/')}/resolve/main/{path}"
        request = urllib.request.Request(url)
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        out = []
        for line in _open(request).decode().splitlines():
            if line.strip():
                row = json.loads(line)
                row["_language"] = lang
                out.append(row)
        return out

    rows: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for out in pool.map(download, targets):
            rows.extend(out)
    return rows


def fetch_rows(dataset: str, config: str, split: str, *, token: str | None = None) -> list[dict]:
    """Fetches every row of a dataset split as a list of dicts (the row's own fields)."""
    token = token or os.environ.get("HF_TOKEN")
    rows: list[dict] = []
    offset = 0
    total = None
    while total is None or offset < total:
        query = urllib.parse.urlencode(
            {"dataset": dataset, "config": config, "split": split,
             "offset": offset, "length": _PAGE}
        )
        request = urllib.request.Request(f"{_ROWS_URL}?{query}")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            payload = json.loads(_open(request, timeout=60))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise GatedDatasetError(
                    f"{dataset} is gated on HuggingFace — accept its terms in the browser, "
                    f"create a token at https://huggingface.co/settings/tokens, and re-run with "
                    f"HF_TOKEN=... in the environment."
                ) from exc
            raise
        total = payload["num_rows_total"]
        rows.extend(entry["row"] for entry in payload["rows"])
        if not payload["rows"]:
            break
        offset += len(payload["rows"])
    return rows
