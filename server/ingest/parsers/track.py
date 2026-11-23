"""What a single GPX / TCX / FIT file tells us, and mapping its sport name to an activity type."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from server.models import LatLng


@dataclass
class ParsedTrack:
    """Only `points` is guaranteed; everything else depends on what the file contains."""

    points: list[LatLng] = field(default_factory=list)
    start: datetime | None = None
    sport: str | None = None
    """Source-specific sport name, mapped to a Strava-style type by normalize_type()."""
    name: str | None = None
    distance_m: float | None = None
    moving_s: float | None = None
    elev_m: float | None = None


# First match wins, so the more specific patterns come first.
_TYPES: list[tuple[str, str]] = [
    (r"trailrun", "Trail Run"),
    (r"virtualrun|treadmill", "Virtual Run"),
    (r"run", "Run"),
    (r"mountainbik|mtb", "Mountain Bike Ride"),
    (r"gravel", "Gravel Ride"),
    (r"virtualride|indoorcycl|virtualactivity", "Virtual Ride"),
    (r"ebik", "E-Bike Ride"),
    (r"bik|cycl|ride", "Ride"),
    (r"hik", "Hike"),
    (r"walk", "Walk"),
    (r"swim", "Swim"),
    (r"backcountry|alpineski|downhillski|crosscountryski|nordicski|ski", "Ski"),
    (r"snowboard", "Snowboard"),
    (r"kayak", "Kayaking"),
    (r"canoe", "Canoeing"),
    (r"row", "Rowing"),
    (r"paddle|sup", "Stand Up Paddling"),
    (r"inlineskat|rollerskat", "Inline Skate"),
    (r"iceskat|skat", "Ice Skate"),
    (r"surf", "Surfing"),
    (r"climb", "Rock Climb"),
    (r"golf", "Golf"),
    (r"yoga", "Yoga"),
]


def normalize_type(sport: str | None) -> str:
    """Map sport names used by GPX / TCX / FIT / Garmin to Strava-style activity types."""
    if not sport:
        return "Workout"
    s = re.sub(r"[\s_-]+", "", sport.lower())
    for pattern, name in _TYPES:
        if re.search(pattern, s):
            return name
    if s in ("generic", "other", "all"):
        return "Workout"
    return sport[0].upper() + sport[1:]


def elevation_gain(elevations: list[float]) -> float:
    """Sum of climbs, ignoring wiggles under 3 m (GPS altitude noise)."""
    gain = 0.0
    ref: float | None = None
    for e in elevations:
        if ref is None:
            ref = e
        elif e > ref + 3:
            gain += e - ref
            ref = e
        elif e < ref:
            ref = e
    return gain


def parse_time(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.strip())
    except ValueError:
        return None


def to_float(text: str | None) -> float | None:
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None
