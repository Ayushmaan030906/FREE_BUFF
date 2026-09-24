"""Credential-safe runtime health tracking and source registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from threading import Lock
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


@dataclass(frozen=True)
class FeedRefresh:
    """Most recent upstream refresh attempt for one feed."""

    last_attempt_at: datetime
    last_success_at: datetime | None
    error: str | None


@dataclass(frozen=True)
class SourceDefinition:
    """Public-facing source metadata; never contains credentials."""

    feed: str
    provider: str
    source_type: str
    authority: str
    categories: str
    config_key: str | None = None
    setup_message: str = ""


SOURCE_REGISTRY = (
    SourceDefinition("Weather", "Open-Meteo Forecast", "API", "Structured provider", "Current weather and forecast"),
    SourceDefinition("Air quality", "Open-Meteo Air Quality", "API", "Structured provider", "AQI, PM2.5 and PM10"),
    SourceDefinition("News", "GNews", "API", "News provider", "Local news", "GNEWS_API_KEY", "Set GNEWS_API_KEY in .env."),
    SourceDefinition("Nearby places", "OpenStreetMap Overpass", "API", "Open data", "Nearby points of interest"),
    SourceDefinition("Earthquakes", "USGS ComCat", "GeoJSON API", "Official government", "Recent earthquakes"),
    SourceDefinition("Civic alerts", "SACHET / NDMA CAP", "RSS + CAP XML", "Official government", "India-wide disaster alerts; CAP-filtered by city"),
    SourceDefinition("Weather warnings", "India Meteorological Department", "API", "Official government", "District warnings and nowcasts", "IMD_API_KEY", "Register with IMD API Management and configure the issued credential."),
    SourceDefinition("Events", "Ticketmaster Discovery", "API", "Event provider", "Public events in India", "TICKETMASTER_API_KEY", "Set TICKETMASTER_API_KEY in .env to enable event search."),
    SourceDefinition("Community", "No verified provider configured", "—", "—", "Community notices"),
)

_STALE_AFTER = {
    "Weather": 1800,
    "Air quality": 1800,
    "News": 3600,
    "Nearby places": 7200,
    "Earthquakes": 3600,
    "Civic alerts": 900,
    "Events": 7200,
}

_FEED_REFRESHES: dict[str, FeedRefresh] = {}
_FEED_REFRESHES_LOCK = Lock()


def _safe_error(error: Exception) -> str:
    """Summarize an upstream error without exposing request URLs or credentials."""

    if "timeout" in type(error).__name__.casefold():
        return "The request timed out."
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code == 401:
        return "Authentication failed; verify the provider credentials in .env."
    if status_code == 403:
        return "The provider denied the request or its quota is exhausted."
    if status_code == 429:
        return "The provider rate limit was reached."
    if status_code:
        return f"The provider returned HTTP {status_code}."
    if isinstance(error, ValueError):
        return "The provider returned data CityPulse could not process."
    return f"The request failed ({type(error).__name__})."


def track_feed_refresh(feed_name: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Record actual adapter refreshes; cache hits never update timestamps."""

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            attempted_at = datetime.now(UTC)
            try:
                result = function(*args, **kwargs)
            except Exception as error:
                with _FEED_REFRESHES_LOCK:
                    previous = _FEED_REFRESHES.get(feed_name)
                    _FEED_REFRESHES[feed_name] = FeedRefresh(
                        attempted_at,
                        previous.last_success_at if previous else None,
                        _safe_error(error),
                    )
                raise
            with _FEED_REFRESHES_LOCK:
                _FEED_REFRESHES[feed_name] = FeedRefresh(attempted_at, attempted_at, None)
            return result

        return wrapped

    return decorate


def feed_refreshes() -> dict[str, FeedRefresh]:
    """Return a snapshot of source refresh state for UI and tests."""

    with _FEED_REFRESHES_LOCK:
        return dict(_FEED_REFRESHES)


def _format_time(value: datetime | None) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC") if value else "—"


def feed_health_rows(
    *, live_enabled: bool, configured: dict[str, bool] | None = None
) -> list[dict[str, str]]:
    """Return source registry and last refresh data without any secret material."""

    configured = configured or {}
    refreshes = feed_refreshes()
    rows: list[dict[str, str]] = []
    for definition in SOURCE_REGISTRY:
        refresh = refreshes.get(definition.feed)
        is_configured = definition.config_key is None or configured.get(definition.feed, False)
        if not live_enabled:
            state, error = "Demo mode", "Live feeds are not being requested."
        elif definition.config_key and not is_configured:
            state, error = "Not configured", definition.setup_message
        elif definition.feed in {"Weather warnings", "Community"}:
            state, error = "Unavailable", definition.setup_message or "No verified live provider is configured."
        elif refresh is None:
            state, error = "Awaiting first refresh", "—"
        elif refresh.error:
            state, error = "Error", refresh.error
        elif (
            definition.feed in _STALE_AFTER
            and refresh.last_success_at is not None
            and (datetime.now(UTC) - refresh.last_success_at).total_seconds()
            > _STALE_AFTER[definition.feed]
        ):
            state, error = "Stale", "Last successful refresh is outside the source freshness window."
        else:
            state, error = "Connected", "—"
        rows.append(
            {
                "Source": definition.provider,
                "Data": definition.categories,
                "Type": definition.source_type,
                "Authority": definition.authority,
                "Configuration": (
                    "Not required"
                    if definition.config_key is None
                    else "Configured"
                    if is_configured
                    else "Credentials required"
                ),
                "State": state,
                "Last refresh": _format_time(refresh.last_attempt_at if refresh else None),
                "Last success": _format_time(refresh.last_success_at if refresh else None),
                "Error": error,
            }
        )
    return rows
