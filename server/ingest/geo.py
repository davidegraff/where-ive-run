"""Small geometry helpers: polyline encoding, route thinning, distances."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timezone

from server.models import LatLng


def encode_polyline(points: Sequence[LatLng]) -> str:
    """Google encoded polyline, precision 5 (the page decodes it in web/polyline.ts)."""
    out: list[str] = []
    prev_lat = prev_lng = 0
    for lat, lng in points:
        ilat, ilng = round(lat * 1e5), round(lng * 1e5)
        for delta in (ilat - prev_lat, ilng - prev_lng):
            v = ~(delta << 1) if delta < 0 else delta << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        prev_lat, prev_lng = ilat, ilng
    return "".join(out)


def decode_polyline(text: str) -> list[LatLng]:
    points: list[LatLng] = []
    i = lat = lng = 0
    while i < len(text):
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                b = ord(text[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lng += deltas[1]
        points.append((lat / 1e5, lng / 1e5))
    return points


def thin(points: list[LatLng], min_m: float = 12) -> list[LatLng]:
    """Drop points closer than min_m metres to the last kept one (always keeps the last point)."""
    if not points:
        return points
    kept = [points[0]]
    for p in points[1:]:
        q = kept[-1]
        dy = (p[0] - q[0]) * 111_320
        dx = (p[1] - q[1]) * 111_320 * math.cos(math.radians(q[0]))
        if dx * dx + dy * dy >= min_m * min_m:
            kept.append(p)
    if kept[-1] is not points[-1]:
        kept.append(points[-1])
    return kept


def haversine(a: LatLng, b: LatLng) -> float:
    """Great-circle distance in metres."""
    r = 6_371_000
    d_lat, d_lng = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    s = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(d_lng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(s))


def path_length(points: Sequence[LatLng]) -> float:
    return sum(haversine(points[i - 1], points[i]) for i in range(1, len(points)))


def iso_no_zone(dt: datetime) -> str:
    """Format as UTC "YYYY-MM-DDTHH:MM:SS" (the Strava export uses UTC too)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(microsecond=0).isoformat()
