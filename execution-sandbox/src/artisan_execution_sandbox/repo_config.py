"""Per-repo install/build/test configuration for the execution sandbox (Gate 2 exec-env
generalization). v1 ran one hardcoded command (config.DEMO_REPO_TEST_COMMAND) against the single
demo repo; any-repo support needs the commands to come from the repo itself. Resolution
precedence:

1. `.artisan.toml` at the checkout root — explicit, repo-checked-in:

       [build]
       install = "npm ci"          # optional — skipped when absent
       build   = "npm run build"   # optional — skipped when absent
       test    = "npm test"        # required — a config without it is treated as malformed

   A `[services]` section is reserved for future sidecar containers (databases etc.): it parses
   fine and is ignored with a note, so adding support later is not a schema break.

2. Manifest auto-detection at the checkout root (`_detect`) — package.json / pyproject.toml /
   requirements.txt / go.mod / Cargo.toml / pom.xml / build.gradle. Checkout-root only: monorepo
   affected-package scoping is a known, separate gap.
3. `config.DEMO_REPO_TEST_COMMAND` — the v1 behavior, kept as the last-resort default so
   deployments predating this resolution keep working unchanged.

A malformed `.artisan.toml` falls back to detection rather than failing the attempt — mirrors
main.py's always-return-data contract: config problems are data (surfaced via `RepoConfig.note`
in the ExecutionResult's diff_summary), never a sandbox crash.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from artisan_execution_sandbox.config import DEMO_REPO_TEST_COMMAND

CONFIG_FILENAME = ".artisan.toml"


@dataclass(frozen=True)
class RepoConfig:
    """The commands one attempt needs. `install_cmd`/`build_cmd` are None when the repo has no
    such step (interpreted as "not applicable", never as failure). `source` records where the
    resolution came from; `note` carries any caveat worth surfacing (malformed config, ignored
    [services] section) into logs and failure summaries."""

    install_cmd: str | None
    build_cmd: str | None
    test_cmd: str
    source: Literal["config", "detected", "default"]
    note: str = ""


def resolve(workdir: Path) -> RepoConfig:
    """Resolves the repo's install/build/test commands per the precedence above. Never raises —
    every config problem degrades to the next source with a note."""
    config_path = workdir / CONFIG_FILENAME
    if config_path.is_file():
        try:
            parsed = tomllib.loads(config_path.read_text())
        except (OSError, tomllib.TOMLDecodeError) as exc:
            note = f"malformed {CONFIG_FILENAME} ({exc}) — fell back to manifest detection"
        else:
            config = _from_toml(parsed)
            if config is not None:
                return config
            note = f"{CONFIG_FILENAME} has no [build].test command — fell back to manifest detection"
        detected = _detect(workdir)
        if detected is not None:
            return replace(detected, note=note)
        return RepoConfig(None, None, DEMO_REPO_TEST_COMMAND, "default", note=note)

    detected = _detect(workdir)
    if detected is not None:
        return detected
    return RepoConfig(None, None, DEMO_REPO_TEST_COMMAND, "default")


def _from_toml(parsed: dict) -> RepoConfig | None:
    build = parsed.get("build")
    if not isinstance(build, dict) or not build.get("test"):
        return None
    note = ""
    if "services" in parsed:
        note = "[services] section ignored — service containers are not supported yet (deferred)"
    return RepoConfig(
        install_cmd=_optional_command(build.get("install")),
        build_cmd=_optional_command(build.get("build")),
        test_cmd=str(build["test"]),
        source="config",
        note=note,
    )


def _optional_command(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _detect(workdir: Path) -> RepoConfig | None:
    if (workdir / "package.json").is_file():
        pm = _node_package_manager(workdir)
        install = {
            "npm": "npm ci",
            "pnpm": "pnpm install --frozen-lockfile",
            "yarn": "yarn install --frozen",
        }[pm]
        build_cmd = f"{pm} run build" if _package_json_has_script(workdir, "build") else None
        return RepoConfig(install, build_cmd, f"{pm} test", "detected")
    if (workdir / "pyproject.toml").is_file():
        return RepoConfig("uv pip install --system -e .", None, "pytest", "detected")
    if (workdir / "requirements.txt").is_file():
        return RepoConfig("uv pip install --system -r requirements.txt", None, "pytest", "detected")
    if (workdir / "go.mod").is_file():
        return RepoConfig("go mod download", "go build ./...", "go test ./...", "detected")
    if (workdir / "Cargo.toml").is_file():
        # cargo resolves/downloads dependencies as part of build/test — no separate install step.
        return RepoConfig(None, "cargo build", "cargo test", "detected")
    if (workdir / "pom.xml").is_file():
        # Maven's test phase compiles first — the build signal is inside the test command.
        return RepoConfig(None, None, "mvn -q test", "detected")
    if (workdir / "build.gradle").is_file() or (workdir / "build.gradle.kts").is_file():
        return RepoConfig(None, None, "gradle test", "detected")
    return None


def _node_package_manager(workdir: Path) -> Literal["npm", "pnpm", "yarn"]:
    if (workdir / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (workdir / "yarn.lock").is_file():
        return "yarn"
    return "npm"


def _package_json_has_script(workdir: Path, script: str) -> bool:
    try:
        package = json.loads((workdir / "package.json").read_text())
    except (OSError, json.JSONDecodeError):
        return False
    scripts = package.get("scripts")
    return isinstance(scripts, dict) and script in scripts
