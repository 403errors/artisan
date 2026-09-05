"""Unit tests for the bench runner's pure helpers (no Docker, no network, no Gemini)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals" / "bench"))

from registry import BENCHMARKS
from runner import (
    container_workdir,
    image_for,
    infer_test_command,
    internal_test_command,
    load_done,
    patch_test_files,
)

TEST_PATCH = """\
diff --git a/django/db/models/query.py b/django/db/models/query.py
index abc..def 100644
--- a/django/db/models/query.py
+++ b/django/db/models/query.py
@@ -1,1 +1,1 @@
-x
+y
diff --git a/tests/queries/test_qs.py b/tests/queries/test_qs.py
index abc..def 100644
--- a/tests/queries/test_qs.py
+++ b/tests/queries/test_qs.py
@@ -1,1 +1,1 @@
-old
+new
diff --git a/tests/queries/__pycache__/test_qs.cpython-39.pyc b/tests/queries/__pycache__/test_qs.cpython-39.pyc
index abc..def 100644
--- a/tests/queries/__pycache__/test_qs.cpython-39.pyc
+++ b/tests/queries/__pycache__/test_qs.cpython-39.pyc
@@ -1,1 +1,1 @@
-bin
+bin
"""


def _instance(**overrides):
    base = {
        "instance_id": "django__django-16379",
        "repo": "django/django",
        "base_commit": "abc123",
        "problem_statement": "bug",
        "test_patch": TEST_PATCH,
        "fail_to_pass": ["tests.queries.test_qs.TestX.test_y"],
        "pass_to_pass": [],
        "extra": {},
    }
    return base | overrides


def test_patch_test_files_keeps_only_test_sources():
    assert patch_test_files(TEST_PATCH) == ["tests/queries/test_qs.py"]


def test_internal_test_command_prefers_shipped_commands():
    live = _instance(extra={"test_cmds": ["pytest tests/test_a.py", "pytest tests/test_b.py"]})
    assert internal_test_command(BENCHMARKS["swebench-live"], live) == (
        "pytest tests/test_a.py && pytest tests/test_b.py"
    )
    poly = _instance(extra={"test_command": "mvn test -pl module"})
    assert internal_test_command(BENCHMARKS["swe-polybench"], poly) == "mvn test -pl module"


def test_internal_test_command_defers_to_inference_when_nothing_shipped():
    assert internal_test_command(BENCHMARKS["swebench-verified"], _instance()) is None


# --- infer_test_command (language-aware fallback, runs against the checkout) ---


def test_infer_python_scopes_to_touched_test_files(tmp_path):
    cmd = infer_test_command(tmp_path, ["tests/queries/test_qs.py"])
    assert cmd == "python -m pytest -x -q tests/queries/test_qs.py"


def test_infer_go_scopes_to_packages_of_test_files(tmp_path):
    (tmp_path / "go.mod").write_text("module example.com/x\n")
    cmd = infer_test_command(tmp_path, ["pkg/a/a_test.go", "pkg/b/b_test.go", "README.md"])
    assert cmd == "go test ./pkg/a/... ./pkg/b/..."


def test_infer_rust_and_java(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n")
    assert infer_test_command(tmp_path, ["tests/t.rs"]) == "cargo test"

    (tmp_path / "Cargo.toml").unlink()
    (tmp_path / "pom.xml").write_text("<project/>")
    cmd = infer_test_command(tmp_path, ["src/test/java/com/foo/BarTest.java"])
    assert cmd == "mvn test -q -Dtest=BarTest"


def test_infer_js_reads_the_test_script_runner(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}})
    )
    assert infer_test_command(tmp_path, ["test/t.test.js"]) == "npx vitest run test/t.test.js"

    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "mocha"}}))
    assert infer_test_command(tmp_path, ["test/t.js"]) == "npx mocha test/t.js"

    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "node --test"}}))
    assert infer_test_command(tmp_path, ["test/t.js"]) == "npm test"


def test_image_for_swebench_family_uses_official_naming():
    # Docker Hub convention: instance_id's "__" becomes "_1776_"
    assert image_for(BENCHMARKS["swebench-verified"], _instance()) == (
        "swebench/sweb.eval.x86_64.django_1776_django-16379:latest"
    )


def test_image_for_pro_uses_dockerhub_tag_as_tag():
    inst = _instance(extra={"dockerhub_tag": "nodebb.nodebb-NodeBB__NodeBB-abc123"})
    assert image_for(BENCHMARKS["swebench-pro"], inst) == (
        "jefzda/sweap-images:nodebb.nodebb-NodeBB__NodeBB-abc123"
    )


def test_image_for_live_uses_starryzhang_org():
    inst = _instance(instance_id="aws-cloudformation__cfn-lint-3498")
    assert image_for(BENCHMARKS["swebench-live"], inst) == (
        "starryzhang/sweb.eval.x86_64.aws-cloudformation_1776_cfn-lint-3498:latest"
    )


def test_image_for_polybench_uses_ghcr_prebuilt():
    inst = _instance(instance_id="google__gson-2337")
    assert image_for(BENCHMARKS["swe-polybench"], inst) == (
        "ghcr.io/timesler/swe-polybench.eval.x86_64.google__gson-2337:v1.1"
    )


def test_image_for_multi_swe_uses_mswebench_pr_naming():
    inst = _instance(instance_id="alibaba__fastjson2-1245", repo="alibaba/fastjson2")
    assert image_for(BENCHMARKS["multi-swe-bench"], inst) == (
        "mswebench/alibaba_m_fastjson2:pr-1245"
    )
    # repo names with dashes: split the PR number at the LAST dash
    dashed = _instance(
        instance_id="aws-cloudformation__cfn-lint-3498", repo="aws-cloudformation/cfn-lint"
    )
    assert image_for(BENCHMARKS["multi-swe-bench"], dashed) == (
        "mswebench/aws-cloudformation_m_cfn-lint:pr-3498"
    )


def test_container_workdir_per_benchmark():
    assert container_workdir(BENCHMARKS["swebench-verified"], _instance()) == "/testbed"
    assert container_workdir(BENCHMARKS["swe-polybench"], _instance()) == "/testbed"
    mswe = _instance(instance_id="alibaba__fastjson2-1245", repo="alibaba/fastjson2")
    assert container_workdir(BENCHMARKS["multi-swe-bench"], mswe) == "/home/fastjson2"


def test_load_done_reads_existing_predictions(tmp_path):
    path = tmp_path / "predictions.jsonl"
    path.write_text(
        json.dumps({"instance_id": "a", "model_name_or_path": "m", "model_patch": "x"}) + "\n"
        + json.dumps({"instance_id": "b", "model_name_or_path": "m", "model_patch": "y"}) + "\n"
    )
    assert load_done(path) == {"a", "b"}
    assert load_done(tmp_path / "missing.jsonl") == set()
