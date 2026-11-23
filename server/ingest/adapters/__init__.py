"""Data sources. Each one recognises its own files and turns them into Activity records."""

from __future__ import annotations

from server.ingest.entries import Entry

from .base import ImportContext, SourceAdapter
from .strava_archive import StravaArchive
from .track_files import TrackFiles

__all__ = ["ADAPTERS", "ImportContext", "SourceAdapter", "detect_adapter"]

ADAPTERS: list[SourceAdapter] = [StravaArchive(), TrackFiles()]
"""Tried in order; the first whose detect() matches handles the files. Most specific first."""


def detect_adapter(entries: list[Entry]) -> SourceAdapter | None:
    return next((a for a in ADAPTERS if a.detect(entries)), None)
