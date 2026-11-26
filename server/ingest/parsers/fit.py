"""FIT: Garmin's binary format, also used by Wahoo, Coros, Suunto and the Strava app.

This is a small reader of our own rather than a general FIT library: it decodes only the handful of
fields the importer uses and skips everything else by length, unpacking each record with a single
struct call. On a real Strava archive that's about 1.5 ms per file against 80 ms for fitdecode, which
decodes every field into Python objects, with identical results. (A Strava archive is mostly FIT
files, so this is most of an import's time.)

The format, briefly (the full spec is in Garmin's FIT SDK):

    file    = header, records..., 2-byte CRC        (files may be chained one after another)
    header  = size (12 or 14), protocol, profile, data size (uint32), ".FIT" [, CRC]
    record  = 1-byte record header, then a definition message or a data message

A definition message says what a "local message type" (0-15) looks like from now on: which global
message it is (record, session, ...), the byte order, and each field's number, size and base type.
A data message is just the field values laid out as its definition says, so its size is known and
everything we don't need can be skipped without decoding it.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from server.models import LatLng

from .fit_profile import SPORTS, SUB_SPORTS
from .track import ParsedTrack

SEMICIRCLE = 180 / 2**31
"""FIT stores coordinates as "semicircles": 2^31 of them make 180 degrees."""

FIT_EPOCH = 631_065_600
"""FIT times count seconds from 1989-12-31T00:00:00Z; this is that moment as a Unix time."""

# Global message numbers, and the fields read from each: {message: {field number: name}}.
FILE_ID, SPORT, SESSION, RECORD, ACTIVITY = 0, 12, 18, 20, 34
WANTED: dict[int, dict[int, str]] = {
    FILE_ID: {4: "time_created"},
    SPORT: {0: "sport", 1: "sub_sport", 3: "name"},
    SESSION: {2: "start_time", 5: "sport", 6: "sub_sport", 8: "total_timer_time", 9: "total_distance", 22: "total_ascent"},
    RECORD: {0: "position_lat", 1: "position_long"},
    ACTIVITY: {253: "timestamp"},
}

# Base type number -> (struct format, the value that means "no data")
BASE_TYPES: dict[int, tuple[str, int | None]] = {
    0x00: ("B", 0xFF),  # enum
    0x01: ("b", 0x7F),  # sint8
    0x02: ("B", 0xFF),  # uint8
    0x83: ("h", 0x7FFF),  # sint16
    0x84: ("H", 0xFFFF),  # uint16
    0x85: ("i", 0x7FFF_FFFF),  # sint32
    0x86: ("I", 0xFFFF_FFFF),  # uint32
    0x07: ("s", None),  # string (NUL-terminated, in a fixed-size field)
    0x88: ("f", None),  # float32
    0x89: ("d", None),  # float64
    0x0A: ("B", 0),  # uint8z
    0x8B: ("H", 0),  # uint16z
    0x8C: ("I", 0),  # uint32z
    0x0D: ("B", 0xFF),  # byte
    0x8E: ("q", 0x7FFF_FFFF_FFFF_FFFF),  # sint64
    0x8F: ("Q", 0xFFFF_FFFF_FFFF_FFFF),  # uint64
    0x90: ("Q", 0),  # uint64z
}

INVALID_SINT32 = 0x7FFF_FFFF


@dataclass
class Definition:
    message: int
    """Global message number."""
    size: int
    """Bytes in each data message, including fields we skip."""
    unpack: struct.Struct | None
    """Unpacks just the wanted fields (the others are padding in the format); None if there are none."""
    names: list[str]
    invalid: list[int | None]
    lat_lng: tuple[int, int] | None = None
    """For GPS records: where latitude and longitude are in the unpacked values (in either order)."""


def parse_fit(raw: bytes) -> ParsedTrack:
    points: list[LatLng] = []
    messages: dict[int, list[dict[str, Any]]] = {}

    pos = 0
    while True:
        pos = _read_file(raw, pos, points, messages)
        # Another FIT file may follow (chained files); anything else after the CRC is ignored.
        if len(raw) - pos < 12 or raw[pos + 8 : pos + 12] != b".FIT":
            break

    sessions = messages.get(SESSION, [])
    session = sessions[0] if sessions else {}
    first_sport = messages.get(SPORT, [{}])[0]

    def first_time(*candidates: tuple[int, str]) -> datetime | None:
        for message, field in candidates:
            for m in messages.get(message, [])[:1]:
                if (t := _fit_time(m.get(field))) is not None:
                    return t
        return None

    def total(field: str, scale: float = 1) -> float | None:
        return sum(s[field] for s in sessions if field in s) / scale or None

    sport = SPORTS.get(session.get("sport", first_sport.get("sport", -1)))
    sub_sport = SUB_SPORTS.get(session.get("sub_sport", -1))
    if sport and sub_sport and sub_sport not in ("generic", "street"):
        sport = f"{sub_sport} {sport}"  # e.g. "trail running", so it maps to "Trail Run"
    name = first_sport.get("name")
    return ParsedTrack(
        points=points,
        start=first_time((SESSION, "start_time"), (ACTIVITY, "timestamp"), (FILE_ID, "time_created")),
        sport=sport,
        name=name if isinstance(name, str) else None,
        distance_m=total("total_distance", 100),  # stored in cm
        moving_s=total("total_timer_time", 1000),  # stored in ms
        elev_m=total("total_ascent"),
    )


def _read_file(raw: bytes, start: int, points: list[LatLng], messages: dict[int, list[dict[str, Any]]]) -> int:
    """Read one FIT file starting at `start`; return where it ends."""
    header_size = raw[start] if start < len(raw) else 0
    if header_size not in (12, 14) or raw[start + 8 : start + 12] != b".FIT":
        raise ValueError("not a FIT file")
    data_size = int.from_bytes(raw[start + 4 : start + 8], "little")
    pos = start + header_size
    end = pos + data_size
    if end > len(raw):
        raise ValueError("FIT file is truncated")

    definitions: dict[int, Definition] = {}
    while pos < end:
        header = raw[pos]
        pos += 1
        if header & 0x80:  # compressed-timestamp header: a data message; local type in bits 5-6
            local = (header >> 5) & 0x03
        elif header & 0x40:  # definition message
            pos = _read_definition(raw, pos, header, definitions)
            continue
        else:  # normal data message
            local = header & 0x0F

        d = definitions.get(local)
        if d is None:
            raise ValueError("FIT data message before its definition")
        if pos + d.size > end:
            raise ValueError("FIT file is truncated")
        if d.unpack is not None:
            if d.lat_lng is not None:
                # The hot path: GPS records are most of the file.
                values = d.unpack.unpack_from(raw, pos)
                lat, lng = values[d.lat_lng[0]], values[d.lat_lng[1]]
                if lat != INVALID_SINT32 and lng != INVALID_SINT32 and (lat or lng):
                    points.append((lat * SEMICIRCLE, lng * SEMICIRCLE))
            elif d.message != RECORD:
                values = d.unpack.unpack_from(raw, pos)
                fields = {n: _clean(v) for n, v, bad in zip(d.names, values, d.invalid) if v != bad}
                messages.setdefault(d.message, []).append({k: v for k, v in fields.items() if v is not None})
        pos += d.size
    return end + 2  # skip the file's CRC


def _read_definition(raw: bytes, pos: int, header: int, definitions: dict[int, Definition]) -> int:
    big_endian = raw[pos + 1] == 1  # raw[pos] is reserved
    message = int.from_bytes(raw[pos + 2 : pos + 4], "big" if big_endian else "little")
    field_count = raw[pos + 4]
    pos += 5

    wanted = WANTED.get(message, {})
    fmt = ">" if big_endian else "<"
    names: list[str] = []
    invalid: list[int | None] = []
    size = 0
    for _ in range(field_count):
        number, field_size, base_type = raw[pos], raw[pos + 1], raw[pos + 2]
        pos += 3
        size += field_size
        name = wanted.get(number)
        kind = BASE_TYPES.get(base_type)
        if name and kind and kind[0] == "s":
            fmt += f"{field_size}s"
        elif name and kind and struct.calcsize(kind[0]) == field_size:
            fmt += kind[0]
        else:  # a field we don't read, or an array: skip its bytes
            fmt += f"{field_size}x"
            continue
        names.append(name)
        invalid.append(kind[1])

    if header & 0x20:  # developer data fields follow; we only need their sizes
        dev_count = raw[pos]
        pos += 1
        for _ in range(dev_count):
            size += raw[pos + 1]
            pos += 3

    lat_lng = None
    if message == RECORD and "position_lat" in names and "position_long" in names:
        lat_lng = (names.index("position_lat"), names.index("position_long"))
    local = header & 0x0F
    definitions[local] = Definition(message, size, struct.Struct(fmt) if names else None, names, invalid, lat_lng)
    return pos


def _clean(value: Any) -> Any:
    """Strings come as NUL-padded bytes."""
    if isinstance(value, bytes):
        return value.split(b"\0", 1)[0].decode("utf-8", "replace") or None
    return value


def _fit_time(value: Any) -> datetime | None:
    # Values below 0x10000000 are relative to the device's power-on, not real dates.
    if isinstance(value, int) and value >= 0x1000_0000:
        return datetime.fromtimestamp(value + FIT_EPOCH, timezone.utc)
    return None
