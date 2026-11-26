"""AUTH=browser: each browser sees only its own activities."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import auth
from server.main import create_app
from server.settings import Settings

FIXTURES = Path(__file__).parent / "fixtures"


def make_client(tmp_path: Path, scheme: str) -> TestClient:
    settings = Settings(data_dir=tmp_path, static_dir=None, max_upload_mb=1, import_processes=0,
                        geocoder="off", auth=scheme)
    return TestClient(create_app(settings))


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with make_client(tmp_path, "browser") as c:
        yield c


def import_run(client: TestClient) -> None:
    r = client.post("/api/uploads", content=(FIXTURES / "run.gpx").read_bytes(), headers={"X-Filename": "run.gpx"})
    assert r.status_code == 201, r.text
    r = client.post("/api/imports", json={"uploads": [r.json()["upload_id"]]})
    assert '"done"' in r.text, r.text


def activity_count(client: TestClient) -> int:
    return len(client.get("/api/activities").json()["activities"])


def test_first_visit_sets_a_private_cookie(client: TestClient) -> None:
    r = client.get("/api/imports")
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{auth.COOKIE}=")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert "Secure" not in cookie  # plain HTTP here
    assert "Secure" in client.get("/api/imports", headers={"X-Forwarded-Proto": "https"}).headers["set-cookie"]


def test_browsers_only_see_their_own_data(client: TestClient) -> None:
    import_run(client)
    assert activity_count(client) == 1  # the same browser, sending its cookie back
    mine = dict(client.cookies)

    client.cookies.clear()  # another browser
    assert activity_count(client) == 0
    assert client.get("/api/imports").json() == []
    client.delete("/api/activities")  # deletes only its own (nothing)

    client.cookies.clear()  # back to the first browser
    client.cookies.update(mine)
    assert activity_count(client) == 1


def test_another_browser_cannot_claim_an_upload(client: TestClient) -> None:
    r = client.post("/api/uploads", content=(FIXTURES / "run.gpx").read_bytes(), headers={"X-Filename": "run.gpx"})
    upload_id = r.json()["upload_id"]
    client.cookies.clear()
    assert client.post("/api/imports", json={"uploads": [upload_id]}).status_code == 404


def test_a_forged_cookie_gets_a_fresh_space(client: TestClient) -> None:
    import_run(client)
    client.cookies.clear()
    client.cookies.set(auth.COOKIE, "not-a-real-token")
    assert activity_count(client) == 0


def test_local_scheme_shares_one_space(tmp_path: Path) -> None:
    with make_client(tmp_path, "local") as c:
        import_run(c)
        c.cookies.clear()
        assert activity_count(c) == 1
        assert "set-cookie" not in c.get("/api/imports").headers


def test_unknown_scheme_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="AUTH"):
        make_client(tmp_path, "nope")
