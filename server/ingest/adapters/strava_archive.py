"""Strava's bulk export ("Download or Delete Your Account -> Request Your Archive").

activities.csv has one row per activity; its Filename column points at the GPX / TCX / FIT route.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterator

from server.ingest.entries import Entry
from server.ingest.geo import encode_polyline
from server.ingest.parsers import is_track_file
from server.models import Activity, LatLng, SourceId, activity_key

from .base import ImportContext

_CSV_RE = re.compile(r"(^|/)activities\.csv$")


class StravaArchive:
    id: SourceId = "strava-archive"
    label = "Strava archive"

    def detect(self, entries: list[Entry]) -> bool:
        return any(_CSV_RE.search(e.path) for e in entries)

    def read(self, entries: list[Entry], ctx: ImportContext) -> Iterator[Activity]:
        csv_entry = next(e for e in entries if _CSV_RE.search(e.path))
        prefix = csv_entry.path[: -len("activities.csv")]
        by_path = {e.path: e for e in entries}

        header, *rows = list(csv.reader(io.StringIO(csv_entry.read().decode("utf-8-sig"))))

        def col(name: str, last: bool = False) -> int | None:
            idx = [i for i, h in enumerate(header) if h.strip() == name]
            return (idx[-1] if last else idx[0]) if idx else None

        c_id, c_type = col("Activity ID"), col("Activity Type")
        if c_id is None or c_type is None:
            raise ValueError("activities.csv is missing the Activity ID / Activity Type columns")
        c_date, c_name, c_file = col("Activity Date"), col("Activity Name"), col("Filename")
        c_dist_m = col("Distance", last=True)  # the later "Distance" column is in metres...
        c_dist_display = col("Distance")  # ...the first one is in the account's display unit
        c_moving, c_elapsed, c_elev = col("Moving Time"), col("Elapsed Time"), col("Elevation Gain")

        valid = [r for r in rows if c_type < len(r) and r[c_type]]

        def track_entry(row: list[str]) -> Entry | None:
            file_name = row[c_file] if c_file is not None and c_file < len(row) else ""
            entry = by_path.get(prefix + file_name) if file_name else None
            # Some rows point at .json files (e.g. manual entries with a drawn route); those carry no GPS.
            return entry if entry and is_track_file(entry.path) else None

        # Parse every route file up front (in parallel), then pair each row with its result.
        entries_by_row = [track_entry(r) for r in valid]
        tracks = ctx.read_tracks([e for e in entries_by_row if e])

        for i, (row, entry) in enumerate(zip(valid, entries_by_row)):

            def get(c: int | None, row: list[str] = row) -> str:
                return row[c] if c is not None and c < len(row) else ""

            distance = _num(get(c_dist_m))
            if c_dist_m == c_dist_display:  # old exports have a single Distance column, in km
                distance *= 1000

            points: list[LatLng] = []
            if entry:
                result = next(tracks)
                if result.track:
                    points = result.track.points
                else:  # a corrupt file: keep the activity, skip its route
                    ctx.warn(f"Could not read {get(c_file)}: {result.error}")

            source_id = get(c_id)
            yield Activity(
                key=activity_key(self.id, source_id),
                source=self.id,
                source_id=source_id,
                name=get(c_name),
                date=parse_strava_date(get(c_date)),
                type=get(c_type),
                distance_m=distance,
                moving_s=_num(get(c_moving)) or _num(get(c_elapsed)),
                elev_m=_num(get(c_elev)),
                start=points[0] if points else None,
                polyline=encode_polyline(points) if len(points) > 1 else "",
                url=f"https://www.strava.com/activities/{source_id}",
            )
            ctx.progress(i + 1, len(valid))


def _num(text: str) -> float:
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return 0.0


_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_US = re.compile(r"^([A-Za-z]{3})[a-z]*\.? (\d{1,2}), (\d{4}),? (\d{1,2}):(\d{2}):(\d{2}) ?([AP]M)$", re.IGNORECASE)
_EU = re.compile(r"^(\d{1,2}) ([A-Za-z]{3})[a-z]*\.? (\d{4}),? (\d{1,2}):(\d{2}):(\d{2})$")
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})")
# Newer exports put non-breaking spaces (U+00A0, U+202F) around the time.
_SPACES = re.compile("[\u00a0\u202f]")


def parse_strava_date(text: str) -> str:
    """Strava writes dates in UTC as "Dec 6, 2018, 12:09:18 PM", "6 Dec 2018, 13:09:18" or
    "2018-12-06 12:09:18", depending on the account's language. Returns "YYYY-MM-DDTHH:MM:SS"."""
    t = _SPACES.sub(" ", text).strip()
    if m := _US.match(t):
        hour = int(m[4]) % 12 + (12 if m[7].upper() == "PM" else 0)
        return f"{m[3]}-{_month(m[1])}-{int(m[2]):02d}T{hour:02d}:{m[5]}:{m[6]}"
    if m := _EU.match(t):
        return f"{m[3]}-{_month(m[2])}-{int(m[1]):02d}T{int(m[4]):02d}:{m[5]}:{m[6]}"
    if m := _ISO.match(t):
        return f"{m[1]}-{m[2]}-{m[3]}T{m[4]}:{m[5]}:{m[6]}"
    return t


def _month(name: str) -> str:
    return f"{_MONTHS.index(name.lower()) + 1:02d}"
