#!/usr/bin/env python3
"""Thin launcher for Cue. Run with: python cue.py

Contains no app logic -- it only checks the environment and starts
Streamlit against app.py using the same Python interpreter that ran this
script, so there's no "wrong venv" confusion. All UI code stays in
app.py; this file should stay small.
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import sys
from pathlib import Path

MIN_PYTHON = (3, 11)
# librosa/numba don't yet support CPython 3.13+ (confirmed broken on 3.14
# during development) -- warn but don't block, in case a future release fixes it.
UNTESTED_PYTHON_FROM = (3, 13)

DEFAULT_PORT = 8501
PROJECT_DIR = Path(__file__).resolve().parent


def check_python_version() -> None:
    if sys.version_info[:2] < MIN_PYTHON:
        print(
            f"Cue needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ "
            f"(found {sys.version_info.major}.{sys.version_info.minor}). "
            f"librosa/numba require a modern CPython. Install Python "
            f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]} and recreate the virtualenv: "
            f"python{MIN_PYTHON[0]}.{MIN_PYTHON[1]} -m venv .venv"
        )
        sys.exit(1)
    if sys.version_info[:2] >= UNTESTED_PYTHON_FROM:
        print(
            f"Warning: Python {sys.version_info.major}.{sys.version_info.minor} "
            f"hasn't been tested with this project's librosa/numba dependencies "
            f"(Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} is confirmed working). "
            "Continuing anyway -- if librosa import fails, switch to "
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}."
        )


def check_streamlit_installed() -> None:
    try:
        import streamlit  # noqa: F401
    except ImportError:
        print(
            "Dependencies missing. Activate the virtualenv and run "
            "`pip install -r requirements.txt`."
        )
        sys.exit(1)


def check_ffmpeg() -> None:
    if shutil.which("ffmpeg") is not None:
        return
    if sys.platform == "darwin":
        hint = "brew install ffmpeg"
    elif sys.platform.startswith("linux"):
        hint = "sudo apt install ffmpeg  (or your distro's equivalent)"
    elif sys.platform == "win32":
        hint = "winget install ffmpeg  (or download from https://ffmpeg.org/download.html and add it to PATH)"
    else:
        hint = "install ffmpeg from https://ffmpeg.org and add it to PATH"
    print(f"ffmpeg not found on PATH. Audio analysis needs it to decode previews. Install it with:\n  {hint}")
    sys.exit(1)


def check_env_file() -> None:
    env_path = PROJECT_DIR / ".env"
    if not env_path.exists():
        print(
            "No .env file found. Copy .env.example to .env and add your keys "
            "if you have them -- matching still works fully without Groq/Last.fm keys.\n"
        )


def suppress_streamlit_first_run_prompt() -> None:
    """On a machine's first-ever Streamlit run, it blocks waiting on stdin
    for an email address before it will start the server at all -- fatal
    for a one-command launcher. Pre-writing an empty answer is Streamlit's
    own documented way to skip it (used the same way in CI); it only sets
    a blank email/opts out of usage stats, no other effect."""
    credentials_path = Path.home() / ".streamlit" / "credentials.toml"
    if credentials_path.exists():
        return
    credentials_path.parent.mkdir(parents=True, exist_ok=True)
    credentials_path.write_text('[general]\nemail = ""\n')


def find_free_port(preferred: int) -> int:
    """Return `preferred` if it's free, otherwise the next free port after it."""
    port = preferred
    while port < preferred + 100:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("localhost", port))
                return port
            except OSError:
                port += 1
    # Extremely unlikely, but don't loop forever.
    return preferred


def main() -> None:
    # Line-buffer stdout even when it's redirected to a file/pipe, so the
    # banner below reliably prints before the Streamlit subprocess's own
    # (unbuffered) output rather than racing it.
    sys.stdout.reconfigure(line_buffering=True)

    check_python_version()
    check_streamlit_installed()
    check_ffmpeg()
    check_env_file()
    suppress_streamlit_first_run_prompt()

    port = find_free_port(DEFAULT_PORT)
    if port != DEFAULT_PORT:
        print(f"Port {DEFAULT_PORT} is in use -- using {port} instead.")

    print(f"Starting Cue at http://localhost:{port}")
    print("Press Ctrl+C to stop.\n")

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "app.py",
            "--server.port",
            str(port),
            "--server.address",
            "localhost",
        ],
        cwd=PROJECT_DIR,
    )
    try:
        proc.wait()
    except KeyboardInterrupt:
        # A real terminal Ctrl+C sends SIGINT to the whole foreground
        # process group, so Streamlit is usually already shutting itself
        # down here too -- but explicitly stop it so it can't be orphaned
        # if this script is ever run in a context where only the parent
        # gets the signal (e.g. `kill -INT <pid>` targeting just cue.py).
        print("\nStopping...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        print("Stopped.")


if __name__ == "__main__":
    main()
