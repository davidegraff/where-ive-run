#!/usr/bin/env python3
"""Tag every run in data/runs.json with the city it started in.

Usage:  uv run python -I scripts/add_cities.py

Groups run start points within ~3 km, looks up each group's city once with
OpenStreetMap's Nominatim (1 request/second, per its usage policy), and caches
answers in data/geocode_cache.json so re-runs only look up new places.
Rewrites data/runs.json and data/runs.js with "city" and "region" fields.
"""
from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Sequence
from typing import Any, TypedDict

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(DATA, "geocode_cache.json")
RADIUS_KM = 3.0
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "personal-strava-heatmap/1.0"


class Place(TypedDict):
    city: str
    region: str
    country: str


Point = Sequence[float]  # [lat, lng]
# One cluster: its center point and the indices of the runs that belong to it.
Group = tuple[list[float], list[int]]


def km(a: Point, b: Point) -> float:
    dy = (a[0] - b[0]) * 111.32
    dx = (a[1] - b[1]) * 111.32 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


def cluster(points: list[tuple[int, Point]]) -> list[Group]:
    """Greedy clustering with a grid index. Returns list of (center, [indices])."""
    cells: dict[tuple[int, int], list[int]] = {}
    groups: list[Group] = []
    cell = RADIUS_KM / 111.32
    for i, p in points:
        cx, cy = int(p[0] // cell), int(p[1] // cell)
        best: int | None = None
        best_d = RADIUS_KM
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for g in cells.get((cx + dx, cy + dy), []):
                    d = km(groups[g][0], p)
                    if d < best_d:
                        best, best_d = g, d
        if best is None:
            groups.append((list(p), [i]))
            cells.setdefault((cx, cy), []).append(len(groups) - 1)
        else:
            groups[best][1].append(i)
    return groups


def lookup(session: requests.Session, lat: float, lng: float) -> Place:
    params: dict[str, str | int] = {
        "format": "jsonv2",
        "lat": f"{lat:.4f}",
        "lon": f"{lng:.4f}",
        "zoom": 10,
        "accept-language": "en",
    }
    r = session.get(NOMINATIM_URL, params=params, timeout=30)
    r.raise_for_status()
    a: dict[str, str] = r.json().get("address", {})
    city = (a.get("city") or a.get("town") or a.get("village") or a.get("municipality")
            or a.get("hamlet") or a.get("suburb") or a.get("county") or a.get("state") or "Unknown")
    country = a.get("country", "")
    if a.get("country_code") == "us":
        iso = a.get("ISO3166-2-lvl4", "")
        region = iso.split("-")[-1] if iso.startswith("US-") else a.get("state", "")
        region = f"{region}, USA" if region else "USA"
    else:
        region = country
    return {"city": city, "region": region, "country": country}


def save_json(path: str, obj: Any) -> None:
    with open(path, "w") as f:
        json.dump(obj, f)


def main() -> None:
    path = os.path.join(DATA, "runs.json")
    with open(path) as f:
        runs: list[dict[str, Any]] = json.load(f)
    cache: dict[str, Place] = {}
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            cache = json.load(f)
    pts: list[tuple[int, Point]] = [(i, r["start"]) for i, r in enumerate(runs) if r.get("start")]
    groups = cluster(pts)
    todo = [g for g in groups if f"{g[0][0]:.3f},{g[0][1]:.3f}" not in cache]
    print(f"{len(groups)} start areas, {len(todo)} to look up (about {len(todo)} seconds)...")
    with requests.Session() as session:
        session.headers["User-Agent"] = USER_AGENT
        for n, (center, members) in enumerate(groups):
            key = f"{center[0]:.3f},{center[1]:.3f}"
            if key not in cache:
                for _attempt in range(3):
                    try:
                        cache[key] = lookup(session, center[0], center[1])
                        break
                    except (requests.RequestException, ValueError) as e:
                        print(f"  retry {key}: {e}")
                        time.sleep(5)
                else:
                    cache[key] = {"city": "Unknown", "region": "", "country": ""}
                time.sleep(1.1)
                if n % 20 == 0:
                    save_json(CACHE, cache)
                    print(f"  {n + 1}/{len(groups)}  {cache[key]['city']}, {cache[key]['region']}")
            for i in members:
                runs[i]["city"] = cache[key]["city"]
                runs[i]["region"] = cache[key]["region"]
    save_json(CACHE, cache)
    save_json(path, runs)
    with open(os.path.join(DATA, "runs.js"), "w") as f:
        f.write("window.RUNS = " + json.dumps(runs) + ";\n")
    cities = {(r.get("city"), r.get("region")) for r in runs if r.get("city")}
    print(f"Done: {len(cities)} cities.")


if __name__ == "__main__":
    main()
