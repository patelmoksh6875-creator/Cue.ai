import json
import socket

import pytest

import cue


def test_find_free_port_returns_preferred_when_free():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    assert cue.find_free_port(free_port) == free_port


def test_find_free_port_skips_busy_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        busy_port = s.getsockname()[1]
        result = cue.find_free_port(busy_port)
        assert result != busy_port
        assert result > busy_port


def test_process_alive_true_for_current_process():
    import os

    assert cue._process_alive(os.getpid())


def test_process_alive_false_for_bogus_pid():
    # PID 999999 essentially never exists on a real machine.
    assert cue._process_alive(999999) is False


def test_read_pid_file_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(cue, "PID_FILE", tmp_path / "nope.pid")
    assert cue._read_pid_file() is None


def test_read_pid_file_corrupt_returns_none(tmp_path, monkeypatch):
    pid_file = tmp_path / ".cue.pid"
    pid_file.write_text("not json")
    monkeypatch.setattr(cue, "PID_FILE", pid_file)
    assert cue._read_pid_file() is None


def test_find_running_server_cleans_up_stale_pid_file(tmp_path, monkeypatch):
    pid_file = tmp_path / ".cue.pid"
    pid_file.write_text(json.dumps({"pid": 999999, "port": 8765}))
    monkeypatch.setattr(cue, "PID_FILE", pid_file)
    assert cue.find_running_server() is None
    assert not pid_file.exists()


def test_find_running_server_none_when_no_pid_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cue, "PID_FILE", tmp_path / "nope.pid")
    assert cue.find_running_server() is None


def test_rotate_log_if_large_rotates_when_over_threshold(tmp_path, monkeypatch):
    log_file = tmp_path / "cue.log"
    log_file.write_bytes(b"x" * (cue.MAX_LOG_BYTES + 1))
    monkeypatch.setattr(cue, "LOG_FILE", log_file)
    cue._rotate_log_if_large()
    assert not log_file.exists()
    assert (tmp_path / "cue.log.1").exists()


def test_rotate_log_if_large_leaves_small_log_alone(tmp_path, monkeypatch):
    log_file = tmp_path / "cue.log"
    log_file.write_text("small")
    monkeypatch.setattr(cue, "LOG_FILE", log_file)
    cue._rotate_log_if_large()
    assert log_file.exists()
    assert log_file.read_text() == "small"


def test_status_reports_not_running(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cue, "PID_FILE", tmp_path / "nope.pid")
    cue.status()
    assert "not running" in capsys.readouterr().out
