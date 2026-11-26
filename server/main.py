"""The HTTP API (routes and their types are listed in models.py), plus the built page from dist/.

Run it with `uv run python -m server` (see __main__.py), or directly with uvicorn:
    uv run uvicorn --factory server.main:create_app
"""

from __future__ import annotations

import gzip
import logging
import multiprocessing as mp
from collections.abc import AsyncIterator
from concurrent.futures import Executor, ProcessPoolExecutor
from contextlib import asynccontextmanager
from typing import Annotated
from urllib.parse import unquote

import truststore
from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from server import auth
from server.auth import current_user
from server.geocode import CityLookup, Lookup, nominatim
from server.imports import Imports
from server.models import ActivitiesResponse, ApiError, CityUpdate, ImportRecord, ImportRequest, UploadResult
from server.settings import Settings
from server.store import Store

log = logging.getLogger(__name__)

User = Annotated[str, Depends(current_user)]

GZIP_MIN_BYTES = 2048
"""Activity lists with routes are a few MB of JSON and compress about 3x; tiny ones aren't worth it."""


def create_app(settings: Settings | None = None, lookup: Lookup | None = None) -> FastAPI:
    """Build the app. Tests pass their own settings and a fake city lookup."""
    settings = settings or Settings.from_env()
    # Verify HTTPS (to Nominatim) with the operating system's certificates rather than the ones bundled
    # with Python, so it also works on networks that inspect HTTPS with their own certificate.
    truststore.inject_into_ssl()
    store = Store(settings.data_dir / "app.db")
    if lookup is None and settings.geocode:
        lookup = nominatim(settings.nominatim_user_agent)
    cities = CityLookup(store, lookup)

    # Parsing track files (FIT especially) is CPU-bound, so it runs in a pool of processes shared by
    # all imports. "spawn" starts clean interpreters, which is safe alongside the server's threads.
    pool: Executor | None = None
    if settings.import_processes != 0:
        pool = ProcessPoolExecutor(max_workers=settings.import_processes, mp_context=mp.get_context("spawn"))
    imports = Imports(store, settings.data_dir / "uploads", settings.max_upload_mb * 1024**2, pool,
                      on_imported=cities.schedule)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cities.schedule()  # pick up anything left unnamed last time
        yield
        cities.stop()
        if pool:
            pool.shutdown(wait=True, cancel_futures=True)
        store.close()

    app = FastAPI(title="Where I've Run", lifespan=lifespan, responses={400: {"model": ApiError}})
    auth.install(app, settings.auth)

    # ---------- routes ----------

    @app.get("/api/activities", response_model=ActivitiesResponse)
    def get_activities(request: Request, user: User) -> Response:
        cursor = store.city_cursor()  # read before the activities, so no city name is missed
        body = ActivitiesResponse(activities=store.activities(user), city_cursor=cursor).model_dump_json().encode()
        if len(body) > GZIP_MIN_BYTES and "gzip" in request.headers.get("accept-encoding", ""):
            return Response(gzip.compress(body, compresslevel=6), media_type="application/json",
                            headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
        return Response(body, media_type="application/json")

    @app.delete("/api/activities", status_code=204)
    def delete_activities(user: User) -> None:
        """Also stops any import of the user's that is still running."""
        imports.delete_all(user)

    @app.get("/api/imports")
    def get_imports(user: User) -> list[ImportRecord]:
        return store.imports(user)

    @app.post("/api/uploads", status_code=201, responses={413: {"model": ApiError}})
    async def upload(request: Request, user: User,
                     x_filename: Annotated[str, Header(description="URL-encoded file name")]) -> UploadResult:
        """The request body is the file itself."""
        return await imports.receive(user, unquote(x_filename), request)

    @app.post("/api/imports", response_class=StreamingResponse, responses={404: {"model": ApiError}})
    def start_import(body: ImportRequest, user: User) -> StreamingResponse:
        """Streams one ImportEvent per line (NDJSON), ending with a "done" or "error" event."""
        uploads = imports.claim(user, body.uploads)
        return StreamingResponse(imports.run(user, uploads), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.get("/api/cities")
    def get_cities(user: User, since: int = 0) -> CityUpdate:
        tags, cursor = store.tags_since(user, since)
        pending = store.count_untagged(user) if cities.active else 0
        return CityUpdate(tags=tags, cursor=cursor, pending=pending, error=cities.error)

    # ---------- errors: always {"error": "..."} (see ApiError) ----------

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, e: StarletteHTTPException) -> JSONResponse:
        return JSONResponse({"error": str(e.detail)}, status_code=e.status_code, headers=e.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, e: RequestValidationError) -> JSONResponse:
        problems = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors())
        return JSONResponse({"error": f"Invalid request ({problems})"}, status_code=422)

    # ---------- the built page ----------

    if settings.static_dir and (settings.static_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="page")

    app.state.store, app.state.cities, app.state.imports = store, cities, imports  # for tests
    return app


