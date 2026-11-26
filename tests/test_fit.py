"""The FIT reader, on small files built by hand to reach the parts of the format real files use rarely.

(tests/fixtures/trail-run.fit, written by Garmin's own FIT SDK, is checked in test_ingest.py; the
optional real-archive comparison checks thousands more.)
"""

from __future__ import annotations

import struct

import pytest

from server.ingest.parsers.fit import FIT_EPOCH, SEMICIRCLE, parse_fit

RECORD, SESSION = 20, 18
START = 1_650_000_000  # a Unix time: 2022-04-15T05:20:00Z


def flat(points: list[tuple[float, float]]) -> list[float]:
    """pytest.approx compares flat lists only."""
    return [c for p in points for c in p]


def semicircles(deg: float) -> int:
    return round(deg / SEMICIRCLE)


def fit_file(body: bytes) -> bytes:
    """A 14-byte header, the records, and a (dummy) CRC."""
    return struct.pack("<BBHI4sH", 14, 0x20, 2132, len(body), b".FIT", 0) + body + b"\0\0"


def definition(local: int, message: int, fields: list[tuple[int, int, int]], big_endian: bool = False,
               dev_fields: list[tuple[int, int, int]] | None = None) -> bytes:
    header = 0x40 | local | (0x20 if dev_fields else 0)
    out = struct.pack(">BBBHB" if big_endian else "<BBBHB", header, 0, 1 if big_endian else 0, message, len(fields))
    out += b"".join(struct.pack("BBB", *f) for f in fields)
    if dev_fields:
        out += bytes([len(dev_fields)]) + b"".join(struct.pack("BBB", *f) for f in dev_fields)
    return out


# (field number, size, base type)
LAT, LNG, HEART_RATE = (0, 4, 0x85), (1, 4, 0x85), (3, 1, 0x02)
SESSION_FIELDS = [(2, 4, 0x86), (5, 1, 0x00), (6, 1, 0x00), (8, 4, 0x86), (9, 4, 0x86), (22, 2, 0x84)]


def session(sport: int = 1, sub_sport: int = 0, endian: str = "<") -> bytes:
    return definition(1, SESSION, SESSION_FIELDS, big_endian=endian == ">") + struct.pack(
        endian + "BIBBIIH", 0x01, START - FIT_EPOCH, sport, sub_sport, 600_000, 250_000, 42
    )


def test_reads_points_and_session_totals() -> None:
    body = definition(0, RECORD, [LAT, HEART_RATE, LNG])  # a field we skip, between the two we read
    for i in range(3):
        body += struct.pack("<BiBi", 0x00, semicircles(51.5 + i * 0.001), 150, semicircles(-0.12))
    body += session(sport=2, sub_sport=7)  # cycling / road
    t = parse_fit(fit_file(body))
    assert flat(t.points) == pytest.approx(flat([(51.5, -0.12), (51.501, -0.12), (51.502, -0.12)]), abs=1e-6)
    assert t.start is not None and t.start.timestamp() == START
    assert t.sport == "road cycling"
    assert (t.moving_s, t.distance_m, t.elev_m) == (600, 2500, 42)


def test_big_endian_compressed_timestamps_and_developer_fields() -> None:
    body = definition(0, RECORD, [LAT, LNG], big_endian=True, dev_fields=[(0, 2, 0)])
    body += struct.pack(">BiiH", 0x00, semicircles(40.0), semicircles(-74.0), 0xBEEF)
    # A compressed-timestamp header (bit 7) for local type 0 (bits 5-6), time offset 5 (bits 0-4).
    body += struct.pack(">BiiH", 0x80 | 5, semicircles(40.001), semicircles(-74.0), 0xBEEF)
    body += session(endian=">")
    t = parse_fit(fit_file(body))
    assert flat(t.points) == pytest.approx(flat([(40.0, -74.0), (40.001, -74.0)]), abs=1e-6)
    assert t.sport == "running"


def test_skips_records_without_a_position() -> None:
    body = definition(0, RECORD, [LAT, LNG])
    body += struct.pack("<Bii", 0x00, 0x7FFF_FFFF, 0x7FFF_FFFF)  # "invalid": the watch had no fix yet
    body += struct.pack("<Bii", 0x00, 0, 0)  # 0,0: also no fix
    body += struct.pack("<Bii", 0x00, semicircles(10.0), semicircles(20.0))
    assert flat(parse_fit(fit_file(body)).points) == pytest.approx(flat([(10.0, 20.0)]), abs=1e-6)


def test_redefining_a_local_type_changes_its_layout() -> None:
    body = definition(0, RECORD, [LAT, LNG]) + struct.pack("<Bii", 0, semicircles(1.0), semicircles(2.0))
    body += definition(0, RECORD, [HEART_RATE]) + struct.pack("<BB", 0, 140)  # no position fields now
    body += definition(0, RECORD, [LNG, LAT]) + struct.pack("<Bii", 0, semicircles(4.0), semicircles(3.0))
    assert flat(parse_fit(fit_file(body)).points) == pytest.approx(flat([(1.0, 2.0), (3.0, 4.0)]), abs=1e-6)


def test_chained_files() -> None:
    first = definition(0, RECORD, [LAT, LNG]) + struct.pack("<Bii", 0, semicircles(1.0), semicircles(1.0))
    second = definition(0, RECORD, [LAT, LNG]) + struct.pack("<Bii", 0, semicircles(2.0), semicircles(2.0))
    assert len(parse_fit(fit_file(first) + fit_file(second)).points) == 2


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"not a fit file", "not a FIT file"),
        (fit_file(definition(0, RECORD, [LAT, LNG]) + b"\0\1\2")[:-6], "truncated"),
        (fit_file(struct.pack("<Bii", 0x03, 0, 0)), "before its definition"),
    ],
)
def test_broken_files_raise(raw: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_fit(raw)
