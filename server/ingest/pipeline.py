"""Turn whatever the user uploaded into Activity records."""

from __future__ import annotations

import time
import zipfile
from collections import deque
from collections.abc import Callable, Iterator
from concurrent.futures import Executor, Future
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from server.models import Activity, ProgressEvent, SourceDoneEvent, SourceSummary, WarningEvent

from .adapters import ADAPTERS, SourceAdapter, detect_adapter
from .adapters.base import TrackResult
from .entries import Entry, file_entry, is_zip, zip_entries
from .geo import thin
from .parsers import parse_track_file

BATCH_SIZE = 100
"""Activities are handed over in batches, so a huge archive is saved as it goes."""


@dataclass
class InputFile:
    name: str
    """The name it was uploaded with. Only used for display and to recognise the file type."""
    path: Path


@dataclass
class Batch:
    activities: list[Activity]


PipelineEvent = Union[ProgressEvent, WarningEvent, SourceDoneEvent, Batch]
Emit = Callable[[PipelineEvent], None]


def run_import(files: list[InputFile], emit: Emit, pool: Executor | None = None) -> list[SourceSummary]:
    """Each zip is matched to an adapter on its own (a Strava archive and a Garmin archive can be
    uploaded together); loose files are handled as one group. Raises ValueError if nothing
    recognisable was found.

    Track files are parsed in `pool` (a ProcessPoolExecutor, so FIT decoding uses every core), or
    one by one in this thread if there is no pool. To stop an import early, raise from `emit`."""
    with ExitStack() as stack:
        jobs: list[tuple[str, list[Entry]]] = []
        loose: list[Entry] = []
        unknown: list[str] = []
        for f in files:
            if not is_zip(f.name):
                loose.append(file_entry(f.name, f.path))
                continue
            try:
                zf = stack.enter_context(zipfile.ZipFile(f.path))
            except zipfile.BadZipFile:
                unknown.append(f.name)
                continue
            jobs.append((f.name, zip_entries(zf)))
        if loose:
            jobs.append((loose[0].path if len(loose) == 1 else f"{len(loose)} files", loose))

        summaries: list[SourceSummary] = []
        for name, entries in jobs:
            adapter = detect_adapter(entries)
            if adapter is None:
                unknown.append(name)
            else:
                summaries.append(_run_adapter(adapter, name, entries, emit, pool))

    for name in unknown:
        emit(WarningEvent(type="warning", message=f"{name}: not a format we can read yet"))
    if not summaries:
        supported = ", ".join(a.label for a in ADAPTERS)
        raise ValueError(f"Couldn't find any activities in {', '.join(unknown)}. Supported: {supported}.")
    return summaries


def _run_adapter(adapter: SourceAdapter, file: str, entries: list[Entry], emit: Emit, pool: Executor | None) -> SourceSummary:
    summary = SourceSummary(file=file, source=adapter.id, label=adapter.label, activities=0, with_gps=0, warnings=0)
    last_progress = 0.0

    class Context:
        def read_tracks(self, entries: list[Entry]) -> Iterator[TrackResult]:
            if pool is None:
                return (read_track(e.path, e.read()) for e in entries)
            return _parse_in_pool(pool, entries)

        def progress(self, done: int, total: int) -> None:
            nonlocal last_progress
            now = time.monotonic()
            if done == total or now - last_progress > 0.1:  # at most ~10 updates a second
                last_progress = now
                emit(ProgressEvent(type="progress", file=file, label=adapter.label, done=done, total=total))

        def warn(self, message: str) -> None:
            summary.warnings += 1
            emit(WarningEvent(type="warning", message=message))

    batch: list[Activity] = []
    for activity in adapter.read(entries, Context()):
        summary.activities += 1
        if activity.polyline:
            summary.with_gps += 1
        batch.append(activity)
        if len(batch) >= BATCH_SIZE:
            emit(Batch(batch))
            batch = []
    if batch:
        emit(Batch(batch))
    emit(SourceDoneEvent(type="source-done", summary=summary))
    return summary


def read_track(name: str, raw: bytes) -> TrackResult:
    """Parse one track file and thin its route. Runs in a pool process, so it must be a plain
    module-level function, and it returns errors instead of raising them."""
    try:
        track = parse_track_file(name, raw)
    except Exception as e:
        return TrackResult(track=None, error=str(e) or type(e).__name__)
    track.points = thin(track.points)
    return TrackResult(track=track)


def _parse_in_pool(pool: Executor, entries: list[Entry], window: int = 64) -> Iterator[TrackResult]:
    """Results in input order, with at most `window` files queued ahead, so memory stays bounded and
    an abandoned import leaves little work behind. Unstarted tasks are cancelled if the caller stops early.
    Zip members are read here (zlib is fast and releases the GIL); only parsing happens in the pool."""
    pending: deque[Future[TrackResult]] = deque()
    try:
        for entry in entries:
            pending.append(pool.submit(read_track, entry.path, entry.read()))
            if len(pending) >= window:
                yield pending.popleft().result()
        while pending:
            yield pending.popleft().result()
    finally:
        for f in pending:
            f.cancel()
