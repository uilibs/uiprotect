import subprocess
import sys

import pytest

# uiprotect.__main__ imports the typer-based CLI (optional `cli` extra); skip
# rather than fail at collection when it's absent.
pytest.importorskip("typer")

import uiprotect.__main__ as dunder_main


def test_can_run_as_python_module():
    """Run the CLI as a Python module."""
    result = subprocess.run(
        [sys.executable, "-m", "uiprotect", "--help"],  # S603,S607
        check=True,
        capture_output=True,
    )
    assert result.returncode == 0
    assert b"uiprotect [OPTIONS]" in result.stdout


def test_start_loads_env_file_when_present(monkeypatch, tmp_path):
    """`start()` passes the cwd `.env` to load_dotenv when it exists."""
    seen: dict[str, object] = {}
    monkeypatch.setattr(dunder_main, "load_dotenv", lambda **kw: seen.update(kw))
    monkeypatch.setattr(dunder_main, "app", lambda: None)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("")

    dunder_main.start()

    assert seen["dotenv_path"] == tmp_path / ".env"


def test_start_without_env_file(monkeypatch, tmp_path):
    """`start()` falls back to a bare load_dotenv when no cwd `.env` exists."""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(dunder_main, "load_dotenv", lambda **kw: calls.append(kw))
    monkeypatch.setattr(dunder_main, "app", lambda: None)
    monkeypatch.chdir(tmp_path)

    dunder_main.start()

    assert calls == [{}]
