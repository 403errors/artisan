"""Shared helpers for the eval harnesses' markdown reports.

Each harness keeps its own metric computation (they genuinely differ per stage); this module
owns only the identical plumbing: percentage formatting and the report/sidecar write-and-print
call-site pattern.
"""

import json
from pathlib import Path


def pct(value: float | None, *, digits: int = 0) -> str:
    """Format an optional ratio as a percentage, em-dash when undefined."""
    return "—" if value is None else f"{value:.{digits}%}"


def emit_report(report_path: Path, sidecar_path: Path, report: str, sidecar: dict) -> None:
    """Write the markdown report + JSON sidecar and echo the report to stdout."""
    report_path.write_text(report)
    sidecar_path.write_text(json.dumps(sidecar, indent=2))
    print(f"\n{report}")
