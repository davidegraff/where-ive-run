"""The HTTP API end to end: upload -> import -> stored activities -> city names."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from server.main import create_app
from server.models import LatLng
from server.settings import Settings
from server.store import Place

FIXTURES = Path(__file__).parent / "fixtures"


class FakeLookup:
    """Stands in for Nominatim and records what it was asked."""

    def __init__(self) -> None:
        self.calls: list[LatLng] = []

    def __call__(self, at: LatLng) -> Place:
        self.calls.append(at)
        return Place(city="Testville", region="TS", country="Testland")


@pytest.fixture
def lookup() -> FakeLookup:
    return FakeLookup()


@pytest.fixture
def client(tmp_path: Path, lookup: FakeLookup) -> Iterator[TestClient]:
    settings = Settings(data_dir=tmp_path, static_dir=None, max_upload_mb=1, import_processes=0)
    app = create_app(settings, lookup=lookup)
    app.state.cities.gap_s = 0  # no need to be polite to a fake
    with TestClient(app) as c:
        yield c


def upload(client: TestClient, name: str, body: bytes) -> Any:
    r = client.post("/api/uploads", content=body, headers={"X-Filename": name})
    return r


def run_import(client: TestClient, upload_ids: list[str]) -> list[dict[str, Any]]:
    r = client.post("/api/imports", json={"uploads": upload_ids})
    assert r.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in r.text.splitlines()]


def import_fixtures(client: TestClient) -> list[dict[str, Any]]:
    ids = []
    for name in ("run.gpx", "ride.tcx", "trail-run.fit"):
        r = upload(client, name, (FIXTURES / name).read_bytes())
        assert r.status_code == 201
        ids.append(r.json()["upload_id"])
    return run_import(client, ids)


def wait_for_cities(client: TestClient) -> None:
    assert client.app.state.cities.wait_idle(timeout=10)  # type: ignore[attr-defined]


def test_imports_uploaded_files_and_serves_them(client: TestClient, tmp_path: Path) -> None:
    events = import_fixtures(client)
    assert events[-1]["type"] == "done"
    summary = events[-1]["summaries"][0]
    assert (summary["source"], summary["activities"], summary["with_gps"]) == ("track-files", 3, 3)
    assert any(e["type"] == "progress" for e in events)

    activities = client.get("/api/activities").json()["activities"]
    assert [(a["type"], a["date"]) for a in activities] == [
        ("Run", "2020-05-01T10:00:00"), ("Ride", "2021-07-04T08:30:00"), ("Trail Run", "2022-03-05T07:00:00"),
    ]
    imports = client.get("/api/imports").json()
    assert [(i["file"], i["source"], i["activities"]) for i in imports] == [("3 files", "track-files", 3)]
    # uploads are deleted once imported
    assert list((tmp_path / "uploads").iterdir()) == []


def test_an_upload_can_only_be_imported_once(client: TestClient) -> None:
    r = upload(client, "run.gpx", (FIXTURES / "run.gpx").read_bytes())
    upload_id = r.json()["upload_id"]
    assert run_import(client, [upload_id])[-1]["type"] == "done"
    r = client.post("/api/imports", json={"uploads": [upload_id]})
    assert r.status_code == 404
    assert "Unknown upload" in r.json()["error"]


def test_names_cities_in_the_background(client: TestClient, lookup: FakeLookup) -> None:
    import_fixtures(client)
    wait_for_cities(client)
    assert len(lookup.calls) == 3  # Boston, London and Paris are far apart: three lookups

    update = client.get("/api/cities", params={"since": 0}).json()
    assert len(update["tags"]) == 3
    assert (update["tags"][0]["city"], update["tags"][0]["region"]) == ("Testville", "TS")
    assert update["pending"] == 0
    assert client.get("/api/cities", params={"since": update["cursor"]}).json()["tags"] == []

    body = client.get("/api/activities").json()
    assert body["city_cursor"] == update["cursor"]
    assert all(a["city"] == "Testville" for a in body["activities"])


def test_keeps_city_names_when_the_same_activity_is_imported_again(client: TestClient, lookup: FakeLookup) -> None:
    import_fixtures(client)
    wait_for_cities(client)
    r = upload(client, "again.gpx", (FIXTURES / "run.gpx").read_bytes())
    run_import(client, [r.json()["upload_id"]])
    wait_for_cities(client)
    assert len(lookup.calls) == 3
    activities = client.get("/api/activities").json()["activities"]
    assert len(activities) == 3
    assert all(a["city"] == "Testville" for a in activities)


def test_reports_unreadable_files_as_an_import_error(client: TestClient) -> None:
    r = upload(client, "notes.txt", b"hello")
    last = run_import(client, [r.json()["upload_id"]])[-1]
    assert last["type"] == "error"
    assert "Couldn't find any activities" in last["message"]


def test_rejects_uploads_over_the_size_limit(client: TestClient) -> None:
    r = upload(client, "big.gpx", bytes(1024**2 + 1))
    assert r.status_code == 413
    assert r.json() == {"error": "File is too large"}


def test_deletes_everything(client: TestClient) -> None:
    import_fixtures(client)
    assert client.delete("/api/activities").status_code == 204
    assert client.get("/api/activities").json()["activities"] == []
    assert client.get("/api/imports").json() == []


def test_errors_are_json(client: TestClient) -> None:
    r = client.get("/api/nope")
    assert (r.status_code, r.json()) == (404, {"error": "Not Found"})
    r = client.post("/api/imports", json={})
    assert r.status_code == 422
    assert "uploads" in r.json()["error"]


def test_activities_are_gzipped_when_asked(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("server.main.GZIP_MIN_BYTES", 0)
    import_fixtures(client)
    r = client.get("/api/activities", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    assert len(r.json()["activities"]) == 3  # the client decompresses it


def test_generated_typescript_is_up_to_date() -> None:
    from server.typescript import OUT, generate

    assert OUT.read_text() == generate(), "web/api-types.ts is stale: run `npm run gen:api`"
