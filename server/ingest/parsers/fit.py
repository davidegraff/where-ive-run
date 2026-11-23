"""FIT: Garmin's binary format, also used by Wahoo, Coros, Suunto and the Strava app."""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

import fitdecode

from server.models import LatLng

from .track import ParsedTrack

# FIT stores coordinates as "semicircles": 2^31 of them make 180 degrees.
SEMICIRCLE = 180 / 2**31


def parse_fit(raw: bytes) -> ParsedTrack:
    points: list[LatLng] = []
    sessions: list[dict[str, Any]] = []
    first: dict[str, dict[str, Any]] = {}  # first "sport" / "activity" / "file_id" message

    with fitdecode.FitReader(io.BytesIO(raw), check_crc=fitdecode.CrcCheck.DISABLED) as fit:
        for frame in fit:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            if frame.name == "record":
                lat, lng = _value(frame, "position_lat"), _value(frame, "position_long")
                if isinstance(lat, int) and isinstance(lng, int) and (lat or lng):
                    points.append((lat * SEMICIRCLE, lng * SEMICIRCLE))
            elif frame.name == "session":
                sessions.append({f.name: f.value for f in frame.fields})
            elif frame.name in ("sport", "activity", "file_id") and frame.name not in first:
                first[frame.name] = {f.name: f.value for f in frame.fields}

    def total(name: str) -> float | None:
        return sum(s[name] for s in sessions if isinstance(s.get(name), (int, float))) or None

    s = sessions[0] if sessions else {}
    start = s.get("start_time") or first.get("activity", {}).get("timestamp") or first.get("file_id", {}).get("time_created")
    sport = s.get("sport") or first.get("sport", {}).get("sport")
    sub_sport = s.get("sub_sport")
    if isinstance(sport, str) and isinstance(sub_sport, str) and sub_sport not in ("generic", "street"):
        sport = f"{sub_sport} {sport}"  # e.g. "trail running", so it maps to "Trail Run"
    name = first.get("sport", {}).get("name")
    return ParsedTrack(
        points=points,
        start=start if isinstance(start, datetime) else None,
        sport=sport if isinstance(sport, str) else None,
        name=name if isinstance(name, str) else None,
        distance_m=total("total_distance"),
        moving_s=total("total_timer_time"),
        elev_m=total("total_ascent"),
    )


def _value(frame: Any, name: str) -> Any:
    return frame.get_value(name) if frame.has_field(name) else None
