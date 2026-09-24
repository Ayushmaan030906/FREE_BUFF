"""Cached city lookup using Open-Meteo's public geocoding API."""

import logging

import httpx
import streamlit as st

from citypulse.domain.models import LocationOption

LOGGER = logging.getLogger(__name__)
_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


@st.cache_data(ttl=86_400, max_entries=256, show_spinner=False)
def search_cities(query: str, timeout_seconds: float = 8.0) -> list[LocationOption]:
    """Return up to eight city matches; empty and one-character queries are ignored."""

    search_term = query.strip()
    if len(search_term) < 2:
        return []

    try:
        response = httpx.get(
            _GEOCODING_URL,
            params={"name": search_term, "count": 8, "language": "en", "format": "json"},
            timeout=timeout_seconds,
            headers={"User-Agent": "CityPulse/0.2 (local city dashboard)"},
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        LOGGER.warning("City search failed: %s", error)
        raise RuntimeError("City search is temporarily unavailable. Please try again shortly.") from error

    results = payload.get("results", []) if isinstance(payload, dict) else []
    return [
        LocationOption(
            id=int(item["id"]),
            name=str(item["name"]),
            admin1=str(item.get("admin1") or ""),
            country=str(item.get("country") or ""),
            country_code=str(item.get("country_code") or ""),
            latitude=float(item["latitude"]),
            longitude=float(item["longitude"]),
            timezone=str(item.get("timezone") or "UTC"),
            population=int(item["population"]) if item.get("population") else None,
        )
        for item in results
        if isinstance(item, dict) and "id" in item and "latitude" in item and "longitude" in item
    ]
