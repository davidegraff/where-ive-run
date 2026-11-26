"""Server settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    data_dir: Path = Path("data")
    """DATA_DIR: holds app.db and uploads/. Git-ignored: it contains everyone's routes."""
    static_dir: Path | None = Path("dist")
    """STATIC_DIR: the built page (npm run build), served at /. Not needed in development."""
    max_upload_mb: int = 8192
    """MAX_UPLOAD_MB"""
    geocoder: str = "geonames"
    """GEOCODER: how cities are named. "geonames" (offline, from a downloaded town list, instant),
    "nominatim" (OpenStreetMap's web service: real town boundaries, but one place per second), or "off"."""
    nominatim_user_agent: str = "where-ive-run (self-hosted)"
    """NOMINATIM_USER_AGENT: identifies this server to Nominatim, as its usage policy requires."""
    import_processes: int | None = None
    """IMPORT_PROCESSES: processes used to parse track files (default: one per CPU core; 0 = parse in-thread)."""
    auth: str = "browser"
    """AUTH: who sees which data. "browser" (each browser has its own private space) or "local"
    (everyone shares one, for running it just for yourself). See auth.py."""

    def __post_init__(self) -> None:
        if self.geocoder not in ("geonames", "nominatim", "off"):
            raise ValueError(f'GEOCODER must be "geonames", "nominatim" or "off", not {self.geocoder!r}')

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        processes = env.get("IMPORT_PROCESSES")
        return cls(
            data_dir=Path(env.get("DATA_DIR", "data")),
            static_dir=Path(env.get("STATIC_DIR", "dist")),
            max_upload_mb=int(env.get("MAX_UPLOAD_MB", "8192")),
            geocoder=env.get("GEOCODER", "geonames").lower(),
            nominatim_user_agent=env.get("NOMINATIM_USER_AGENT", cls.nominatim_user_agent),
            import_processes=int(processes) if processes else None,
            auth=env.get("AUTH", cls.auth).lower(),
        )
