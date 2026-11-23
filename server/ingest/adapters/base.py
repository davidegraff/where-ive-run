"""The interface every data source implements."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from server.ingest.entries import Entry
from server.ingest.parsers import ParsedTrack
from server.models import Activity, SourceId


@dataclass
class TrackResult:
    """One parsed track file: the track (with its points already thinned), or why it couldn't be read."""

    track: ParsedTrack | None
    error: str | None = None


class ImportContext(Protocol):
    def read_tracks(self, entries: list[Entry]) -> Iterator[TrackResult]:
        """Parse GPX / TCX / FIT entries, one result per entry, in the same order. Runs on several
        CPU cores, so read all of an import's track files through one call rather than one by one."""
        ...

    def progress(self, done: int, total: int) -> None:
        """Report progress through this source (done of total units)."""

    def warn(self, message: str) -> None:
        """Report a non-fatal problem, e.g. one unreadable file."""


class SourceAdapter(Protocol):
    """A data source. To support a new export format (Garmin, Apple Health, ...), write a class with
    these members and add an instance to ADAPTERS in adapters/__init__.py."""

    id: SourceId
    label: str
    """Shown in the UI, e.g. "Strava archive"."""

    def detect(self, entries: list[Entry]) -> bool:
        """True if these entries (one uploaded zip's contents, or the loose files) are this source's format."""
        ...

    def read(self, entries: list[Entry], ctx: ImportContext) -> Iterator[Activity]:
        """Yield one Activity per activity found."""
        ...
