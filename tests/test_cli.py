import json
import subprocess
import sys

import pytest

from envref import cli


def run_cli(*argv, env=None):
    return subprocess.run(
        [sys.executable, "-m", "envref.cli", *argv], capture_output=True, text=True, env=env
    )


def test_export_formats(tmp_path, monkeypatch, capsys):
    f = tmp_path / ".env"
    f.write_text("A=it's\nB={{ env://SRC }}\n")
    monkeypatch.setenv("SRC", "from env")

    with pytest.raises(SystemExit) as exc:
        cli.main(["export", "-f", str(f)])
    assert exc.value.code == 0
    assert capsys.readouterr().out == "export A='it'\"'\"'s'\nexport B='from env'\n"

    with pytest.raises(SystemExit):
        cli.main(["export", "-f", str(f), "--format", "json"])
    assert json.loads(capsys.readouterr().out) == {"A": "it's", "B": "from env"}


def test_check_reports_without_values(tmp_path, monkeypatch, capsys):
    f = tmp_path / ".env"
    f.write_text("OK={{ env://PRESENT }}\nBAD={{ env://ABSENT }}\nURL=https://x.y\n")
    monkeypatch.setenv("PRESENT", "top-secret-value")

    with pytest.raises(SystemExit) as exc:
        cli.main(["check", "-f", str(f)])
    out = capsys.readouterr().out
    assert exc.value.code == 1
    assert "top-secret-value" not in out
    assert "✓ OK" in out and "✗ BAD" in out and "ABSENT is not set" in out
    assert "URL" in out and "literal" in out


def test_run_execs_with_resolved_environment(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("GREETING={{ env://SRC }}\nPLAIN=yes\n")
    import os

    env = dict(os.environ, SRC="hello")
    result = run_cli(
        "run", "-f", str(f), "--", sys.executable, "-c",
        "import os; print(os.environ['GREETING'], os.environ['PLAIN'])", env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "hello yes"


def test_doctor_lists_builtins(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["doctor"])
    out = capsys.readouterr().out
    assert exc.value.code == 0
    for scheme in ("env://", "file://", "keychain://", "op://"):
        assert scheme in out


def test_unknown_scheme_is_a_clean_error(tmp_path, capsys):
    f = tmp_path / ".env"
    f.write_text("X={{ nope://y }}\n")
    with pytest.raises(SystemExit) as exc:
        cli.main(["export", "-f", str(f)])
    assert exc.value.code == 1
    assert "no resolver for 'nope://'" in capsys.readouterr().err
