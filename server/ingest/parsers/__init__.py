"""Readers for single activity files: GPX, TCX and FIT, optionally gzipped (".fit.gz")."""

from __future__ import annotations

import gzip
import re

from .fit import parse_fit
from .gpx import parse_gpx
from .tcx import parse_tcx
from .track import ParsedTrack, normalize_type

__all__ = ["ParsedTrack", "is_track_file", "normalize_type", "parse_track_file"]

_TRACK_RE = re.compile(r"\.(gpx|tcx|fit)(\.gz)?$", re.IGNORECASE)


def is_track_file(name: str) -> bool:
    return bool(_TRACK_RE.search(name))


def parse_track_file(name: str, raw: bytes) -> ParsedTrack:
    """Parse a GPX / TCX / FIT file, choosing the reader by its file name."""
    low = name.lower()
    if low.endswith(".gz"):
        raw, low = gzip.decompress(raw), low[:-3]
    if low.endswith(".gpx"):
        return parse_gpx(raw)
    if low.endswith(".tcx"):
        return parse_tcx(raw)
    if low.endswith(".fit"):
        return parse_fit(raw)
    raise ValueError(f"Not a GPX, TCX or FIT file: {name}")
