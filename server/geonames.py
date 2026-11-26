"""Offline city names from GeoNames (https://www.geonames.org, CC BY 4.0).

GeoNames publishes every town in the world with at least 1,000 people (about 170,000 of them) as a
plain text file of names, coordinates and populations. With it the server can name the city an
activity started in without asking anyone: no rate limit, no network, and no coordinates leave the
server. The files (about 11 MB) are downloaded once, into DATA_DIR/geonames/, the first time they're
needed, or ahead of time with:

    uv run python -m server.geonames

How a city is chosen. GeoNames has only each town's centre point, not its boundary, so:

1. Nearby towns are scored by distance divided by population ** SIZE_WEIGHT, and the lowest score
   wins: being close counts most, but a large city can win over a small place slightly closer.
2. Neighbourhoods are never named: the city they're part of is (see _find_parents). GeoNames marks
   many neighbourhoods as such (feature code PPLX: Astoria, Jamaica Plain, Hollywood). Those still
   help to place a start (Astoria is in Queens), but are always named after their city. It lists
   others as ordinary towns (Back Bay, Mission Hill and Dorchester in Boston); a town counts as part
   of a bigger place if it shares that place's municipality code (Back Bay and Boston are both
   07000), or has no municipality code at all and lies within a much bigger place's area. Separate
   towns next door keep their names (Chelsea, Cambridge, Brookline each have their own code).
   GeoNames also marks a few real cities as neighbourhoods (Beverly Hills is PPLX, inside Los
   Angeles); the corrections file below marks those as towns.
3. A city made of county-level boroughs is named by borough: New York is Brooklyn, Queens,
   Manhattan, The Bronx or Staten Island (see _borough_cities).

Areas are estimated from population (CITY_DENSITY), since GeoNames has no boundaries.

The data comes from two places, kept apart: GeoNames' files exactly as downloaded, and our own
corrections in geonames-corrections.toml (entries GeoNames has wrong, and towns too small for its
list). This module only reads them: to change a name, change the data. `version` fingerprints the
data and these rules together, so the server can re-name activities when either changes.
"""

from __future__ import annotations

import hashlib
import io
import logging
import math
import sys
import threading
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from server.models import LatLng
from server.store import Place

log = logging.getLogger(__name__)

BASE_URL = "https://download.geonames.org/export/dump/"
FILES = ["cities1000.zip", "admin1CodesASCII.txt", "countryInfo.txt"]

SIZE_WEIGHT = 0.4
"""How much a place's population counts against its distance (0 = simply the nearest)."""
CENTRE_KM = 0.5
"""Added to every distance, so that right at a small place's centre, size still counts a little."""
CELL_DEG = 0.25
"""Grid cell size for finding nearby places quickly."""
SEARCH_CELLS = 2
"""Cells searched in each direction (about 50 km); widened up to MAX_SEARCH_CELLS if that's empty."""
MAX_SEARCH_CELLS = 8

# Feature codes for populated places that no longer exist: historical, abandoned, destroyed, and
# historical capitals. (PPLX, "section of a populated place", is a neighbourhood: kept, see above.)
SKIP_FEATURES = {"PPLH", "PPLQ", "PPLW", "PPLCH"}
NEIGHBOURHOOD = "PPLX"

CORRECTIONS_FILE = Path(__file__).with_name("geonames-corrections.toml")

CITY_DENSITY = 3000
"""People per km², for estimating a city's area from its population (GeoNames has no boundaries).
On the low side for a city centre, so estimated areas err towards too big."""
PART_OF_RATIO = 10
"""A town without a municipality code is only folded into a place at least this many times its size."""
SAME_CODE_RATIO = 2
"""A town sharing a place's municipality code is folded into it if that place is at least this many
times its size (the shared code is strong evidence: Dorchester has 98,000 people, Boston 650,000)."""
MIN_PARENT_POPULATION = 5000
SAME_CODE_REACH = 1.5
"""A town sharing a bigger place's municipality code is part of it if within this many of its radii.
(The code alone isn't enough: in some US states it's a township holding several separate places.)"""
BOROUGH_SHARE = 0.1
"""A borough must have at least this share of its city's population."""


@dataclass(slots=True)  # slots: about 170,000 of these are kept in memory
class _Town:
    name: str
    lat: float
    lng: float
    population: int
    weight: float
    """population ** SIZE_WEIGHT"""
    region: str
    country: str
    feature: str
    county: tuple[str, str, str]
    """(country, admin1, admin2): state and county, or their equivalents."""
    municipality: tuple[str, ...] | None
    """The most detailed admin code GeoNames has (commune, municipality, ...), if any."""
    named_as: int = -1
    """Index of the town whose name is used for this one: itself, or the city it's part of."""
    separate: bool = False
    """Set by the corrections file: a town in its own right, never named after a bigger place."""

    @property
    def neighbourhood(self) -> bool:
        return self.feature == NEIGHBOURHOOD

    @property
    def radius_km(self) -> float:
        return math.sqrt(self.population / CITY_DENSITY / math.pi)


class GeoNames:
    """An in-memory index of GeoNames towns, with our corrections applied. Loading takes a second or two."""

    def __init__(self, directory: Path, corrections: Path = CORRECTIONS_FILE) -> None:
        self.version = data_version(directory, corrections)
        countries = _countries(directory / "countryInfo.txt")
        states = _us_states(directory / "admin1CodesASCII.txt")
        fixes, additions = _read_corrections(corrections)
        unused = set(fixes)

        self._towns: list[_Town] = []
        self._grid: dict[tuple[int, int], list[int]] = {}

        def add(name: str, lat: float, lng: float, feature: str, country_code: str, admin: list[str], population: int,
                separate: bool = False) -> None:
            if feature in SKIP_FEATURES:
                return
            country = countries.get(country_code, country_code)
            if country_code == "US":
                region = f"{admin[0]}, USA" if admin[0] in states else "USA"
            else:
                region = country
            population = max(population, 1)
            municipality = (country_code, *admin) if admin[3] else (country_code, *admin[:3]) if admin[2] else None
            self._towns.append(_Town(name, lat, lng, population, population ** SIZE_WEIGHT, region, country, feature,
                                     (country_code, admin[0], admin[1]), municipality, separate=separate))

        with zipfile.ZipFile(directory / "cities1000.zip") as z, z.open("cities1000.txt") as f:
            for line in io.TextIOWrapper(f, encoding="utf-8"):
                # Columns: id, name, asciiname, alternatenames, lat, lng, feature class, feature code,
                # country, cc2, admin1, admin2, admin3, admin4, population, ...
                c = line.rstrip("\n").split("\t")
                lat, lng, feature, population = float(c[4]), float(c[5]), c[7], int(c[14] or 0)
                fix = fixes.get(c[0])
                if fix:
                    unused.discard(c[0])
                    if fix["name"] != c[1]:
                        raise ValueError(f"{corrections.name}: GeoNames id {c[0]} is {c[1]!r}, not {fix['name']!r}")
                    lat, lng = fix.get("latitude", lat), fix.get("longitude", lng)
                    feature, population = fix.get("feature_code", feature), fix.get("population", population)
                    if fix.get("separate_town"):
                        feature = "PPL" if feature == NEIGHBOURHOOD else feature
                add(c[1], lat, lng, feature, c[8], [c[10], c[11], c[12], c[13]], population,
                    separate=bool(fix and fix.get("separate_town")))
        if unused:
            # Not an error: GeoNames may have dropped or merged the entry. The fix can probably go.
            log.warning("%s: no GeoNames entry with id %s; is the fix still needed?", corrections.name, ", ".join(sorted(unused)))
        for a in additions:
            add(a["name"], a["latitude"], a["longitude"], "PPL", a["country"], [a["admin1"], a.get("admin2", ""), "", ""],
                a["population"])

        dropped = self._borough_cities()
        for i, t in enumerate(self._towns):
            t.named_as = i
            if i not in dropped:
                self._grid.setdefault(_cell(t.lat, t.lng), []).append(i)
        self._find_parents()
        # A neighbourhood whose city wasn't found is left out rather than named.
        for cell in self._grid.values():
            cell[:] = [i for i in cell if not (self._towns[i].neighbourhood and self._towns[i].named_as == i)]
        parts = sum(1 for i, t in enumerate(self._towns) if t.named_as != i)
        log.info("Loaded %d GeoNames towns (%d named after the city they're part of)", len(self._towns), parts)

    def _near(self, lat: float, lng: float, km: float) -> list[tuple[float, int]]:
        """(distance, index) of every indexed town within `km` of a point."""
        cos_lat = max(math.cos(math.radians(lat)), 0.01)
        cy, cx = _cell(lat, lng)
        dy_cells = math.ceil(km / 111.32 / CELL_DEG)
        dx_cells = math.ceil(km / (111.32 * cos_lat) / CELL_DEG)
        out = []
        for dy in range(-dy_cells, dy_cells + 1):
            for dx in range(-dx_cells, dx_cells + 1):
                for i in self._grid.get((cy + dy, cx + dx), ()):
                    t = self._towns[i]
                    d = math.hypot((t.lat - lat) * 111.32, (t.lng - lng) * 111.32 * cos_lat)
                    if d <= km:
                        out.append((d, i))
        return out

    def _borough_cities(self) -> set[int]:
        """Cities that are named by borough instead: a city with no county of its own that contains
        two or more county seats (PPLA2) of its state, each with at least BOROUGH_SHARE of its
        people. New York City (Brooklyn, Queens, Manhattan, The Bronx); also a few cities organised
        the same way elsewhere, such as Izmir and Luanda."""
        seats: dict[tuple[str, str], list[_Town]] = {}
        for t in self._towns:
            if t.feature == "PPLA2":
                seats.setdefault(t.county[:2], []).append(t)
        dropped = set()
        for i, t in enumerate(self._towns):
            if t.neighbourhood or t.county[2] or t.population < 200_000:
                continue
            inside = [s for s in seats.get(t.county[:2], []) if s is not t and s.population >= BOROUGH_SHARE * t.population
                      and _km(t.lat, t.lng, s.lat, s.lng) <= t.radius_km]
            if len(inside) >= 2:
                dropped.add(i)
        return dropped

    def _find_parents(self) -> None:
        """Point each neighbourhood at the city it's part of (named_as). Done from the bigger
        places' side: for each place, look at the smaller ones within its reach."""
        for p_index, p in enumerate(self._towns):
            if p.neighbourhood or p.population < MIN_PARENT_POPULATION or p_index not in self._grid.get(_cell(p.lat, p.lng), ()):
                continue
            for d, i in self._near(p.lat, p.lng, SAME_CODE_REACH * p.radius_km):
                t = self._towns[i]
                if i == p_index or t.separate or p.population <= t.population:
                    continue
                same_area = t.county == p.county or (t.county[:2] == p.county[:2] and not t.county[2])
                if not same_area:
                    continue
                same_code = bool(t.municipality) and t.municipality == p.municipality
                if t.neighbourhood:  # known to be part of somewhere: the biggest place around it that fits
                    fits = same_code or not t.municipality
                elif same_code:
                    fits = p.population >= SAME_CODE_RATIO * t.population
                else:
                    fits = not t.municipality and d <= p.radius_km and p.population >= PART_OF_RATIO * t.population
                if fits:
                    current = self._towns[t.named_as]
                    if t.named_as == i or p.population > current.population:
                        t.named_as = p_index

    def __call__(self, at: LatLng) -> Place:
        lat, lng = at
        cos_lat = math.cos(math.radians(lat))
        cy, cx = _cell(lat, lng)
        for reach in range(SEARCH_CELLS, MAX_SEARCH_CELLS + 1, 2):
            best: _Town | None = None
            best_score = math.inf
            for dy in range(-reach, reach + 1):
                for dx in range(-reach, reach + 1):
                    for i in self._grid.get((cy + dy, cx + dx), ()):
                        t = self._towns[i]
                        km = math.hypot((t.lat - lat) * 111.32, (t.lng - lng) * 111.32 * cos_lat)
                        score = (km + CENTRE_KM) / t.weight
                        if score < best_score:
                            best, best_score = t, score
            if best:
                named = self._towns[best.named_as]
                return Place(city=named.name, region=named.region, country=named.country)
        return Place(city="Unknown", region="", country="")


_FIX_FIELDS = {"geonameid", "name", "latitude", "longitude", "feature_code", "population", "separate_town", "why", "source"}
_ADD_FIELDS = {"name", "latitude", "longitude", "population", "country", "admin1", "admin2", "why", "source"}


def _read_corrections(path: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """The [[fix]] entries by GeoNames id, and the [[add]] entries. Every entry must say why."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    unknown_sections = set(data) - {"fix", "add"}
    if unknown_sections:
        raise ValueError(f"{path.name}: unknown section(s) {', '.join(sorted(unknown_sections))}; expected [[fix]] or [[add]]")
    for kind, fields, required in (("fix", _FIX_FIELDS, {"geonameid", "name", "why", "source"}),
                                   ("add", _ADD_FIELDS, {"name", "latitude", "longitude", "population", "country", "admin1", "why", "source"})):
        for entry in data.get(kind, []):
            label = f"{path.name}: [[{kind}]] {entry.get('name', '?')!r}"
            if extra := set(entry) - fields:
                raise ValueError(f"{label}: unknown field(s) {', '.join(sorted(extra))}")
            if missing := required - set(entry):
                raise ValueError(f"{label}: missing {', '.join(sorted(missing))}")
    fixes = {str(f["geonameid"]): f for f in data.get("fix", [])}
    return fixes, list(data.get("add", []))


def data_version(directory: Path, corrections: Path = CORRECTIONS_FILE) -> str:
    """A fingerprint of everything that decides a name: the downloaded GeoNames files, our
    corrections, and the rules in this file. If it changes, names may have changed."""
    h = hashlib.sha256()
    for name in FILES:
        st = (directory / name).stat()
        h.update(f"{name}:{st.st_size}:{st.st_mtime_ns};".encode())
    h.update(corrections.read_bytes())
    h.update(Path(__file__).read_bytes())
    return h.hexdigest()[:16]


def _cell(lat: float, lng: float) -> tuple[int, int]:
    return math.floor(lat / CELL_DEG), math.floor(lng / CELL_DEG)


def _km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    return math.hypot((lat1 - lat2) * 111.32, (lng1 - lng2) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2)))


def _countries(path: Path) -> dict[str, str]:
    """ISO code -> English name ("GB" -> "United Kingdom")."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            c = line.split("\t")
            out[c[0]] = c[4]
    return out


def _us_states(path: Path) -> set[str]:
    """US state codes ("MA", ...), so a missing or odd admin1 code isn't shown as a state."""
    return {line.split("\t", 1)[0][3:] for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("US.")}


# ---------- downloading ----------

_download_lock = threading.Lock()


def ensure_downloaded(directory: Path) -> None:
    """Download the GeoNames files that aren't there yet."""
    with _download_lock:
        directory.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            target = directory / name
            if target.exists():
                continue
            log.info("Downloading %s%s", BASE_URL, name)
            r = requests.get(BASE_URL + name, timeout=300)
            r.raise_for_status()
            partial = target.with_suffix(target.suffix + ".part")
            partial.write_bytes(r.content)
            partial.rename(target)  # only complete files ever have the real name


class LazyGeoNames:
    """A city lookup that downloads and loads GeoNames on first use, in the city-lookup thread,
    so starting the server stays instant."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._index: GeoNames | None = None
        self._lock = threading.Lock()

    def _load(self) -> GeoNames:
        with self._lock:
            if self._index is None:
                try:
                    ensure_downloaded(self.directory)
                except requests.RequestException as e:
                    raise RuntimeError(f"couldn't download the GeoNames city list ({e})") from e
                self._index = GeoNames(self.directory)
            return self._index

    def __call__(self, at: LatLng) -> Place:
        return self._load()(at)

    def version(self) -> str:
        """See data_version(). Loads the data first, so call it from the city-lookup thread."""
        return self._load().version


if __name__ == "__main__":
    from server.settings import Settings

    import truststore

    truststore.inject_into_ssl()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Settings.from_env().data_dir / "geonames"
    ensure_downloaded(target)
    print(f"GeoNames files are in {target}")
