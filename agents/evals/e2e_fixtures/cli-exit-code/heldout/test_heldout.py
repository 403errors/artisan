"""Held-out oracle tests — injected by the eval harness AFTER the pipeline finishes, never
visible to the coding agent. They fail on the seeded bug and pass on a correct fix."""

import pytest

from cfgtool.main import main


def test_invalid_config_exits_nonzero(tmp_path):
    cfg = tmp_path / "bad.ini"
    cfg.write_text("[server]\nport=8080\n")  # missing [logging]
    assert main(["check", str(cfg)]) == 2


def test_unparseable_config_exits_nonzero(tmp_path):
    cfg = tmp_path / "broken.ini"
    cfg.write_text("not an ini file [[[")
    assert main(["check", str(cfg)]) != 0


def test_valid_config_still_exits_zero(tmp_path):
    cfg = tmp_path / "good.ini"
    cfg.write_text("[server]\nport=8080\n[logging]\nlevel=info\n")
    assert main(["check", str(cfg)]) == 0
