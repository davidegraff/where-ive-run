"""One file to import: a loose upload, or a file inside an uploaded zip."""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path


@dataclass
class Entry:
    path: str
    """Path inside the archive, or the file name for loose files."""
    size: int
    read: Callable[[], bytes]


def is_zip(name: str) -> bool:
    return name.lower().endswith(".zip")


def file_entry(name: str, path: Path) -> Entry:
    return Entry(path=name, size=path.stat().st_size, read=path.read_bytes)


def zip_entries(zf: zipfile.ZipFile) -> list[Entry]:
    """List a zip's files without extracting them. Each one is read only when asked for, so a
    multi-GB archive never has to fit in memory."""
    return [Entry(path=info.filename, size=info.file_size, read=partial(zf.read, info))
            for info in zf.infolist() if not info.is_dir()]
