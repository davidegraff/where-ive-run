#!/usr/bin/env python3
"""Tag every run in data/runs.json with the city it started in.

Usage:  python3 -I scripts/add_cities.py

Groups run start points within ~3 km, looks up each group's city once with
OpenStreetMap's Nominatim (1 request/second, per its usage policy), and caches
answers in data/geocode_cache.json so re-runs only look up new places.
Rewrites data/runs.json and data/runs.js with "city" and "region" fields.
"""
import json
import math
import os
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(DATA, "geocode_cache.json")
RADIUS_KM = 3.0



def km(a, b):
    dy = (a[0] - b[0]) * 111.32
    dx = (a[1] - b[1]) * 111.32 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


def cluster(points):
    """Greedy clustering with a grid index. Returns list of [center, [indices]]."""
    cells, groups = {}, []
    cell = RADIUS_KM / 111.32
    for i, p in points:
        cx, cy = int(p[0] // cell), int(p[1] // cell)
        best, best_d = None, RADIUS_KM
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for g in cells.get((cx + dx, cy + dy), []):
                    d = km(groups[g][0], p)
                    if d < best_d:
                        best, best_d = g, d
        if best is None:
            groups.append([list(p), [i]])
            cells.setdefault((cx, cy), []).append(len(groups) - 1)
        else:
            groups[best][1].append(i)
    return groups


def lookup(lat, lng):
    url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
        {"format": "jsonv2", "lat": f"{lat:.4f}", "lon": f"{lng:.4f}", "zoom": 10, "accept-language": "en"})
    req = urllib.request.Request(url, headers={"User-Agent": "personal-strava-heatmap/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        a = json.load(r).get("address", {})
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


def main():
    path = os.path.join(DATA, "runs.json")
    runs = json.load(open(path))
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    pts = [(i, r["start"]) for i, r in enumerate(runs) if r.get("start")]
    groups = cluster(pts)
    todo = [g for g in groups if f"{g[0][0]:.3f},{g[0][1]:.3f}" not in cache]
    print(f"{len(groups)} start areas, {len(todo)} to look up (about {len(todo)} seconds)...")
    for n, g in enumerate(groups):
        key = f"{g[0][0]:.3f},{g[0][1]:.3f}"
        if key not in cache:
            for attempt in range(3):
                try:
                    cache[key] = lookup(*g[0])
                    break
                except Exception as e:
                    print(f"  retry {key}: {e}")
                    time.sleep(5)
            else:
                cache[key] = {"city": "Unknown", "region": "", "country": ""}
            time.sleep(1.1)
            if n % 20 == 0:
                json.dump(cache, open(CACHE, "w"))
                print(f"  {n + 1}/{len(groups)}  {cache[key]['city']}, {cache[key]['region']}")
        for i in g[1]:
            runs[i]["city"] = cache[key]["city"]
            runs[i]["region"] = cache[key]["region"]
    json.dump(cache, open(CACHE, "w"))
    json.dump(runs, open(path, "w"))
    with open(os.path.join(DATA, "runs.js"), "w") as f:
        f.write("window.RUNS = " + json.dumps(runs) + ";\n")
    cities = {(r.get("city"), r.get("region")) for r in runs if r.get("city")}
    print(f"Done: {len(cities)} cities.")


if __name__ == "__main__":
    main()
