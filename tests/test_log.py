"""Tests for bouquet's logging configuration."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from bouquet import log as bouquet_log


@pytest.fixture
def isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect ~/.local/state/bouquet/ into tmp_path and reset module state."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # Strip any handlers a previous test left on the bouquet logger.
    root = logging.getLogger("bouquet")
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    bouquet_log.LOG_FILE = None
    yield tmp_path
    # Cleanup: close handlers we added so the rotating file can be deleted.
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()


def test_configure_creates_state_dir_and_log_file(isolated_state_dir: Path) -> None:
    log_path = bouquet_log.configure("myproj")
    assert log_path == isolated_state_dir / ".local/state/bouquet/myproj.log"
    assert log_path.parent.is_dir()
    assert log_path == bouquet_log.LOG_FILE


def test_configure_writes_log_records_to_file(isolated_state_dir: Path) -> None:
    log_path = bouquet_log.configure("myproj")
    logging.getLogger("bouquet.test").info("hello %s", "world")
    # RotatingFileHandler buffers — flush all bouquet handlers
    for h in logging.getLogger("bouquet").handlers:
        h.flush()
    contents = log_path.read_text()
    assert "hello world" in contents
    assert "INFO" in contents


def test_configure_is_idempotent(isolated_state_dir: Path) -> None:
    """Calling configure twice with the same project name must not duplicate handlers."""
    bouquet_log.configure("myproj")
    handler_count_after_first = len(logging.getLogger("bouquet").handlers)
    bouquet_log.configure("myproj")
    handler_count_after_second = len(logging.getLogger("bouquet").handlers)
    assert handler_count_after_first == handler_count_after_second


def test_configure_respects_level(isolated_state_dir: Path) -> None:
    log_path = bouquet_log.configure("myproj", level="WARNING")
    logging.getLogger("bouquet.test").info("should-not-appear")
    logging.getLogger("bouquet.test").warning("should-appear")
    for h in logging.getLogger("bouquet").handlers:
        h.flush()
    contents = log_path.read_text()
    assert "should-not-appear" not in contents
    assert "should-appear" in contents


def test_state_dir_creates_under_home(isolated_state_dir: Path) -> None:
    assert bouquet_log.state_dir() == isolated_state_dir / ".local/state/bouquet"


def test_log_file_uses_rotating_handler(isolated_state_dir: Path) -> None:
    bouquet_log.configure("myproj")
    file_handlers = [h for h in logging.getLogger("bouquet").handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1
    fh = file_handlers[0]
    assert fh.maxBytes > 0
    assert fh.backupCount > 0
