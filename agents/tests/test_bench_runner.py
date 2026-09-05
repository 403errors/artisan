"""Unit tests for the bench runner's pure helpers (no Docker, no network, no Gemini)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals" / "bench"))

from registry import BENCHMARKS
from runner import (
    image_for,
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


def test_internal_test_command_scopes_to_touched_test_files():
    cmd = internal_test_command(BENCHMARKS["swebench-verified"], _instance())
    assert cmd == "python -m pytest -x -q tests/queries/test_qs.py"


def test_internal_test_command_prefers_shipped_commands():
    live = _instance(extra={"test_cmds": ["pytest tests/test_a.py", "pytest tests/test_b.py"]})
    assert internal_test_command(BENCHMARKS["swebench-live"], live) == (
        "pytest tests/test_a.py && pytest tests/test_b.py"
    )
    poly = _instance(extra={"test_command": "mvn test -pl module"})
    assert internal_test_command(BENCHMARKS["swe-polybench"], poly) == "mvn test -pl module"


def test_internal_test_command_falls_back_when_patch_has_no_test_files():
    inst = _instance(test_patch=TEST_PATCH.split("diff --git")[1])  # source file only
    assert internal_test_command(BENCHMARKS["swebench-verified"], inst) == "python -m pytest -x -q"


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


def test_image_for_unsupported_benchmarks_raise_with_guidance():
    with pytest.raises(NotImplementedError, match="official harness"):
        image_for(BENCHMARKS["multi-swe-bench"], _instance())


def test_load_done_reads_existing_predictions(tmp_path):
    path = tmp_path / "predictions.jsonl"
    path.write_text(
        json.dumps({"instance_id": "a", "model_name_or_path": "m", "model_patch": "x"}) + "\n"
        + json.dumps({"instance_id": "b", "model_name_or_path": "m", "model_patch": "y"}) + "\n"
    )
    assert load_done(path) == {"a", "b"}
    assert load_done(tmp_path / "missing.jsonl") == set()
