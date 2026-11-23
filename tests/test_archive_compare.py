"""Checks the importer against the old command-line importer's output on a real Strava archive.

Skipped unless both are available:
    STRAVA_ARCHIVE=~/Downloads/export_123.zip LEGACY_JSON=data/runs.json uv run pytest tests/test_archive_compare.py -s
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from server.ingest.pipeline import Batch, InputFile, PipelineEvent, run_import
from server.models import Activity

ARCHIVE = Path(os.path.expanduser(os.environ.get("STRAVA_ARCHIVE", "")))
LEGACY = Path(os.environ.get("LEGACY_JSON", ""))


@pytest.mark.skipif(not (ARCHIVE.is_file() and LEGACY.is_file()), reason="set STRAVA_ARCHIVE and LEGACY_JSON")
def test_matches_the_old_importer() -> None:
    got: list[Activity] = []
    warnings: list[str] = []

    def emit(e: PipelineEvent) -> None:
        if isinstance(e, Batch):
            got.extend(e.activities)
        elif e.type == "warning":
            warnings.append(e.message)

    t0 = time.monotonic()
    with ProcessPoolExecutor(mp_context=mp.get_context("spawn")) as pool:
        summaries = run_import([InputFile(ARCHIVE.name, ARCHIVE)], emit, pool)
    print(f"\nimported {len(got)} activities in {time.monotonic() - t0:.1f} s", summaries, warnings[:5])

    want = json.loads(LEGACY.read_text())
    assert len(got) == len(want)
    by_id = {a.source_id: a for a in got}
    for w in want:
        g = by_id[str(w["id"])]
        assert (g.date, g.type, g.name, g.polyline) == (w["date"], w["type"], w["name"], w["polyline"]), w["id"]
        assert g.distance_m == pytest.approx(w["distance_m"], abs=1e-3)
        assert g.moving_s == pytest.approx(w["moving_s"], abs=1e-3)
        assert g.elev_m == pytest.approx(w["elev_m"], abs=1e-3)
        assert (list(g.start) if g.start else None) == w["start"]
