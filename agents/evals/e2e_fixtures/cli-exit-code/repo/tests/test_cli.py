import pytest

from cfgtool.main import main


def test_valid_config_prints_ok(tmp_path, capsys):
    cfg = tmp_path / "good.ini"
    cfg.write_text("[server]\nport=8080\n[logging]\nlevel=info\n")
    main(["check", str(cfg)])
    assert "OK" in capsys.readouterr().out


def test_invalid_config_prints_invalid_to_stderr(tmp_path, capsys):
    cfg = tmp_path / "bad.ini"
    cfg.write_text("[server]\nport=8080\n")  # missing [logging]
    main(["check", str(cfg)])
    assert "INVALID" in capsys.readouterr().err


def test_unparseable_config_reports_problem(tmp_path, capsys):
    cfg = tmp_path / "broken.ini"
    cfg.write_text("not an ini file [[[")
    main(["check", str(cfg)])
    assert "INVALID" in capsys.readouterr().err
