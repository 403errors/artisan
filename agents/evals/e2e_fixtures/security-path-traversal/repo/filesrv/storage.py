"""Serves user-uploaded files by name from the upload directory."""

import os
from pathlib import Path

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads"))


def read_user_file(name: str) -> str:
    """Reads a file from the upload directory by its name."""
    return (UPLOAD_DIR / name).read_text()


def write_user_file(name: str, content: str) -> None:
    """Writes content to a file in the upload directory, creating it if needed."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / name).write_text(content)
