"""Pre-push security scan gate (Workstream 6): a secrets scan (gitleaks) and a static-analysis
scan (semgrep) run against the working tree between `git_ops.commit_all(...)` and
`git_ops.push(...)` in main.py's `run_attempt`/`run_conflict_resolution`. Mirrors
test_runner.py's plain-list-of-args `subprocess.run` style — no `shell=True`, no exceptions raised
for expected failure modes.

Both scanners fail OPEN on tool malfunction (missing binary, unparseable output, etc.) — a broken
or absent scanner must never block every push. They only fail CLOSED on an actual finding."""

import json
import os
import subprocess

_DEPENDENCY_MANIFESTS = (
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "go.mod",
    "Cargo.toml",
)


def scan_secrets(repo_dir: str) -> tuple[bool, str]:
    """Runs gitleaks against the working tree. Returns (clean, findings_text).

    `--exit-code 0` makes gitleaks always exit zero even when it finds secrets — cleanliness is
    determined by parsing its JSON stdout, not its exit code, so a nonzero exit here means "the
    tool itself broke" (fail open), never "secrets were found" (fail closed)."""
    try:
        result = subprocess.run(
            ["gitleaks", "detect", "--source", repo_dir, "--no-git", "-f", "json", "--exit-code", "0"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return True, "gitleaks unavailable, scan skipped"

    if result.returncode != 0:
        # The tool itself malfunctioned (bad flags, crash, etc.) — fail open rather than block
        # every push over a broken scanner.
        return True, "gitleaks unavailable, scan skipped"

    try:
        findings = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        return True, "gitleaks unavailable, scan skipped"

    if not findings:
        return True, ""

    lines = [
        f"- {f.get('RuleID', 'unknown rule')} in {f.get('File', 'unknown file')}:"
        f"{f.get('StartLine', '?')}"
        for f in findings
    ]
    return False, "\n".join(lines)


def scan_static(repo_dir: str) -> tuple[bool, str]:
    """Runs semgrep's security-audit ruleset against the working tree. Returns (ok, findings_text).
    Only ERROR-severity findings make `ok=False`; WARNING/INFO findings are returned as
    non-blocking text so the caller can surface them without failing the scan."""
    try:
        result = subprocess.run(
            ["semgrep", "--config=p/security-audit", "--json", "--quiet", repo_dir],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return True, "semgrep unavailable, scan skipped"

    try:
        payload = json.loads(result.stdout) if result.stdout.strip() else {}
        results = payload.get("results", [])
    except json.JSONDecodeError:
        return True, "semgrep unavailable, scan skipped"

    errors = []
    warnings = []
    for r in results:
        severity = (r.get("extra") or {}).get("severity", "")
        path = r.get("path", "unknown file")
        line = (r.get("start") or {}).get("line", "?")
        check_id = r.get("check_id", "unknown rule")
        summary = f"- {check_id} in {path}:{line}"
        if severity == "ERROR":
            errors.append(summary)
        elif severity in ("WARNING", "INFO"):
            warnings.append(summary)

    if errors:
        return False, "\n".join(errors)
    return True, "\n".join(warnings)


def scan_new_dependencies(repo_dir: str) -> list[str]:
    """Best-effort, never raises. Returns short strings describing newly-added dependencies in any
    changed manifest file (package.json/requirements.txt/pyproject.toml/go.mod/Cargo.toml) at the
    root of `repo_dir`. Purely informational — never blocks anything."""
    try:
        return _scan_new_dependencies(repo_dir)
    except Exception:  # noqa: BLE001 - documented best-effort contract ("never raises")
        return []


def _scan_new_dependencies(repo_dir: str) -> list[str]:
    try:
        changed = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        changed_files = set(changed.stdout.splitlines()) if changed.returncode == 0 else set()
    except Exception:  # noqa: BLE001 - fail open on git tooling issues
        changed_files = set()

    findings: list[str] = []
    for manifest in _DEPENDENCY_MANIFESTS:
        path = os.path.join(repo_dir, manifest)
        if not os.path.isfile(path):
            continue
        if changed_files and manifest not in changed_files:
            continue

        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                new_content = f.read()
        except OSError:
            continue

        try:
            old = subprocess.run(
                ["git", "show", f"HEAD~1:{manifest}"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            old_content = old.stdout if old.returncode == 0 else ""
        except Exception:  # noqa: BLE001 - fail open on git tooling issues
            old_content = ""

        old_lines = set(old_content.splitlines())
        new_lines = [line for line in new_content.splitlines() if line not in old_lines]

        for line in _added_dependency_lines(manifest, new_lines):
            findings.append(f"added dependency: {line} ({manifest})")

    return findings


def _added_dependency_lines(manifest: str, lines: list[str]) -> list[str]:
    """Pragmatic, best-effort extraction of dependency-looking names from added lines — not a
    full package-manager-aware parser."""
    names: list[str] = []
    if manifest == "requirements.txt":
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            names.append(stripped)
    elif manifest == "package.json":
        for line in lines:
            stripped = line.strip().strip(",")
            if ":" not in stripped:
                continue
            key = stripped.split(":", 1)[0].strip().strip('"')
            if not key or key in ("dependencies", "devDependencies"):
                continue
            names.append(key)
    else:
        # pyproject.toml/go.mod/Cargo.toml: keep it simple — surface any non-empty added line
        # that isn't an obvious section header.
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith(("[", "#")):
                continue
            names.append(stripped)
    return names
