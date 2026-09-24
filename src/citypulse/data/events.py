"""Optional Ticketmaster Discovery API provider for public event listings."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from time import sleep
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import streamlit as st

from citypulse.data.feed_health import track_feed_refresh
from citypulse.domain.models import City, CityEvent

LOGGER = logging.getLogger(__name__)
TICKETMASTER_URL = "https://app.ticketmaster.com/discovery/v2/events.json"


@track_feed_refresh("Events")
def fetch_ticketmaster_events(city: City, api_key: str, timeout_seconds: float) -> list[CityEvent]:
    """Query the documented Discovery API for events in India near the selected city."""

    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        response = None
        for attempt in range(3):
            response = client.get(
                TICKETMASTER_URL,
                params={
                    "apikey": api_key,
                    "city": city.name,
                    "countryCode": city.country_code or "IN",
                    "sort": "date,asc",
                    "size": 50,
                },
                headers={"User-Agent": "CityPulse/0.2 (city event discovery)"},
            )
            if response.status_code not in {429, 500, 502, 503, 504} or attempt == 2:
                break
            sleep(0.5 * (2**attempt))
        assert response is not None
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Ticketmaster returned an unexpected response.")
    embedded = payload.get("_embedded", {})
    raw_events = embedded.get("events", []) if isinstance(embedded, dict) else []
    events: list[CityEvent] = []
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        title = str(item.get("name") or "").strip()
        url = str(item.get("url") or "")
        if not title or not url.startswith(("https://", "http://")):
            continue
        dates = item.get("dates", {})
        start = dates.get("start", {}) if isinstance(dates, dict) else {}
        date_time = str(start.get("dateTime") or "") if isinstance(start, dict) else ""
        local_date = str(start.get("localDate") or "") if isinstance(start, dict) else ""
        local_time = str(start.get("localTime") or "00:00:00") if isinstance(start, dict) else "00:00:00"
        timezone_name = str(dates.get("timezone") or city.timezone) if isinstance(dates, dict) else city.timezone
        try:
            starts_at = datetime.fromisoformat(date_time.replace("Z", "+00:00")) if date_time else datetime.fromisoformat(
                f"{local_date}T{local_time}"
            )
            if starts_at.tzinfo is None:
                try:
                    starts_at = starts_at.replace(tzinfo=ZoneInfo(timezone_name))
                except ZoneInfoNotFoundError:
                    starts_at = starts_at.replace(tzinfo=UTC)
        except ValueError:
            continue
        end = dates.get("end", {}) if isinstance(dates, dict) else {}
        end_time_text = str(end.get("dateTime") or "") if isinstance(end, dict) else ""
        ends_at = None
        if end_time_text:
            try:
                ends_at = datetime.fromisoformat(end_time_text.replace("Z", "+00:00"))
                if ends_at.tzinfo is None:
                    ends_at = starts_at.tzinfo and ends_at.replace(tzinfo=starts_at.tzinfo)
            except ValueError:
                ends_at = None
        embedded_event = item.get("_embedded", {})
        venues = embedded_event.get("venues", []) if isinstance(embedded_event, dict) else []
        venue_info = venues[0] if venues and isinstance(venues[0], dict) else {}
        venue_name = str(venue_info.get("name") or "Venue not provided")
        venue_city = venue_info.get("city", {})
        event_city = str(venue_city.get("name") or city.name) if isinstance(venue_city, dict) else city.name
        venue_state = venue_info.get("state", {})
        event_state = str(venue_state.get("name") or city.state) if isinstance(venue_state, dict) else city.state
        location = venue_info.get("location", {})
        try:
            latitude = float(location["latitude"]) if isinstance(location, dict) and location.get("latitude") else None
            longitude = float(location["longitude"]) if isinstance(location, dict) and location.get("longitude") else None
        except (TypeError, ValueError):
            latitude, longitude = None, None
        classifications = item.get("classifications", [])
        segment = classifications[0].get("segment", {}) if classifications and isinstance(classifications[0], dict) else {}
        category = str(segment.get("name") or "Event") if isinstance(segment, dict) else "Event"
        description = str(item.get("info") or item.get("pleaseNote") or "")
        events.append(
            CityEvent(
                id=f"ticketmaster:{item.get('id') or url}",
                title=title,
                category=category,
                description=description,
                venue=venue_name,
                neighborhood="",
                starts_at=starts_at,
                latitude=latitude,
                longitude=longitude,
                ends_at=ends_at,
                city=event_city,
                state=event_state,
                organizer=str(item.get("promoter", {}).get("name") or "") if isinstance(item.get("promoter"), dict) else "",
                source="Ticketmaster Discovery API",
                source_url=url,
                verified=False,
                last_updated_at=datetime.now(UTC),
            )
        )
    return events


@st.cache_data(ttl=1800, max_entries=96, show_spinner=False)
def cached_ticketmaster_events(
    city: City, api_key: str | None, timeout_seconds: float
) -> tuple[list[CityEvent] | None, str | None]:
    if not api_key:
        return None, "Ticketmaster is not configured; set TICKETMASTER_API_KEY in .env to enable event search."
    try:
        return fetch_ticketmaster_events(city, api_key, timeout_seconds), None
    except httpx.TimeoutException:
        LOGGER.warning("Ticketmaster event request timed out.")
        return None, "Ticketmaster event search timed out."
    except (httpx.HTTPError, ValueError) as error:
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        LOGGER.warning("Ticketmaster request failed (HTTP %s; %s).", status or "unknown", type(error).__name__)
        return None, "Ticketmaster event search is temporarily unavailable."
