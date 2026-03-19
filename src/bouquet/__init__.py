"""Bouquet - An orchestration layer for agentic coding."""

from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("bouquet")
except PackageNotFoundError:
    __version__ = "0.0.0"
