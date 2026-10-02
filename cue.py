#!/usr/bin/env python3
"""Cue launcher. Run with: python cue.py

Runs the Cue server as a detached background process and opens the
browser to it -- the terminal is not needed afterward. Contains no app
logic; it only checks the environment, starts/stops/inspects the FastAPI
server in server/main.py, and opens a browser tab.

Subcommands:
  python cue.py               start the server if needed and print its URL
                               (copy/paste it into a browser; works from an
                               IDE's run button)
  python cue.py --open        same, and also open the browser for you
  python cue.py stop          stop the running server
  python cue.py status        show whether Cue is running and where
  python cue.py logs          print the server log
  python cue.py install-app   generate Cue.app (macOS double-click launcher,
                               no Terminal window) in the project folder
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

MIN_PYTHON = (3, 11)
# librosa/numba don't yet support CPython 3.13+ (confirmed broken on 3.14
# during development) -- warn but don't block, in case a future release fixes it.
UNTESTED_PYTHON_FROM = (3, 13)

DEFAULT_PORT = 8765
PROJECT_DIR = Path(__file__).resolve().parent
PID_FILE = PROJECT_DIR / ".cue.pid"
LOG_DIR = PROJECT_DIR / "logs"
LOG_FILE = LOG_DIR / "cue.log"
HEALTH_TIMEOUT_S = 20


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


def check_dependencies() -> None:
    missing = []
    for module in ("fastapi", "uvicorn", "librosa"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    if missing:
        print(
            f"Dependencies missing ({', '.join(missing)}). Activate the virtualenv "
            "and run `pip install -r requirements.txt`."
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
    if not (PROJECT_DIR / ".env").exists():
        print(
            "No .env file found. Copy .env.example to .env and add your keys "
            "if you have them -- matching still works fully without Groq/Last.fm keys.\n"
        )


def suppress_streamlit_first_run_prompt() -> None:
    """Harmless leftover safety net: nothing in the V2 stack uses Streamlit,
    but if it's ever reinstalled in this venv for some reason, this avoids
    its first-run email prompt blocking a background process on stdin."""
    credentials_path = Path.home() / ".streamlit" / "credentials.toml"
    if credentials_path.exists():
        return
    try:
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text('[general]\nemail = ""\n')
    except OSError:
        pass


MAX_LOG_BYTES = 5 * 1024 * 1024


def _rotate_log_if_large() -> None:
    """Simple size-based rotation for the launched server's raw stdout
    log -- it's a subprocess's output stream, not Python logging, so
    logging.handlers.RotatingFileHandler doesn't apply here. Keeps one
    backup, checked at each start rather than continuously."""
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_BYTES:
        backup = LOG_FILE.with_suffix(".log.1")
        backup.unlink(missing_ok=True)
        LOG_FILE.rename(backup)


def find_free_port(preferred: int) -> int:
    port = preferred
    while port < preferred + 100:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                port += 1
    return preferred


def _read_pid_file() -> dict | None:
    if not PID_FILE.exists():
        return None
    try:
        return json.loads(PID_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)  # signal 0: existence check only, raises if not alive
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _health_check(port: int, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def find_running_server() -> dict | None:
    """Returns {"pid": ..., "port": ...} if a Cue server from our PID file
    is alive and actually answering health checks; cleans up a stale PID
    file otherwise."""
    info = _read_pid_file()
    if info is None:
        return None
    if not _process_alive(info["pid"]) or not _health_check(info["port"]):
        PID_FILE.unlink(missing_ok=True)
        return None
    return info


def _announce(port: int, already_running: bool, open_browser: bool) -> None:
    """Print the URL prominently so it can be copied from an IDE's run
    panel into any browser. Only opens a browser itself on request."""
    url = f"http://127.0.0.1:{port}"
    state = "already running" if already_running else "running"
    print()
    print(f"  Cue is {state}. Copy this into your browser:")
    print()
    print(f"      {url}")
    print()
    print("  Stop it with: python cue.py stop")
    if open_browser:
        webbrowser.open(url)


def start(open_browser: bool = False) -> None:
    check_python_version()
    check_dependencies()
    check_ffmpeg()
    check_env_file()
    suppress_streamlit_first_run_prompt()

    running = find_running_server()
    if running is not None:
        _announce(running["port"], already_running=True, open_browser=open_browser)
        return

    port = find_free_port(DEFAULT_PORT)
    LOG_DIR.mkdir(exist_ok=True)
    _rotate_log_if_large()
    log_handle = open(LOG_FILE, "a")
    log_handle.write(f"\n--- Cue starting at {time.strftime('%Y-%m-%d %H:%M:%S')} on port {port} ---\n")
    log_handle.flush()

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=PROJECT_DIR,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,  # new session: detaches from the controlling
        # terminal, so a closed terminal/ended launching session can't HUP it.
        # Belt-and-suspenders: also explicitly ignore SIGHUP in the child --
        # SIG_IGN survives exec (unlike a Python signal handler), so uvicorn
        # inherits "ignore SIGHUP" even though it doesn't set that itself.
        preexec_fn=lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN),
    )
    PID_FILE.write_text(json.dumps({"pid": proc.pid, "port": port}))

    print(f"Starting Cue on http://127.0.0.1:{port} ...")
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while time.monotonic() < deadline:
        if _health_check(port):
            _announce(port, already_running=False, open_browser=open_browser)
            return
        if proc.poll() is not None:
            print(f"Cue's server process exited unexpectedly. Check the log:\n  {LOG_FILE}")
            PID_FILE.unlink(missing_ok=True)
            sys.exit(1)
        time.sleep(0.3)

    print(
        f"Cue didn't respond within {HEALTH_TIMEOUT_S}s. It may still be starting -- "
        f"check the log for errors:\n  {LOG_FILE}\n  (or run: python cue.py logs)"
    )
    sys.exit(1)


def stop() -> None:
    info = find_running_server()
    if info is None:
        print("Cue isn't running.")
        return

    try:
        urllib.request.urlopen(
            urllib.request.Request(f"http://127.0.0.1:{info['port']}/api/shutdown", method="POST"),
            timeout=2.0,
        )
    except (urllib.error.URLError, OSError, TimeoutError):
        # Graceful shutdown didn't answer -- fall back to signaling the PID directly.
        try:
            os.kill(info["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass

    for _ in range(20):
        if not _process_alive(info["pid"]):
            break
        time.sleep(0.25)

    PID_FILE.unlink(missing_ok=True)
    print("Cue stopped.")


def status() -> None:
    info = find_running_server()
    if info is None:
        print("Cue is not running.")
        return
    print(f"Cue is running at http://127.0.0.1:{info['port']} (pid {info['pid']}).")


def logs() -> None:
    if not LOG_FILE.exists():
        print(f"No log file yet at {LOG_FILE}.")
        return
    print(f"--- {LOG_FILE} (last 50 lines) ---")
    lines = LOG_FILE.read_text(errors="replace").splitlines()
    print("\n".join(lines[-50:]))


APP_BUNDLE_SCRIPT = """#!/bin/bash
# Generated by `python cue.py install-app` -- do not edit by hand, it
# will be overwritten next time install-app runs. Launched by Finder
# (double-click / Dock / Spotlight), so there is no terminal to print
# to: every failure shows a native dialog instead, and all output goes
# to logs/cue.log.
PROJECT_DIR="{project_dir}"
LOG_FILE="$PROJECT_DIR/logs/cue.log"
mkdir -p "$PROJECT_DIR/logs"

show_error() {{
    local msg="$1"
    osascript -e "display dialog \\"$(printf '%s' "$msg" | sed 's/"/\\\\"/g')\\" buttons {{\\"OK\\"}} with icon stop with title \\"Cue\\"" >/dev/null 2>&1
}}

cd "$PROJECT_DIR" 2>>"$LOG_FILE" || {{
    show_error "Cue's project folder is missing:\\n$PROJECT_DIR"
    exit 1
}}

PYTHON="$PROJECT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    show_error "Cue's virtualenv is missing. In Terminal, run:\\n\\ncd \\"$PROJECT_DIR\\"\\npython3.11 -m venv .venv\\nsource .venv/bin/activate\\npip install -r requirements.txt"
    exit 1
fi

OUTPUT=$("$PYTHON" cue.py --open 2>&1)
STATUS=$?
printf '%s\\n' "$OUTPUT" >> "$LOG_FILE"

if [ $STATUS -ne 0 ]; then
    REASON=$(printf '%s' "$OUTPUT" | tail -5)
    show_error "Cue failed to start.\\n\\n$REASON\\n\\nFull log: $LOG_FILE"
fi
"""

INFO_PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Cue</string>
    <key>CFBundleDisplayName</key>
    <string>Cue</string>
    <key>CFBundleExecutable</key>
    <string>Cue</string>
    <key>CFBundleIdentifier</key>
    <string>com.cue.launcher</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
"""
# No CFBundleIconFile key: Stage 7 (UI redesign) will generate Cue.icns
# from the layered-glass mark and this bundle will be regenerated to
# reference it. Until then Finder shows the generic app icon -- a
# placeholder, not a mistake.


def install_app() -> None:
    if sys.platform != "darwin":
        print("install-app only applies to macOS (Cue.app is a macOS app bundle).")
        sys.exit(1)

    app_dir = PROJECT_DIR / "Cue.app"
    macos_dir = app_dir / "Contents" / "MacOS"
    resources_dir = app_dir / "Contents" / "Resources"
    macos_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)

    (app_dir / "Contents" / "Info.plist").write_text(INFO_PLIST_TEMPLATE)

    executable = macos_dir / "Cue"
    executable.write_text(APP_BUNDLE_SCRIPT.format(project_dir=str(PROJECT_DIR)))
    executable.chmod(0o755)

    print(f"Created {app_dir}")
    print("Double-click it in Finder to launch Cue with no terminal window.")
    print(
        "First launch: macOS will likely say it's from an unidentified developer -- "
        "right-click Cue.app and choose Open once to allow it."
    )

    applications_dir = Path.home() / "Applications"
    try:
        answer = input(f"\nCopy Cue.app to {applications_dir} so it shows up in Launchpad/Spotlight? [y/N] ")
    except EOFError:
        answer = "n"
    if answer.strip().lower() == "y":
        applications_dir.mkdir(exist_ok=True)
        dest = applications_dir / "Cue.app"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(app_dir, dest)
        print(f"Copied to {dest}")


COMMANDS = {
    "start": start,
    "stop": stop,
    "status": status,
    "logs": logs,
    "install-app": install_app,
}


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    command = sys.argv[1] if len(sys.argv) > 1 else "start"
    if command == "--open":
        start(open_browser=True)
        return
    handler = COMMANDS.get(command)
    if handler is None:
        print(f"Unknown command: {command}\nUsage: python cue.py [start|stop|status|logs|install-app]")
        sys.exit(1)
    handler()


if __name__ == "__main__":
    main()
