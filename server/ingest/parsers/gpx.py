"""GPX: <trk><trkseg><trkpt lat lon><ele/><time/></trkpt>..., from almost any app or device."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from server.ingest.geo import path_length
from server.models import LatLng

from .track import ParsedTrack, elevation_gain, parse_time, to_float

# "{*}" matches any XML namespace, so both <trkpt> and <gpx:trkpt> are found.
NS = "{*}"


def parse_gpx(raw: bytes) -> ParsedTrack:
    root = ET.fromstring(raw.strip())
    points: list[LatLng] = []
    elevations: list[float] = []
    times = []
    for pt in root.findall(f".//{NS}trkpt"):
        lat, lon = to_float(pt.get("lat")), to_float(pt.get("lon"))
        if lat is None or lon is None:
            continue
        points.append((lat, lon))
        if (ele := to_float(pt.findtext(NS + "ele"))) is not None:
            elevations.append(ele)
        if (t := parse_time(pt.findtext(NS + "time"))) is not None:
            times.append(t)

    start = times[0] if times else parse_time(root.findtext(f"{NS}metadata/{NS}time"))
    trk = root.find(NS + "trk")
    return ParsedTrack(
        points=points,
        start=start,
        name=trk.findtext(NS + "name") if trk is not None else None,
        sport=trk.findtext(NS + "type") if trk is not None else None,
        distance_m=path_length(points),
        moving_s=(times[-1] - times[0]).total_seconds() if len(times) > 1 else None,
        elev_m=elevation_gain(elevations),
    )
