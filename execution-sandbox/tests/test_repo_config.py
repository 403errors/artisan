"""Tests for repo_config.resolve: the `.artisan.toml` > manifest-detection > env-default
precedence, the full detection matrix, and the never-raise fallback contract (a bad config file
degrades to detection with a note — it must never crash an attempt)."""

from artisan_execution_sandbox import repo_config
from artisan_execution_sandbox.repo_config import RepoConfig

# --------------------------------------------------------------------------- .artisan.toml


def test_artisan_toml_wins_over_manifests(tmp_path) -> None:
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / ".artisan.toml").write_text(
        '[build]\ninstall = "make deps"\nbuild = "make build"\ntest = "make test"\n'
    )
    config = repo_config.resolve(tmp_path)
    assert config == RepoConfig("make deps", "make build", "make test", "config")


def test_artisan_toml_with_only_a_test_command(tmp_path) -> None:
    (tmp_path / ".artisan.toml").write_text('[build]\ntest = "./run_tests.sh"\n')
    config = repo_config.resolve(tmp_path)
    assert config.install_cmd is None
    assert config.build_cmd is None
    assert config.test_cmd == "./run_tests.sh"
    assert config.source == "config"


def test_services_section_is_tolerated_with_a_note(tmp_path) -> None:
    """The reserved [services] section parses and is ignored (deferred) — adding sidecar support
    later must not be a schema break for repos that already declare it."""
    (tmp_path / ".artisan.toml").write_text(
        '[build]\ntest = "pytest"\n\n[services]\ndb = "postgres:16"\n'
    )
    config = repo_config.resolve(tmp_path)
    assert config.source == "config"
    assert config.test_cmd == "pytest"
    assert "services" in config.note
    assert "ignored" in config.note


def test_malformed_toml_falls_back_to_detection_with_a_note(tmp_path) -> None:
    (tmp_path / ".artisan.toml").write_text("[build\nthis is not toml")
    (tmp_path / "go.mod").write_text("module example.com/x\n")
    config = repo_config.resolve(tmp_path)
    assert config.source == "detected"
    assert config.test_cmd == "go test ./..."
    assert "malformed" in config.note


def test_config_without_a_test_command_falls_back(tmp_path) -> None:
    (tmp_path / ".artisan.toml").write_text('[build]\ninstall = "npm ci"\n')
    (tmp_path / "package.json").write_text('{"scripts": {"test": "vitest"}}')
    config = repo_config.resolve(tmp_path)
    assert config.source == "detected"
    assert "no [build].test" in config.note


# --------------------------------------------------------------------------- detection matrix


def test_detects_npm_with_build_script(tmp_path) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {"build": "tsc", "test": "jest"}}')
    config = repo_config.resolve(tmp_path)
    assert config == RepoConfig("npm ci", "npm run build", "npm test", "detected")


def test_detects_pnpm_by_lockfile(tmp_path) -> None:
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    config = repo_config.resolve(tmp_path)
    assert config.install_cmd == "pnpm install --frozen-lockfile"
    assert config.build_cmd is None  # no build script declared
    assert config.test_cmd == "pnpm test"


def test_detects_yarn_by_lockfile(tmp_path) -> None:
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "yarn.lock").write_text("# yarn lockfile v1\n")
    config = repo_config.resolve(tmp_path)
    assert config.install_cmd == "yarn install --frozen"
    assert config.test_cmd == "yarn test"


def test_package_json_without_build_script_has_no_build_step(tmp_path) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {"test": "jest"}}')
    config = repo_config.resolve(tmp_path)
    assert config.build_cmd is None


def test_unparseable_package_json_is_treated_as_no_build_script(tmp_path) -> None:
    (tmp_path / "package.json").write_text("not json")
    config = repo_config.resolve(tmp_path)
    assert config.source == "detected"
    assert config.build_cmd is None
    assert config.test_cmd == "npm test"


def test_detects_pyproject(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    config = repo_config.resolve(tmp_path)
    assert config == RepoConfig("uv pip install --system -e .", None, "pytest", "detected")


def test_detects_requirements_txt(tmp_path) -> None:
    (tmp_path / "requirements.txt").write_text("flask\n")
    config = repo_config.resolve(tmp_path)
    assert config.install_cmd == "uv pip install --system -r requirements.txt"
    assert config.test_cmd == "pytest"


def test_detects_go(tmp_path) -> None:
    (tmp_path / "go.mod").write_text("module example.com/x\n")
    config = repo_config.resolve(tmp_path)
    assert config == RepoConfig("go mod download", "go build ./...", "go test ./...", "detected")


def test_detects_cargo(tmp_path) -> None:
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'x'\n")
    config = repo_config.resolve(tmp_path)
    assert config == RepoConfig(None, "cargo build", "cargo test", "detected")


def test_detects_maven(tmp_path) -> None:
    (tmp_path / "pom.xml").write_text("<project/>\n")
    config = repo_config.resolve(tmp_path)
    assert config == RepoConfig(None, None, "mvn -q test", "detected")


def test_detects_gradle(tmp_path) -> None:
    (tmp_path / "build.gradle").write_text("plugins { id 'java' }\n")
    config = repo_config.resolve(tmp_path)
    assert config == RepoConfig(None, None, "gradle test", "detected")


def test_detects_gradle_kotlin_dsl(tmp_path) -> None:
    (tmp_path / "build.gradle.kts").write_text("plugins { java }\n")
    config = repo_config.resolve(tmp_path)
    assert config.test_cmd == "gradle test"


# --------------------------------------------------------------------------- default fallback


def test_no_config_no_manifest_falls_back_to_env_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(repo_config, "DEMO_REPO_TEST_COMMAND", "make check")
    config = repo_config.resolve(tmp_path)
    assert config == RepoConfig(None, None, "make check", "default")
