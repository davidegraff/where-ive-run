"""Offline city names from a tiny, hand-made GeoNames file."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from server.geonames import CORRECTIONS_FILE, GeoNames, _read_corrections, ensure_downloaded
from server.main import create_app
from server.settings import Settings

FIXTURES = Path(__file__).parent / "fixtures"

# id, name, lat, lng, feature code, country, admin1, admin2 (county), admin3 (municipality), population
TOWNS = [
    ("1", "Boston", 42.35843, -71.05977, "PPLA", "US", "MA", "025", "07000", 653_833),
    ("2", "Back Bay", 42.35, -71.08, "PPL", "US", "MA", "025", "07000", 17_577),  # listed as a town
    ("3", "Dorchester", 42.30, -71.06, "PPL", "US", "MA", "025", "07000", 97_826),  # also Boston's code
    ("4", "Beacon Hill", 42.35871, -71.06783, "PPLX", "US", "MA", "025", "", 9_305),  # marked as a neighbourhood
    ("5", "Chelsea", 42.39176, -71.03283, "PPL", "US", "MA", "025", "13205", 39_398),  # same county, own code
    ("6", "Natick", 42.28343, -71.3495, "PPL", "US", "MA", "017", "43895", 37_006),
    ("7", "New York City", 40.71427, -74.00597, "PPL", "US", "NY", "", "", 8_804_190),  # no county: boroughs instead
    ("8", "Brooklyn", 40.6501, -73.94958, "PPLA2", "US", "NY", "047", "", 2_736_074),
    ("9", "Queens", 40.68149, -73.83652, "PPLA2", "US", "NY", "081", "", 2_316_841),
    ("10", "Manhattan", 40.78343, -73.96625, "PPLA2", "US", "NY", "061", "", 1_487_536),
    ("11", "Astoria", 40.77205, -73.93014, "PPLX", "US", "NY", "081", "", 78_793),  # in Queens, nearer Manhattan
    ("12", "Somewhere", 44.0, -72.0, "PPLX", "US", "VT", "", "", 2_000),  # a neighbourhood of nowhere: never named
    ("13", "Lonelyville", 44.1, -72.1, "PPL", "US", "VT", "001", "", 1_500),
    ("4174402", "Sunrise", 26.13397, -80.1131, "PPL", "US", "FL", "011", "", 84_439),  # misplaced: corrected below
    ("14", "Fort Lauderdale", 26.12231, -80.14338, "PPLA2", "US", "FL", "011", "", 183_146),
    ("15", "London", 51.50853, -0.12574, "PPLC", "GB", "ENG", "GLA", "", 8_961_989),
    ("16", "Paris", 48.85341, 2.3488, "PPLC", "FR", "11", "75", "751", 2_138_551),
    ("17", "Los Angeles", 34.05223, -118.24368, "PPLA2", "US", "CA", "037", "", 3_820_914),
    ("18", "Beverly Hills", 34.07362, -118.40036, "PPLX", "US", "CA", "037", "", 34_869),  # a city, marked as a neighbourhood
    ("19", "Hollywood", 34.09834, -118.32674, "PPLX", "US", "CA", "037", "", 167_664),  # a real neighbourhood
]

CORRECTIONS = """
[[fix]]
geonameid = "4174402"
name = "Sunrise"
latitude = 26.1667
longitude = -80.2788
why = "Misplaced on Fort Lauderdale's beach."
source = "OpenStreetMap"

[[fix]]
geonameid = "18"
name = "Beverly Hills"
separate_town = true
why = "A separate city."
source = "OpenStreetMap"

[[add]]
name = "Mount Washington"
latitude = 42.0996
longitude = -73.4540
population = 160
country = "US"
admin1 = "MA"
admin2 = "003"
why = "Too small for GeoNames' list."
source = "OpenStreetMap"
"""


def write_corrections(path: Path, text: str = CORRECTIONS) -> Path:
    path.write_text(text)
    return path


def write_geonames(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for gid, name, lat, lng, code, country, admin1, admin2, admin3, pop in TOWNS:
        cols = [gid, name, name, "", str(lat), str(lng), "P", code, country, "", admin1, admin2, admin3, "", str(pop), "", "", "", ""]
        rows.append("\t".join(cols))
    with zipfile.ZipFile(directory / "cities1000.zip", "w") as z:
        z.writestr("cities1000.txt", "\n".join(rows) + "\n")
    (directory / "admin1CodesASCII.txt").write_text("US.MA\tMassachusetts\tMassachusetts\t1\nUS.NY\tNew York\tNew York\t2\n"
                                                     "US.FL\tFlorida\tFlorida\t3\nUS.VT\tVermont\tVermont\t4\n")
    (directory / "countryInfo.txt").write_text(
        "#ISO\tISO3\tISO-Numeric\tfips\tCountry\n"
        "US\tUSA\t840\tUS\tUnited States\nGB\tGBR\t826\tUK\tUnited Kingdom\nFR\tFRA\t250\tFR\tFrance\n"
    )
    return directory


@pytest.fixture
def index(tmp_path: Path) -> GeoNames:
    return GeoNames(write_geonames(tmp_path / "geonames"), write_corrections(tmp_path / "corrections.toml"))


def test_towns_sharing_a_citys_municipality_code_are_named_after_it(index: GeoNames) -> None:
    assert index((42.3503, -71.0810)).city == "Boston"  # at Back Bay's centre
    assert index((42.2980, -71.0590)).city == "Boston"  # at Dorchester's: big, but Boston's code


def test_neighbourhoods_are_never_named(index: GeoNames) -> None:
    assert index((42.35871, -71.06783)).city == "Boston"  # Beacon Hill
    assert index((44.0, -72.0)).city == "Lonelyville"  # a neighbourhood with no city found: left out


def test_separate_towns_keep_their_names(index: GeoNames) -> None:
    assert index((42.3918, -71.0328)).city == "Chelsea"  # next to Boston, same county, own code
    place = index((42.2850, -71.3480))
    assert (place.city, place.region, place.country) == ("Natick", "MA, USA", "United States")


def test_new_york_is_named_by_borough(index: GeoNames) -> None:
    assert index((40.6710, -73.9814)).city == "Brooklyn"  # Park Slope
    assert index((40.7549, -73.9840)).city == "Manhattan"  # Midtown, where New York City's own point is close
    assert index((40.7718, -73.9300)).city == "Queens"  # in Astoria: a neighbourhood, known to be in Queens


def test_corrections_move_misplaced_towns(index: GeoNames) -> None:
    assert index((26.1340, -80.1180)).city == "Fort Lauderdale"  # where GeoNames wrongly puts Sunrise
    assert index((26.1667, -80.2788)).city == "Sunrise"  # where Sunrise really is


def test_corrections_can_mark_separate_towns(index: GeoNames) -> None:
    assert index((34.0736, -118.4004)).city == "Beverly Hills"
    assert index((34.0983, -118.3267)).city == "Los Angeles"  # Hollywood stays a neighbourhood


def test_corrections_can_add_towns(index: GeoNames) -> None:
    place = index((42.094, -73.454))
    assert (place.city, place.region) == ("Mount Washington", "MA, USA")


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ('[[fix]]\ngeonameid = "1"\nname = "Bostn"\nwhy = "x"\nsource = "y"\n', "GeoNames id 1 is 'Boston', not 'Bostn'"),
        ('[[fix]]\ngeonameid = "1"\nname = "Boston"\nlattitude = 1\nwhy = "x"\nsource = "y"\n', "unknown field"),
        ('[[fix]]\ngeonameid = "1"\nname = "Boston"\nlatitude = 1.0\n', "missing source, why"),
        ('[[remove]]\nname = "Boston"\n', "unknown section"),
    ],
)
def test_corrections_file_mistakes_are_errors(tmp_path: Path, text: str, error: str) -> None:
    directory = write_geonames(tmp_path / "geonames")
    with pytest.raises(ValueError, match=error):
        GeoNames(directory, write_corrections(tmp_path / "c.toml", text))


def test_a_fix_for_an_id_geonames_no_longer_has_is_reported(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    text = '[[fix]]\ngeonameid = "999"\nname = "Gone"\nlatitude = 1.0\nwhy = "x"\nsource = "y"\n'
    GeoNames(write_geonames(tmp_path / "geonames"), write_corrections(tmp_path / "c.toml", text))
    assert "no GeoNames entry with id 999" in caplog.text


def test_the_real_corrections_file_is_valid() -> None:
    fixes, additions = _read_corrections(CORRECTIONS_FILE)
    assert fixes and additions
    assert all(entry["why"] and entry["source"] for entry in [*fixes.values(), *additions])


def test_the_version_changes_with_the_corrections(tmp_path: Path) -> None:
    directory = write_geonames(tmp_path / "geonames")
    a = GeoNames(directory, write_corrections(tmp_path / "c.toml")).version
    assert GeoNames(directory, write_corrections(tmp_path / "c.toml")).version == a
    changed = GeoNames(directory, write_corrections(tmp_path / "c.toml", CORRECTIONS.replace("160", "170"))).version
    assert changed != a


def test_regions_outside_the_us_are_the_country(index: GeoNames) -> None:
    assert (index((51.5, -0.12)).city, index((51.5, -0.12)).region) == ("London", "United Kingdom")
    assert index((48.86, 2.35)).region == "France"


def test_far_from_any_town(index: GeoNames) -> None:
    assert index((49.5, 1.0)).city == "Paris"  # ~130 km away: found by widening the search
    assert index((-45.0, -140.0)).city == "Unknown"  # the middle of the Pacific


def test_download_writes_complete_files_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        content = b"data"

        def raise_for_status(self) -> None:
            pass

    fetched: list[str] = []

    def fake_get(url: str, timeout: float) -> Response:
        fetched.append(url)
        return Response()

    monkeypatch.setattr("server.geonames.requests.get", fake_get)
    target = tmp_path / "geonames"
    (target).mkdir()
    (target / "countryInfo.txt").write_text("already here")
    ensure_downloaded(target)
    assert sorted(p.name for p in target.iterdir()) == ["admin1CodesASCII.txt", "cities1000.zip", "countryInfo.txt"]
    assert (target / "countryInfo.txt").read_text() == "already here"  # not downloaded again
    assert len(fetched) == 2


def test_names_every_activity_on_import(tmp_path: Path) -> None:
    write_geonames(tmp_path / "geonames")
    settings = Settings(data_dir=tmp_path, static_dir=None, import_processes=0)  # geocoder="geonames" is the default
    with TestClient(create_app(settings)) as client:
        ids = []
        for name in ("run.gpx", "ride.tcx", "trail-run.fit"):  # Boston, London, Paris
            r = client.post("/api/uploads", content=(FIXTURES / name).read_bytes(), headers={"X-Filename": name})
            ids.append(r.json()["upload_id"])
        client.post("/api/imports", json={"uploads": ids})
        assert client.app.state.cities.wait_idle(timeout=10)  # type: ignore[attr-defined]
        activities: list[dict[str, Any]] = client.get("/api/activities").json()["activities"]
        assert [(a["city"], a["region"]) for a in activities] == [
            ("Boston", "MA, USA"), ("London", "United Kingdom"), ("Paris", "France"),
        ]
        assert client.get("/api/cities").json()["error"] is None
