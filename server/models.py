"""The data shapes the API sends and receives.

This module is the contract between the server and the page: `python -m server.typescript` turns
these models into web/api-types.ts, so the page is type-checked against exactly what the server sends.
Field docstrings become comments in the generated file.

Routes (all JSON unless noted):
    GET    /api/activities             -> ActivitiesResponse
    DELETE /api/activities             -> 204   (deletes the user's activities and import history)
    GET    /api/imports                -> list[ImportRecord]
    POST   /api/uploads                -> UploadResult  (raw file body; URL-encoded file name in X-Filename)
    POST   /api/imports                -> ImportEvent per line (NDJSON stream; body: ImportRequest)
    GET    /api/cities?since=<cursor>  -> CityUpdate
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

SourceId = Literal["strava-archive", "track-files"]

LatLng = tuple[float, float]


class Model(BaseModel):
    model_config = ConfigDict(
        use_attribute_docstrings=True,  # docstrings under fields become their descriptions
        json_schema_serialization_defaults_required=True,  # fields with defaults are still always sent
    )


class Activity(Model):
    """The one activity shape every data source is converted into."""

    key: str
    """Primary key: "{source}:{source_id}". Re-importing the same source overwrites instead of duplicating."""
    source: SourceId
    source_id: str
    """The id the source uses (Strava activity id, start time of a GPX file, ...)."""
    name: str
    date: str
    """Start time in UTC as "YYYY-MM-DDTHH:MM:SS" (no zone suffix, like the Strava export)."""
    type: str
    """Strava-style type name: "Run", "Ride", "Hike", ..."""
    distance_m: float
    moving_s: float
    elev_m: float
    start: LatLng | None
    polyline: str
    """Google encoded polyline of the thinned route ("" when there is no GPS)."""
    url: str | None = None
    """Link back to the activity on the source's website, if it has one."""
    city: str | None = None
    """Filled in after import by the background city lookup."""
    region: str | None = None


def activity_key(source: SourceId, source_id: str) -> str:
    return f"{source}:{source_id}"


class ActivitiesResponse(Model):
    activities: list[Activity]
    city_cursor: int
    """Pass as /api/cities?since= to hear about city names filled in after this response."""


class CityTag(Model):
    key: str
    city: str
    region: str


class CityUpdate(Model):
    tags: list[CityTag]
    cursor: int
    """Pass back as ?since= to get only newer tags."""
    pending: int
    """Activities still waiting for a city name (0 once the lookup has caught up or stopped)."""


class ImportRecord(Model):
    id: int
    at: str
    """ISO time of the import."""
    file: str
    """Uploaded file name (or "N files")."""
    source: SourceId
    label: str
    activities: int


class UploadResult(Model):
    upload_id: str
    name: str
    size: int


class ImportRequest(Model):
    uploads: list[str]
    """Upload ids from POST /api/uploads. Each zip is matched to a source on its own; loose files form one group."""


class SourceSummary(Model):
    file: str
    source: SourceId
    label: str
    activities: int
    with_gps: int
    warnings: int


# ---------- events streamed by POST /api/imports ----------


class ProgressEvent(Model):
    type: Literal["progress"]
    file: str
    label: str
    done: int
    total: int


class WarningEvent(Model):
    """A non-fatal problem, e.g. one unreadable file."""

    type: Literal["warning"]
    message: str


class SourceDoneEvent(Model):
    type: Literal["source-done"]
    summary: SourceSummary


class DoneEvent(Model):
    """Last line of a successful import. The page then fetches /api/activities."""

    type: Literal["done"]
    summaries: list[SourceSummary]


class ErrorEvent(Model):
    """Last line of a failed import."""

    type: Literal["error"]
    message: str


ImportEvent = Annotated[
    Union[ProgressEvent, WarningEvent, SourceDoneEvent, DoneEvent, ErrorEvent],
    Field(discriminator="type"),
]


class ApiError(Model):
    """The body of every 4xx / 5xx response."""

    error: str


# What `python -m server.typescript` exports, in this order.
TYPESCRIPT_EXPORTS: dict[str, Any] = {
    "SourceId": SourceId,
    "LatLng": LatLng,
    "Activity": Activity,
    "ActivitiesResponse": ActivitiesResponse,
    "CityTag": CityTag,
    "CityUpdate": CityUpdate,
    "ImportRecord": ImportRecord,
    "UploadResult": UploadResult,
    "ImportRequest": ImportRequest,
    "SourceSummary": SourceSummary,
    "ImportEvent": ImportEvent,
    "ApiError": ApiError,
}
