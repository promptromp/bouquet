"""Bouquet logging configuration.

A single call to :func:`configure` early in the CLI / TUI entry points
sets up:

- a rotating file handler at ``~/.local/state/bouquet/{project}.log``
  (~5 MB × 3 backups), capturing everything at the configured level
- a stderr console handler at ``WARNING+`` so direct (non-TUI) CLI use
  still surfaces problems immediately, but the file log is always the
  durable record (the TUI captures stderr, so file is the source of
  truth there)

All bouquet modules use ``logging.getLogger(__name__)`` to emit through
the configured ``bouquet`` logger.

Calling :func:`configure` more than once is a no-op (handlers aren't
re-added).
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


#: Path to the active log file once :func:`configure` has been called.
#: Callers (e.g. :class:`bouquet.bootstrap.SetupCommandsError`) reference
#: this to point users at the durable diagnostic record.
LOG_FILE: Path | None = None

_LOGGER_NAME = "bouquet"
_FORMATTER = logging.Formatter(
    "%(asctime)s %(name)-30s %(levelname)-7s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3


def state_dir() -> Path:
    """Return ``~/.local/state/bouquet/``, creating it if needed."""
    d = Path.home() / ".local" / "state" / "bouquet"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _level_value(level: str | int) -> int:
    """Normalise a level name or int into the corresponding logging constant."""
    if isinstance(level, int):
        return level
    return logging.getLevelName(level.upper())


def configure(project_name: str, level: str | int = "INFO") -> Path:
    """Idempotently configure the ``bouquet`` logger.

    Returns the absolute path to the active log file.

    *level* controls the file handler's threshold (INFO by default).
    The console handler is always WARNING+ regardless.
    """
    global LOG_FILE
    log_file = state_dir() / f"{project_name}.log"

    root = logging.getLogger(_LOGGER_NAME)
    root.setLevel(logging.DEBUG)
    root.propagate = False

    # Idempotent: skip if a file handler already points at this log file.
    for h in root.handlers:
        if isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == log_file:
            LOG_FILE = log_file
            return log_file

    fh = RotatingFileHandler(
        log_file,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setLevel(_level_value(level))
    fh.setFormatter(_FORMATTER)
    root.addHandler(fh)

    # Stderr handler — only WARNING+ so non-TUI CLI use isn't noisy but
    # real problems still surface even before configure() is called.
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in root.handlers):
        ch = logging.StreamHandler()
        ch.setLevel(logging.WARNING)
        ch.setFormatter(_FORMATTER)
        root.addHandler(ch)

    LOG_FILE = log_file
    root.info("logging configured for project=%s level=%s", project_name, level)
    return log_file
