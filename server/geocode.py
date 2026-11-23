"""Names the city each activity started in, using OpenStreetMap's Nominatim.

Start points within ~3 km are grouped and looked up once; answers are cached in the places table.
Nominatim's usage policy allows at most 1 request per second *per application*, so the whole server
has a single background thread doing lookups, shared by all users. A first import of a few hundred
places takes a few minutes; the page picks up names as they arrive (GET /api/cities).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import requests

from server.models import LatLng
from server.store import Place, Store, Untagged

log = logging.getLogger(__name__)

RADIUS_KM = 3
GAP_S = 1.1
"""Pause between Nominatim requests."""

Lookup = Callable[[LatLng], Place]


def km(a: LatLng, b: LatLng) -> float:
    dy = (a[0] - b[0]) * 111.32
    dx = (a[1] - b[1]) * 111.32 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


@dataclass
class Cluster:
    center: LatLng
    members: list[Untagged] = field(default_factory=list)


def cluster(items: list[Untagged]) -> list[Cluster]:
    """Greedy clustering: each point joins the nearest existing cluster within RADIUS_KM, or starts
    a new one. A grid of RADIUS_KM-sized cells means only neighbouring cells need checking."""
    groups: list[Cluster] = []
    cells: dict[tuple[int, int], list[int]] = {}
    cell = RADIUS_KM / 111.32
    for item in items:
        p = item.start
        cx, cy = math.floor(p[0] / cell), math.floor(p[1] / cell)
        best, best_d = -1, float(RADIUS_KM)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for g in cells.get((cx + dx, cy + dy), []):
                    d = km(groups[g].center, p)
                    if d < best_d:
                        best, best_d = g, d
        if best < 0:
            groups.append(Cluster(center=p, members=[item]))
            cells.setdefault((cx, cy), []).append(len(groups) - 1)
        else:
            groups[best].members.append(item)
    return groups


def nominatim(user_agent: str) -> Lookup:
    """Reverse geocoding with Nominatim. The location is rounded to ~1 km: enough to name the city
    (zoom 10) without sending exact start points."""

    def lookup(at: LatLng) -> Place:
        params = {"format": "jsonv2", "lat": f"{at[0]:.2f}", "lon": f"{at[1]:.2f}", "zoom": "10", "accept-language": "en"}
        r = requests.get("https://nominatim.openstreetmap.org/reverse", params=params,
                         headers={"User-Agent": user_agent}, timeout=30)
        r.raise_for_status()
        a: dict[str, str] = r.json().get("address", {})
        city = (a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or a.get("hamlet")
                or a.get("suburb") or a.get("county") or a.get("state") or "Unknown")
        region = a.get("country", "")
        if a.get("country_code") == "us":
            iso = a.get("ISO3166-2-lvl4", "")
            state = iso.split("-")[-1] if iso.startswith("US-") else a.get("state")
            region = f"{state}, USA" if state else "USA"
        return Place(city=city, region=region, country=a.get("country", ""))

    return lookup


class CityLookup:
    """The background lookup. Call schedule() after an import (and once at startup); the thread
    works through every user's untagged activities, then waits. Places that fail three times are
    left untagged and retried the next time schedule() is called."""

    def __init__(self, store: Store, lookup: Lookup | None, gap_s: float = GAP_S, retry_s: float = 5) -> None:
        self.store, self.lookup = store, lookup
        self.gap_s, self.retry_s = gap_s, retry_s
        self._wake = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._stop = False
        self._thread: threading.Thread | None = None

    def schedule(self) -> None:
        if self.lookup is None:
            return
        self._idle.clear()
        self._wake.set()
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="city-lookup", daemon=True)
            self._thread.start()

    @property
    def active(self) -> bool:
        """True while lookups are queued or in flight."""
        return not self._idle.is_set()

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Block until the queue is empty (for tests and shutdown)."""
        return self._idle.wait(timeout)

    def stop(self) -> None:
        """Stop after the current lookup, and wait for that (call before closing the store)."""
        self._stop = True
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=35)

    def _run(self) -> None:
        while not self._stop:
            self._wake.wait()
            self._wake.clear()
            if self._stop:
                break
            try:
                for user in self.store.users_with_untagged():
                    self._tag_user(user)
            except Exception:
                log.exception("City lookup stopped")
            if not self._wake.is_set():  # nothing new was scheduled meanwhile
                self._idle.set()

    def _tag_user(self, user: str) -> None:
        assert self.lookup is not None
        for group in cluster(self.store.untagged(user)):
            if self._stop:
                return
            key = f"{group.center[0]:.3f},{group.center[1]:.3f}"
            place = self.store.place(key)
            if place is None:
                for _ in range(3):
                    try:
                        place = self.lookup(group.center)
                        break
                    except Exception as e:
                        log.warning("City lookup failed (%s), retrying", e)
                        time.sleep(self.retry_s)
                if place:
                    self.store.put_place(key, place)
                time.sleep(self.gap_s)
            if place:
                self.store.tag_cities(user, [m.key for m in group.members], place)
