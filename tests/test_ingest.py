"""Parsers, geometry helpers and the import pipeline, without the HTTP server."""

from __future__ import annotations

import multiprocessing as mp
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from server.ingest.adapters.strava_archive import parse_strava_date
from server.ingest.geo import decode_polyline, encode_polyline, thin
from server.ingest.parsers import normalize_type, parse_track_file
from server.ingest.pipeline import Batch, InputFile, PipelineEvent, run_import
from server.models import Activity, SourceSummary

FIXTURES = Path(__file__).parent / "fixtures"


def read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ---------- geometry ----------


def test_polyline_round_trip() -> None:
    pts = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
    encoded = encode_polyline(pts)
    assert encoded == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"  # Google's documented example (web/polyline.test.ts too)
    assert decode_polyline(encoded) == pts


def test_thin_drops_close_points_but_keeps_the_last() -> None:
    pts = [(0.0, 0.0), (0.00001, 0.0), (0.00002, 0.0), (0.001, 0.0), (0.00101, 0.0)]
    assert thin(pts) == [(0.0, 0.0), (0.001, 0.0), (0.00101, 0.0)]


# ---------- parsers ----------


def test_gpx() -> None:
    t = parse_track_file("run.gpx", read("run.gpx"))
    assert t.points == [(42.36, -71.06), (42.361, -71.06), (42.362, -71.06)]
    assert t.name == "Lunch & Run"
    assert t.sport == "running"
    assert t.start is not None and t.start.isoformat() == "2020-05-01T10:00:00+00:00"
    assert t.moving_s == 120
    assert t.distance_m is not None and 220 < t.distance_m < 225
    assert t.elev_m == 5


def test_tcx_skips_trackpoints_without_a_position() -> None:
    t = parse_track_file("ride.tcx", read("ride.tcx"))
    assert t.points == [(51.5, -0.12), (51.51, -0.12)]
    assert t.sport == "Biking"
    assert t.distance_m == 5000
    assert t.moving_s == 600
    assert t.elev_m == 10
    assert t.start is not None and t.start.isoformat() == "2021-07-04T08:30:00+00:00"


def test_fit() -> None:
    t = parse_track_file("trail-run.fit", read("trail-run.fit"))
    assert len(t.points) == 3
    assert t.points[0] == pytest.approx((48.85, 2.35), abs=1e-6)
    assert t.start is not None and t.start.isoformat() == "2022-03-05T07:00:00+00:00"
    assert normalize_type(t.sport) == "Trail Run"
    assert t.distance_m == pytest.approx(222.5)
    assert t.moving_s == 120
    assert t.elev_m == 7


def test_gzipped_track_file() -> None:
    import gzip

    t = parse_track_file("run.gpx.gz", gzip.compress(read("run.gpx")))
    assert len(t.points) == 3


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Dec 6, 2018, 12:09:18 PM", "2018-12-06T12:09:18"),
        ("Jan 1, 2020, 12:05:00 AM", "2020-01-01T00:05:00"),
        ("Jul 4, 2021, 3:07:09 PM", "2021-07-04T15:07:09"),
        ("Jul 4, 2021, 3:07:09 PM", "2021-07-04T15:07:09"),
        ("Sept 4, 2021, 3:07:09 PM", "2021-09-04T15:07:09"),
        ("6 Dec 2018, 13:09:18", "2018-12-06T13:09:18"),
        ("2018-12-06 12:09:18", "2018-12-06T12:09:18"),
    ],
)
def test_strava_dates(text: str, expected: str) -> None:
    assert parse_strava_date(text) == expected


@pytest.mark.parametrize(
    ("sport", "expected"),
    [("running", "Run"), ("Biking", "Ride"), ("cycling", "Ride"), ("hiking", "Hike"), ("trail running", "Trail Run"),
     ("generic", "Workout"), (None, "Workout"), ("kitesurfing", "Surfing"), ("pickleball", "Pickleball")],
)
def test_normalize_type(sport: str | None, expected: str) -> None:
    assert normalize_type(sport) == expected


# ---------- pipeline ----------


def collect(files: list[InputFile], pool: ProcessPoolExecutor | None = None) -> tuple[list[Activity], list[SourceSummary], list[str]]:
    got: list[Activity] = []
    warnings: list[str] = []

    def emit(e: PipelineEvent) -> None:
        if isinstance(e, Batch):
            got.extend(e.activities)
        elif e.type == "warning":
            warnings.append(e.message)

    return got, run_import(files, emit, pool), warnings


def loose_files() -> list[InputFile]:
    return [InputFile(n, FIXTURES / n) for n in ("run.gpx", "ride.tcx", "trail-run.fit")]


def test_imports_loose_track_files() -> None:
    got, summaries, _ = collect(loose_files())
    assert [s.source for s in summaries] == ["track-files"]
    assert [(a.type, a.date) for a in got] == [
        ("Run", "2020-05-01T10:00:00"), ("Ride", "2021-07-04T08:30:00"), ("Trail Run", "2022-03-05T07:00:00"),
    ]
    assert all(a.polyline and a.start for a in got)
    assert got[1].name == "Morning Ride"  # TCX has no name: one is made up from the start time


def test_process_pool_gives_the_same_result() -> None:
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context("spawn")) as pool:
        in_pool, _, _ = collect(loose_files(), pool)
    in_thread, _, _ = collect(loose_files())
    assert in_pool == in_thread


def test_strava_archive(tmp_path: Path) -> None:
    archive = tmp_path / "export_123.zip"
    csv = (
        "Activity ID,Activity Date,Activity Name,Activity Type,Distance,Moving Time,Elevation Gain,Filename,Distance\n"
        '111,"May 1, 2020, 10:00:00 AM",Lunch run,Run,0.22,120,5,activities/111.gpx,222.4\n'
        '222,"Jun 2, 2020, 7:00:00 PM",Weights,Weight Training,0,1800,0,,0\n'
        '333,"Jul 3, 2020, 8:00:00 AM",Broken,Ride,10,600,0,activities/333.fit,10000\n'
    )
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("activities.csv", csv)
        z.writestr("activities/111.gpx", read("run.gpx"))
        z.writestr("activities/333.fit", b"not a fit file")
    got, summaries, warnings = collect([InputFile(archive.name, archive)])

    assert summaries[0].source == "strava-archive"
    assert summaries[0].with_gps == 1
    run, weights, broken = got
    assert (run.key, run.date, run.distance_m, run.url) == (
        "strava-archive:111", "2020-05-01T10:00:00", 222.4, "https://www.strava.com/activities/111",
    )
    assert run.start == (42.36, -71.06)
    assert weights.polyline == "" and weights.start is None and weights.moving_s == 1800
    assert broken.polyline == "" and broken.distance_m == 10000  # unreadable route, activity kept
    assert len(warnings) == 1 and "333.fit" in warnings[0]


def test_unsupported_files_give_a_clear_error(tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("hello")
    with pytest.raises(ValueError, match="Couldn't find any activities"):
        collect([InputFile("notes.txt", notes)])
