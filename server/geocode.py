"""Names the city each activity started in, in a background thread; the page picks up names as
they arrive (GET /api/cities).

There are two ways to look a city up (GEOCODER in settings.py):

- "geonames" (the default): offline, from a downloaded list of towns (see geonames.py). Each
  activity is named from its own start point, and a whole archive takes well under a second.
- "nominatim": OpenStreetMap's Nominatim web service, which knows real town boundaries but allows
  at most 1 request per second *per application*. Start points within ~3 km are grouped and looked
  up once, answers are cached in the places table, and one thread serves all users. A first import
  of a few hundred places takes a few minutes.
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

GIVE_UP_AFTER = 3
"""Stop for now after this many places in a row couldn't be looked up (the network or Nominatim is
probably down, and every remaining place would fail the same way). The next import retries."""


CITY_DATA_KEY = "city_data_version"
"""The meta key recording which version of the city data named the stored activities."""


class LookupStopped(Exception):
    pass


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
    works through every user's untagged activities, then waits.

    A place that fails three times is left untagged. If GIVE_UP_AFTER places fail in a row, the
    lookup stops and `error` says why; the next schedule() tries again."""

    def __init__(self, store: Store, lookup: Lookup | None, gap_s: float = GAP_S, retry_s: float = 5,
                 offline: bool = False, data_version: Callable[[], str] | None = None) -> None:
        self.store, self.lookup = store, lookup
        self.gap_s, self.retry_s = gap_s, retry_s
        self.offline = offline
        """True for a local lookup (GeoNames): name every activity on its own, with no pauses."""
        self.data_version = data_version
        """For a local lookup: a fingerprint of the data that decides names. When it differs from the
        one that named the stored activities, they're all named again (see _rename_if_data_changed)."""
        self._wake = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._stop = False
        self._thread: threading.Thread | None = None
        self.error: str | None = None
        """Why the last run stopped early, or None."""

    def schedule(self) -> None:
        if self.lookup is None:
            return
        self.error = None
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
                self._rename_if_data_changed()
                for user in self.store.users_with_untagged():
                    self._tag_user(user)
            except LookupStopped as e:
                self.error = str(e)
                log.error("City lookup stopped: %s", e)
            except Exception as e:
                self.error = "an internal error"
                log.exception("City lookup stopped: %s", e)
            if not self._wake.is_set():  # nothing new was scheduled meanwhile
                self._idle.set()

    def _rename_if_data_changed(self) -> None:
        if self.data_version is None:
            return
        try:
            version = self.data_version()
        except Exception as e:
            raise LookupStopped(str(e)) from e
        if self.store.meta(CITY_DATA_KEY) != version:
            cleared = self.store.clear_all_cities()
            self.store.set_meta(CITY_DATA_KEY, version)
            if cleared:
                log.info("City data changed (version %s): naming %d activities again", version, cleared)

    def _tag_user(self, user: str) -> None:
        if self.offline:
            self._tag_user_offline(user)
        else:
            self._tag_user_online(user)

    def _tag_user_offline(self, user: str) -> None:
        assert self.lookup is not None
        by_place: dict[tuple[str, str, str], list[str]] = {}
        for item in self.store.untagged(user):
            if self._stop:
                return
            try:
                place = self.lookup(item.start)
            except Exception as e:
                raise LookupStopped(str(e)) from e
            by_place.setdefault((place.city, place.region, place.country), []).append(item.key)
        for (city, region, country), keys in by_place.items():
            self.store.tag_cities(user, keys, Place(city, region, country))

    def _tag_user_online(self, user: str) -> None:
        assert self.lookup is not None
        failures_in_a_row = 0
        for group in cluster(self.store.untagged(user)):
            if self._stop:
                return
            key = f"{group.center[0]:.3f},{group.center[1]:.3f}"
            place = self.store.place(key)
            if place is None:
                problem = ""
                for attempt in range(3):
                    try:
                        place = self.lookup(group.center)
                        break
                    except Exception as e:
                        problem = _describe(e)
                        log.warning("City lookup failed (attempt %d of 3): %s", attempt + 1, problem)
                        time.sleep(self.retry_s)
                if place:
                    self.store.put_place(key, place)
                    failures_in_a_row = 0
                else:
                    failures_in_a_row += 1
                    if failures_in_a_row >= GIVE_UP_AFTER:
                        raise LookupStopped(f"couldn't reach OpenStreetMap ({problem})")
                time.sleep(self.gap_s)
            if place:
                self.store.tag_cities(user, [m.key for m in group.members], place)


def _describe(e: Exception) -> str:
    """A short reason for the page, instead of requests' very long exception messages."""
    if isinstance(e, requests.exceptions.SSLError):
        return "its HTTPS certificate couldn't be verified"
    if isinstance(e, requests.exceptions.ConnectionError):
        return "no connection"
    if isinstance(e, requests.exceptions.Timeout):
        return "timed out"
    if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
        return f"HTTP {e.response.status_code}"
    return str(e) or type(e).__name__
