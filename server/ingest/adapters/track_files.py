"""Loose GPX / TCX / FIT files (or a zip of them) from any app or device."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from server.ingest.entries import Entry
from server.ingest.geo import encode_polyline, iso_no_zone
from server.ingest.parsers import is_track_file, normalize_type
from server.models import Activity, SourceId, activity_key

from .base import ImportContext


class TrackFiles:
    id: SourceId = "track-files"
    label = "GPX / TCX / FIT files"

    def detect(self, entries: list[Entry]) -> bool:
        return any(is_track_file(e.path) for e in entries)

    def read(self, entries: list[Entry], ctx: ImportContext) -> Iterator[Activity]:
        files = [e for e in entries if is_track_file(e.path)]
        for i, (entry, result) in enumerate(zip(files, ctx.read_tracks(files))):
            ctx.progress(i + 1, len(files))
            base = entry.path.rsplit("/", 1)[-1]
            track = result.track
            if track is None:
                ctx.warn(f"Could not read {base}: {result.error}")
                continue
            points = track.points
            if not track.start and len(points) < 2:
                ctx.warn(f"{base}: no time or GPS data, skipped")
                continue
            # Keyed by start time, so the same activity exported as both GPX and FIT is stored once.
            source_id = iso_no_zone(track.start) if track.start else base
            activity_type = normalize_type(track.sport)
            yield Activity(
                key=activity_key(self.id, source_id),
                source=self.id,
                source_id=source_id,
                name=track.name or _default_name(activity_type, track.start),
                date=iso_no_zone(track.start) if track.start else "",
                type=activity_type,
                distance_m=track.distance_m or 0,
                moving_s=track.moving_s or 0,
                elev_m=track.elev_m or 0,
                start=points[0] if points else None,
                polyline=encode_polyline(points) if len(points) > 1 else "",
            )


def _default_name(activity_type: str, start: datetime | None) -> str:
    """ "Morning Run", like Strava. The hour is UTC: track files don't say which time zone they're in."""
    if not start:
        return activity_type
    h = start.hour
    part = "Morning" if h < 12 else "Afternoon" if h < 17 else "Evening" if h < 21 else "Night"
    return f"{part} {activity_type}"
