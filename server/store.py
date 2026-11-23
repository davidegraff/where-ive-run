"""SQLite storage (Python's built-in sqlite3).

Every activity and import belongs to a user id; see auth.py for where that id comes from.
One connection is shared by the request handlers, the import threads and the city lookup, so every
method takes a lock.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from server.models import Activity, CityTag, ImportRecord, LatLng

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    user_id    TEXT NOT NULL,
    key        TEXT NOT NULL,
    source     TEXT NOT NULL,
    source_id  TEXT NOT NULL,
    name       TEXT NOT NULL,
    date       TEXT NOT NULL,
    type       TEXT NOT NULL,
    distance_m REAL NOT NULL,
    moving_s   REAL NOT NULL,
    elev_m     REAL NOT NULL,
    start_lat  REAL,
    start_lng  REAL,
    polyline   TEXT NOT NULL,
    url        TEXT,
    city       TEXT,
    region     TEXT,
    -- Increases each time a city is filled in, so the page can ask for "tags since N".
    city_seq   INTEGER,
    PRIMARY KEY (user_id, key)
);
CREATE INDEX IF NOT EXISTS activities_city_seq ON activities (user_id, city_seq);

CREATE TABLE IF NOT EXISTS imports (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    at         TEXT NOT NULL,
    file       TEXT NOT NULL,
    source     TEXT NOT NULL,
    label      TEXT NOT NULL,
    activities INTEGER NOT NULL
);

-- Reverse-geocode answers keyed by "lat,lng" (3 decimals). Shared by all users: it holds only place names.
CREATE TABLE IF NOT EXISTS places (
    key     TEXT PRIMARY KEY,
    city    TEXT NOT NULL,
    region  TEXT NOT NULL,
    country TEXT NOT NULL
);
"""

# Re-importing an activity keeps its city if the start point hasn't moved, so re-imports don't re-geocode.
_SAME_START = """((activities.start_lat IS NULL AND excluded.start_lat IS NULL)
    OR (abs(activities.start_lat - excluded.start_lat) < 1e-3 AND abs(activities.start_lng - excluded.start_lng) < 1e-3))"""

_UPSERT = f"""
INSERT INTO activities (user_id, key, source, source_id, name, date, type, distance_m, moving_s, elev_m,
                        start_lat, start_lng, polyline, url)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (user_id, key) DO UPDATE SET
    source = excluded.source, source_id = excluded.source_id, name = excluded.name, date = excluded.date,
    type = excluded.type, distance_m = excluded.distance_m, moving_s = excluded.moving_s,
    elev_m = excluded.elev_m, start_lat = excluded.start_lat, start_lng = excluded.start_lng,
    polyline = excluded.polyline, url = excluded.url,
    city     = CASE WHEN {_SAME_START} THEN activities.city     ELSE NULL END,
    region   = CASE WHEN {_SAME_START} THEN activities.region   ELSE NULL END,
    city_seq = CASE WHEN {_SAME_START} THEN activities.city_seq ELSE NULL END
"""


@dataclass
class Place:
    city: str
    region: str
    country: str


@dataclass
class Untagged:
    """An activity with a start point and no city yet, as the city lookup needs it."""

    key: str
    start: LatLng


class Store:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(SCHEMA)
        self._seq: int = self._db.execute("SELECT coalesce(max(city_seq), 0) FROM activities").fetchone()[0]

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """Run the block as one transaction, holding the lock."""
        with self._lock:
            self._db.execute("BEGIN")
            try:
                yield self._db
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ---------- activities ----------

    def activities(self, user: str) -> list[Activity]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM activities WHERE user_id = ? ORDER BY date, key", (user,)).fetchall()
        return [_to_activity(r) for r in rows]

    def put_activities(self, user: str, activities: list[Activity]) -> None:
        with self._tx() as db:
            db.executemany(
                _UPSERT,
                [
                    (user, a.key, a.source, a.source_id, a.name, a.date, a.type, a.distance_m, a.moving_s, a.elev_m,
                     a.start[0] if a.start else None, a.start[1] if a.start else None, a.polyline, a.url)
                    for a in activities
                ],
            )

    def clear(self, user: str) -> None:
        """Delete the user's activities and import history. The shared place-name cache is kept."""
        with self._tx() as db:
            db.execute("DELETE FROM activities WHERE user_id = ?", (user,))
            db.execute("DELETE FROM imports WHERE user_id = ?", (user,))

    # ---------- import history ----------

    def add_import(self, user: str, at: str, file: str, source: str, label: str, activities: int) -> None:
        with self._tx() as db:
            db.execute(
                "INSERT INTO imports (user_id, at, file, source, label, activities) VALUES (?, ?, ?, ?, ?, ?)",
                (user, at, file, source, label, activities),
            )

    def imports(self, user: str) -> list[ImportRecord]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, at, file, source, label, activities FROM imports WHERE user_id = ? ORDER BY id", (user,)
            ).fetchall()
        return [ImportRecord(**dict(r)) for r in rows]

    # ---------- city lookup ----------

    def users_with_untagged(self) -> list[str]:
        with self._lock:
            rows = self._db.execute(
                "SELECT DISTINCT user_id FROM activities WHERE city IS NULL AND start_lat IS NOT NULL"
            ).fetchall()
        return [r[0] for r in rows]

    def untagged(self, user: str) -> list[Untagged]:
        # Date order makes the clusters (and so the cache keys) the same from one run to the next.
        with self._lock:
            rows = self._db.execute(
                "SELECT key, start_lat, start_lng FROM activities"
                " WHERE user_id = ? AND city IS NULL AND start_lat IS NOT NULL ORDER BY date, key",
                (user,),
            ).fetchall()
        return [Untagged(key=r["key"], start=(r["start_lat"], r["start_lng"])) for r in rows]

    def count_untagged(self, user: str) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT count(*) FROM activities WHERE user_id = ? AND city IS NULL AND start_lat IS NOT NULL", (user,)
            ).fetchone()
        return int(row[0])

    def tag_cities(self, user: str, keys: list[str], place: Place) -> None:
        with self._tx() as db:
            for key in keys:
                self._seq += 1
                db.execute(
                    "UPDATE activities SET city = ?, region = ?, city_seq = ? WHERE user_id = ? AND key = ?",
                    (place.city, place.region, self._seq, user, key),
                )

    def city_cursor(self) -> int:
        """The latest city tag's sequence number. Read it before reading activities."""
        with self._lock:
            return self._seq

    def tags_since(self, user: str, cursor: int) -> tuple[list[CityTag], int]:
        """City names filled in after `cursor`, and the new cursor."""
        with self._lock:
            rows = self._db.execute(
                "SELECT key, city, region, city_seq FROM activities WHERE user_id = ? AND city_seq > ? ORDER BY city_seq",
                (user, cursor),
            ).fetchall()
        tags = [CityTag(key=r["key"], city=r["city"], region=r["region"] or "") for r in rows]
        return tags, (rows[-1]["city_seq"] if rows else max(cursor, 0))

    def place(self, key: str) -> Place | None:
        with self._lock:
            row = self._db.execute("SELECT city, region, country FROM places WHERE key = ?", (key,)).fetchone()
        return Place(**dict(row)) if row else None

    def put_place(self, key: str, place: Place) -> None:
        with self._tx() as db:
            db.execute(
                "INSERT OR REPLACE INTO places (key, city, region, country) VALUES (?, ?, ?, ?)",
                (key, place.city, place.region, place.country),
            )


def _to_activity(r: sqlite3.Row) -> Activity:
    return Activity(
        key=r["key"],
        source=r["source"],
        source_id=r["source_id"],
        name=r["name"],
        date=r["date"],
        type=r["type"],
        distance_m=r["distance_m"],
        moving_s=r["moving_s"],
        elev_m=r["elev_m"],
        start=(r["start_lat"], r["start_lng"]) if r["start_lat"] is not None else None,
        polyline=r["polyline"],
        url=r["url"],
        city=r["city"],
        region=r["region"] if r["city"] else None,
    )
