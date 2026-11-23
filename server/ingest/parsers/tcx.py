"""TCX (Garmin Training Center): <Activity Sport><Id/><Lap><Track><Trackpoint>..., mostly from Garmin."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from server.models import LatLng

from .track import ParsedTrack, elevation_gain, parse_time, to_float

NS = "{*}"


def parse_tcx(raw: bytes) -> ParsedTrack:
    root = ET.fromstring(raw.strip())
    points: list[LatLng] = []
    elevations: list[float] = []
    for tp in root.findall(f".//{NS}Trackpoint"):
        pos = tp.find(NS + "Position")
        if pos is not None:
            lat = to_float(pos.findtext(NS + "LatitudeDegrees"))
            lng = to_float(pos.findtext(NS + "LongitudeDegrees"))
            if lat is not None and lng is not None:
                points.append((lat, lng))
        if (alt := to_float(tp.findtext(NS + "AltitudeMeters"))) is not None:
            elevations.append(alt)

    # Lap totals are direct children of <Lap> (trackpoints have their own DistanceMeters).
    distance = moving = 0.0
    for lap in root.findall(f".//{NS}Lap"):
        distance += to_float(lap.findtext(NS + "DistanceMeters")) or 0
        moving += to_float(lap.findtext(NS + "TotalTimeSeconds")) or 0

    activity = root.find(f".//{NS}Activity")
    return ParsedTrack(
        points=points,
        start=parse_time(root.findtext(f".//{NS}Id")),
        sport=activity.get("Sport") if activity is not None else None,
        distance_m=distance or None,
        moving_s=moving or None,
        elev_m=elevation_gain(elevations),
    )
