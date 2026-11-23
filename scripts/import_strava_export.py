#!/usr/bin/env python3
"""Build data/runs.js from a Strava bulk-export zip (no API needed).

Usage:  uv run python -I scripts/import_strava_export.py ~/Downloads/export_12345.zip

Reads the zip in place (nothing is extracted). Uses activities.csv for run
details and the GPX / TCX / FIT files in activities/ for the routes.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import math
import os
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Sequence
from datetime import datetime
from typing import Any, TypedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

LatLng = tuple[float, float]


class Run(TypedDict):
    id: str
    name: str
    date: str
    type: str
    distance_m: float
    moving_s: float
    elev_m: float
    start: list[float] | None
    polyline: str


def encode_polyline(pts: Sequence[LatLng]) -> str:
    out: list[str] = []
    plat, plng = 0, 0
    for lat, lng in pts:
        ilat, ilng = round(lat * 1e5), round(lng * 1e5)
        for d in (ilat - plat, ilng - plng):
            v = ~(d << 1) if d < 0 else d << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plat, plng = ilat, ilng
    return "".join(out)


def thin(pts: list[LatLng], min_m: float = 12) -> list[LatLng]:
    """Drop points closer than min_m metres to the last kept one."""
    if not pts:
        return pts
    kept = [pts[0]]
    for p in pts[1:]:
        q = kept[-1]
        dy = (p[0] - q[0]) * 111_320
        dx = (p[1] - q[1]) * 111_320 * math.cos(math.radians(q[0]))
        if dx * dx + dy * dy >= min_m * min_m:
            kept.append(p)
    if kept[-1] is not pts[-1]:
        kept.append(pts[-1])
    return kept


def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_gpx(raw: bytes) -> list[LatLng]:
    pts: list[LatLng] = []
    for el in ET.fromstring(raw).iter():
        if strip_ns(el.tag) == "trkpt" and "lat" in el.attrib:
            pts.append((float(el.attrib["lat"]), float(el.attrib["lon"])))
    return pts


def parse_tcx(raw: bytes) -> list[LatLng]:
    pts: list[LatLng] = []
    for el in ET.fromstring(raw.strip()).iter():
        if strip_ns(el.tag) == "Position":
            vals = {strip_ns(c.tag): c.text for c in el}
            lat, lng = vals.get("LatitudeDegrees"), vals.get("LongitudeDegrees")
            if lat and lng:
                pts.append((float(lat), float(lng)))
    return pts


def parse_fit(raw: bytes) -> list[LatLng]:
    import fitdecode  # type: ignore[import-untyped]
    pts: list[LatLng] = []
    k = 180 / 2 ** 31
    with fitdecode.FitReader(io.BytesIO(raw), check_crc=fitdecode.CrcCheck.DISABLED) as fit:
        for frame in fit:
            if isinstance(frame, fitdecode.FitDataMessage) and frame.name == "record":
                if frame.has_field("position_lat") and frame.has_field("position_long"):
                    lat, lng = frame.get_value("position_lat"), frame.get_value("position_long")
                    if lat is not None and lng is not None:
                        pts.append((lat * k, lng * k))
    return pts


def read_track(zf: zipfile.ZipFile, name: str) -> list[LatLng]:
    raw = zf.read(name)
    low = name.lower()
    if low.endswith(".gz"):
        raw, low = gzip.decompress(raw), low[:-3]
    if low.endswith(".gpx"):
        return parse_gpx(raw)
    if low.endswith(".tcx"):
        return parse_tcx(raw)
    if low.endswith(".fit"):
        return parse_fit(raw)
    return []


def num(v: Any) -> float:
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return 0.0


def parse_date(s: str) -> str:
    for fmt in ("%b %d, %Y, %I:%M:%S %p", "%d %b %Y, %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt).isoformat()
        except ValueError:
            pass
    return s


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: import_strava_export.py path/to/export.zip")
    zf = zipfile.ZipFile(os.path.expanduser(sys.argv[1]))
    csv_name = next((n for n in zf.namelist() if n.endswith("activities.csv")), None)
    if not csv_name:
        sys.exit("No activities.csv in that zip. Is it the Strava archive?")
    prefix = csv_name[: -len("activities.csv")]

    rows = list(csv.reader(io.TextIOWrapper(zf.open(csv_name), encoding="utf-8-sig")))
    header, rows = rows[0], rows[1:]

    def col(name: str, last: bool = False) -> int | None:
        idx = [i for i, h in enumerate(header) if h.strip() == name]
        return (idx[-1] if last else idx[0]) if idx else None

    c_id, c_date, c_name, c_type = col("Activity ID"), col("Activity Date"), col("Activity Name"), col("Activity Type")
    c_file = col("Filename")
    c_dist_m = col("Distance", last=True)   # later "Distance" column is metres
    c_dist_km = col("Distance")             # first one is in display units (km)
    c_moving = col("Moving Time")
    c_elapsed = col("Elapsed Time")
    c_elev = col("Elevation Gain")

    names = set(zf.namelist())
    runs: list[Run] = []
    failed = 0
    for r in rows:
        def get(c: int | None, r: list[str] = r) -> str:
            return r[c] if c is not None and c < len(r) else ""

        if not get(c_type):
            continue
        dist = num(get(c_dist_m))
        if c_dist_m == c_dist_km:
            dist *= 1000
        pts: list[LatLng] = []
        fname = get(c_file)
        if fname and prefix + fname in names:
            try:
                pts = thin(read_track(zf, prefix + fname))
            except Exception as e:  # corrupt/odd file: keep the run, skip the route
                failed += 1
                print(f"  could not read {fname}: {e}")
        runs.append({
            "id": get(c_id),
            "name": get(c_name),
            "date": parse_date(get(c_date)),
            "type": get(c_type),
            "distance_m": dist,
            "moving_s": num(get(c_moving)) or num(get(c_elapsed)),
            "elev_m": num(get(c_elev)),
            "start": list(pts[0]) if pts else None,
            "polyline": encode_polyline(pts) if len(pts) > 1 else "",
        })
        if len(runs) % 100 == 0:
            print(f"  {len(runs)} activities read...")

    runs.sort(key=lambda x: x["date"])
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "runs.json"), "w") as f:
        json.dump(runs, f)
    with open(os.path.join(DATA, "runs.js"), "w") as f:
        f.write("window.RUNS = " + json.dumps(runs) + ";\n")
    with_gps = sum(1 for x in runs if x["polyline"])
    km = sum(x["distance_m"] for x in runs) / 1000
    print(f"\nDone: {len(runs)} activities ({with_gps} with GPS routes, {failed} unreadable files), {km:,.0f} km.")
    print("\nTagging runs with their cities...")
    import subprocess
    subprocess.run([sys.executable, "-I", os.path.join(ROOT, "scripts", "add_cities.py")], check=True)
    print("Saved data/runs.js. Open heatmap.html to see the map.")


if __name__ == "__main__":
    main()
