"""Uploads and import jobs.

A file is uploaded on its own (POST /api/uploads) and written to disk. An import (POST /api/imports)
then reads one or more uploads in a background thread, saves the activities it finds as it goes, and
streams progress events back to the page. The uploads are deleted afterwards, whatever happens.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from concurrent.futures import Executor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, Request

from server.ingest.pipeline import Batch, InputFile, PipelineEvent, run_import
from server.models import DoneEvent, ErrorEvent, ImportEvent, UploadResult
from server.store import Store

log = logging.getLogger(__name__)

UPLOAD_TTL_S = 60 * 60
"""Uploads that haven't been imported within this time are deleted."""


@dataclass
class Upload:
    user: str
    name: str
    path: Path
    size: int
    expires: float


class ImportCancelled(Exception):
    """Raised inside the import thread when the page stops listening, or the user deletes their data."""


@dataclass(eq=False)
class Job:
    """A running import, so "Delete all" can stop it first."""

    user: str
    cancelled: threading.Event
    reason: str = ""


class Imports:
    def __init__(self, store: Store, upload_dir: Path, max_upload_bytes: int, pool: Executor | None,
                 on_imported: Callable[[], None]) -> None:
        self.store = store
        self.upload_dir = upload_dir
        self.max_upload_bytes = max_upload_bytes
        self.pool = pool
        self.on_imported = on_imported
        """Called after each successful import (starts the city lookup)."""
        self._uploads: dict[str, Upload] = {}
        self._jobs: set[Job] = set()
        self._lock = threading.Lock()
        self._saving = threading.Lock()
        """Held while an import saves a batch, and while deleting, so the two never overlap."""

    def delete_all(self, user: str) -> None:
        """Stop the user's running imports, then delete their activities and import history.
        Without stopping them first, an import would carry on saving into the emptied account."""
        with self._saving:
            for job in [j for j in self._jobs if j.user == user]:
                job.reason = "Stopped: all your data was deleted while this import was running."
                job.cancelled.set()
            self.store.clear(user)

    # ---------- uploads ----------

    async def receive(self, user: str, name: str, request: Request) -> UploadResult:
        """Stream the request body to disk. The name is only used for display and to recognise the file type."""
        name = name.replace("\\", "/").rsplit("/", 1)[-1][:255]
        if not name:
            raise HTTPException(400, "Missing file name (X-Filename header)")
        declared = request.headers.get("content-length")
        if declared and int(declared) > self.max_upload_bytes:
            raise HTTPException(413, "File is too large")

        self.sweep()
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        upload_id = str(uuid.uuid4())
        path = self.upload_dir / upload_id
        size = 0
        try:
            with path.open("wb") as f:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > self.max_upload_bytes:
                        raise HTTPException(413, "File is too large")
                    f.write(chunk)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        with self._lock:
            self._uploads[upload_id] = Upload(user, name, path, size, time.time() + UPLOAD_TTL_S)
        return UploadResult(upload_id=upload_id, name=name, size=size)

    def claim(self, user: str, upload_ids: list[str]) -> list[Upload]:
        """Take the uploads out of the waiting list, so each one is imported at most once."""
        if not upload_ids:
            raise HTTPException(400, "No uploads given")
        with self._lock:
            uploads = [self._uploads.get(i) for i in upload_ids]
            if any(u is None or u.user != user for u in uploads):
                raise HTTPException(404, "Unknown upload (it may have expired, or already been imported)")
            for i in upload_ids:
                del self._uploads[i]
        return [u for u in uploads if u]

    def sweep(self) -> None:
        """Delete expired uploads."""
        now = time.time()
        with self._lock:
            expired = [i for i, u in self._uploads.items() if u.expires < now]
            for i in expired:
                self._uploads.pop(i).path.unlink(missing_ok=True)

    # ---------- imports ----------

    async def run(self, user: str, uploads: list[Upload]) -> AsyncIterator[str]:
        """Run the import in a thread and yield its events as NDJSON lines, ending with done / error.
        If the page disconnects, the generator is closed and the import stops at its next event."""
        loop = asyncio.get_running_loop()
        events: asyncio.Queue[ImportEvent] = asyncio.Queue()
        job = Job(user, threading.Event())
        cancelled = job.cancelled

        def send(event: ImportEvent) -> None:
            try:
                loop.call_soon_threadsafe(events.put_nowait, event)
            except RuntimeError:  # the event loop has shut down
                pass

        def emit(event: PipelineEvent) -> None:
            if cancelled.is_set():
                raise ImportCancelled
            if isinstance(event, Batch):
                with self._saving:
                    if cancelled.is_set():
                        raise ImportCancelled
                    self.store.put_activities(user, event.activities)
            else:
                send(event)

        def work() -> None:
            final: ImportEvent
            try:
                files = [InputFile(u.name, u.path) for u in uploads]
                summaries = run_import(files, emit, self.pool)
                with self._saving:
                    if cancelled.is_set():
                        raise ImportCancelled
                    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    for s in summaries:
                        self.store.add_import(user, at, s.file, s.source, s.label, s.activities)
                self.on_imported()
                final = DoneEvent(type="done", summaries=summaries)
            except ImportCancelled:
                # Nobody is listening if the page went away; after "Delete all", the page shows why.
                final = ErrorEvent(type="error", message=job.reason or "Import cancelled")
            except ValueError as e:  # nothing recognisable in the upload: a message meant for the user
                final = ErrorEvent(type="error", message=str(e))
            except Exception:
                log.exception("Import failed")
                final = ErrorEvent(type="error", message="The import failed on the server")
            finally:
                for u in uploads:
                    u.path.unlink(missing_ok=True)
                with self._lock:
                    self._jobs.discard(job)
            send(final)

        with self._lock:
            self._jobs.add(job)
        threading.Thread(target=work, name=f"import-{user}", daemon=True).start()
        try:
            while True:
                event = await events.get()
                yield event.model_dump_json() + "\n"
                if event.type in ("done", "error"):
                    return
        finally:
            cancelled.set()
