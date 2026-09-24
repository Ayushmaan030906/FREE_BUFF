"""Cached adapters for public weather, news, map, and hazard APIs."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from threading import Lock
from time import monotonic, sleep
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import streamlit as st

from citypulse.data.feed_health import track_feed_refresh
from citypulse.data.events import cached_ticketmaster_events
from citypulse.data.neighborhood_alerts import build_neighborhood_alerts
from citypulse.data.news import GNewsProvider
from citypulse.data.providers import city_timezone, distance_km
from citypulse.data.sachet import cached_sachet_alerts
from citypulse.domain.models import (
    AirQualityConditions,
    AirQualityPoint,
    City,
    CitySnapshot,
    DailyWeatherPoint,
    Earthquake,
    HourlyWeatherPoint,
    NearbyPlace,
    NewsStory,
    WeatherConditions,
)

LOGGER = logging.getLogger(__name__)
USER_AGENT = "CityPulse/0.2 (local city dashboard)"
OPEN_METEO_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
GNEWS_URL = "https://gnews.io/api/v4/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
_REQUEST_LOCKS = {"gnews": Lock(), "overpass": Lock()}
_LAST_REQUEST_AT = {"gnews": 0.0, "overpass": 0.0}
_OVERPASS_FAILURE_LOCK = Lock()
_OVERPASS_FAILURES: dict[tuple[float, float, int, float], tuple[float, str]] = {}
OVERPASS_FAILURE_TTL_SECONDS = 60.0


def _get_json(
    url: str,
    timeout_seconds: float,
    *,
    params: dict[str, object] | None = None,
    form_data: dict[str, str] | None = None,
) -> dict[str, Any]:
    with httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        response = None
        for attempt in range(3):
            response = (
                client.get(url, params=params)
                if form_data is None
                else client.post(url, data=form_data)
            )
            if response.status_code not in {429, 500, 502, 503, 504} or attempt == 2:
                break
            sleep(0.5 * (2**attempt))
        assert response is not None
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("The data provider returned an unexpected response.")
    if payload.get("error"):
        raise ValueError(str(payload.get("reason", "The data provider returned an error.")))
    return payload


def _rate_limited_get_json(
    service: str,
    url: str,
    timeout_seconds: float,
    *,
    params: dict[str, object] | None = None,
    form_data: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Enforce a conservative one-request-per-second process-local API limit."""

    lock = _REQUEST_LOCKS[service]
    with lock:
        wait_seconds = 1.0 - (monotonic() - _LAST_REQUEST_AT[service])
        if wait_seconds > 0:
            sleep(wait_seconds)
        _LAST_REQUEST_AT[service] = monotonic()
        return _get_json(url, timeout_seconds, params=params, form_data=form_data)


def _parse_datetime(value: str, timezone: ZoneInfo) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone) if parsed.tzinfo is None else parsed


def _weather_description(code: int) -> str:
    descriptions = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Drizzle",
        55: "Dense drizzle",
        56: "Freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Rain",
        65: "Heavy rain",
        66: "Freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow",
        73: "Snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Rain showers",
        81: "Rain showers",
        82: "Violent rain showers",
        85: "Snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with hail",
        99: "Thunderstorm with heavy hail",
    }
    return descriptions.get(code, "Conditions unavailable")


@track_feed_refresh("Weather")
def _fetch_weather(latitude: float, longitude: float, timeout_seconds: float) -> WeatherConditions:
    payload = _get_json(
        OPEN_METEO_WEATHER_URL,
        timeout_seconds,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": (
                "temperature_2m,relative_humidity_2m,apparent_temperature,"
                "weather_code,wind_speed_10m"
            ),
            "hourly": "temperature_2m,precipitation_probability,relative_humidity_2m,wind_speed_10m",
            "daily": (
                "temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                "precipitation_sum,weather_code,sunrise,sunset,uv_index_max"
            ),
            "forecast_days": 7,
            "timezone": "auto",
        },
    )
    current = payload["current"]
    timezone = city_timezone(str(payload.get("timezone", "UTC")))
    observed_at = _parse_datetime(str(current["time"]), timezone)
    hourly_payload = payload["hourly"]
    hourly = [
        HourlyWeatherPoint(
            time=_parse_datetime(str(hour_time), timezone),
            temperature_c=float(temperature),
            precipitation_probability_pct=float(rain_probability or 0),
            relative_humidity_pct=int(humidity or 0),
            wind_speed_kmh=float(wind_speed or 0),
        )
        for hour_time, temperature, rain_probability, humidity, wind_speed in zip(
            hourly_payload["time"],
            hourly_payload["temperature_2m"],
            hourly_payload["precipitation_probability"],
            hourly_payload["relative_humidity_2m"],
            hourly_payload["wind_speed_10m"],
        )
        if temperature is not None and _parse_datetime(str(hour_time), timezone) >= observed_at
    ][:24]

    daily_payload = payload["daily"]
    daily = [
        DailyWeatherPoint(
            day=date.fromisoformat(str(day_value)),
            temperature_min_c=float(minimum),
            temperature_max_c=float(maximum),
            precipitation_probability_max_pct=float(precip_probability or 0),
            precipitation_sum_mm=float(rain_sum or 0),
            uv_index_max=float(uv_max or 0),
            sunrise=_parse_datetime(str(sunrise), timezone) if sunrise else None,
            sunset=_parse_datetime(str(sunset), timezone) if sunset else None,
            weather_code=int(code),
            description=_weather_description(int(code)),
        )
        for day_value, minimum, maximum, precip_probability, rain_sum, uv_max, sunrise, sunset, code in zip(
            daily_payload["time"],
            daily_payload["temperature_2m_min"],
            daily_payload["temperature_2m_max"],
            daily_payload["precipitation_probability_max"],
            daily_payload["precipitation_sum"],
            daily_payload["uv_index_max"],
            daily_payload["sunrise"],
            daily_payload["sunset"],
            daily_payload["weather_code"],
        )
    ]
    code = int(current["weather_code"])
    return WeatherConditions(
        observed_at=observed_at,
        temperature_c=float(current["temperature_2m"]),
        feels_like_c=float(current["apparent_temperature"]),
        relative_humidity_pct=int(current["relative_humidity_2m"]),
        wind_speed_kmh=float(current["wind_speed_10m"]),
        weather_code=code,
        description=_weather_description(code),
        hourly_forecast=hourly,
        daily_forecast=daily,
    )


@st.cache_data(ttl=600, max_entries=128, show_spinner=False)
def _cached_weather(
    latitude: float,
    longitude: float,
    timeout_seconds: float,
) -> tuple[WeatherConditions | None, str | None]:
    try:
        return _fetch_weather(latitude, longitude, timeout_seconds), None
    except Exception as error:
        LOGGER.warning("Open-Meteo weather request failed: %s", error)
        return None, "Open-Meteo weather is temporarily unavailable."


@track_feed_refresh("Air quality")
def _fetch_air_quality(latitude: float, longitude: float, timeout_seconds: float) -> AirQualityConditions:
    payload = _get_json(
        OPEN_METEO_AIR_URL,
        timeout_seconds,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": "us_aqi,european_aqi,pm2_5,pm10",
            "hourly": "us_aqi,pm2_5",
            "forecast_days": 1,
            "timezone": "auto",
        },
    )
    current = payload["current"]
    timezone = city_timezone(str(payload.get("timezone", "UTC")))
    observed_at = _parse_datetime(str(current["time"]), timezone)
    hourly_payload = payload["hourly"]
    hourly = [
        AirQualityPoint(
            time=_parse_datetime(str(hour_time), timezone),
            us_aqi=float(aqi),
            pm2_5_ug_m3=float(pm25 or 0),
        )
        for hour_time, aqi, pm25 in zip(
            hourly_payload["time"], hourly_payload["us_aqi"], hourly_payload["pm2_5"]
        )
        if aqi is not None and _parse_datetime(str(hour_time), timezone) >= observed_at
    ][:24]
    return AirQualityConditions(
        observed_at=observed_at,
        us_aqi=float(current["us_aqi"]),
        european_aqi=float(current["european_aqi"]),
        pm2_5_ug_m3=float(current["pm2_5"]),
        pm10_ug_m3=float(current["pm10"]),
        hourly_forecast=hourly,
    )


@st.cache_data(ttl=900, max_entries=128, show_spinner=False)
def _cached_air_quality(
    latitude: float,
    longitude: float,
    timeout_seconds: float,
) -> tuple[AirQualityConditions | None, str | None]:
    try:
        return _fetch_air_quality(latitude, longitude, timeout_seconds), None
    except Exception as error:
        LOGGER.warning("Open-Meteo air-quality request failed: %s", error)
        return None, "Open-Meteo air quality is temporarily unavailable."


def _fetch_news(
    city_name: str,
    country: str,
    country_code: str,
    api_key: str,
    timeout_seconds: float,
) -> list[NewsStory]:
    return GNewsProvider().search(city_name, country, country_code, api_key, timeout_seconds)


@st.cache_data(ttl=1200, max_entries=128, show_spinner=False)
def _cached_news(
    city_name: str,
    country: str,
    country_code: str,
    api_key: str | None,
    timeout_seconds: float,
) -> tuple[list[NewsStory] | None, str | None]:
    if not api_key:
        return None, "GNews is not configured. Add GNEWS_API_KEY to .env to enable live news."
    try:
        return _fetch_news(city_name, country, country_code, api_key, timeout_seconds), None
    except Exception as error:
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
        # Do not log the exception string: GNews sends its credential as a query parameter.
        LOGGER.warning(
            "GNews request failed (HTTP %s; %s).",
            status_code or "unknown",
            type(error).__name__,
        )
        if status_code == 401:
            message = "GNews rejected the configured key. Check GNEWS_API_KEY in .env."
        elif status_code == 403:
            message = "GNews denied this request or its quota is exhausted."
        else:
            message = "GNews could not refresh local headlines."
        return None, message


def _place_category(tags: dict[str, Any]) -> tuple[str, str] | None:
    amenity_labels = {
        "atm": ("Finance", "ATM"),
        "bank": ("Finance", "Bank"),
        "cafe": ("Food & drink", "Cafe"),
        "cinema": ("Culture", "Cinema"),
        "clinic": ("Health", "Clinic"),
        "college": ("Education", "College"),
        "community_centre": ("Community", "Community centre"),
        "dentist": ("Health", "Dentist"),
        "doctors": ("Health", "Doctor"),
        "fast_food": ("Food & drink", "Fast food"),
        "fire_station": ("Emergency", "Fire station"),
        "fuel": ("Transport", "Fuel station"),
        "hospital": ("Health", "Hospital"),
        "kindergarten": ("Education", "Kindergarten"),
        "library": ("Community", "Library"),
        "pharmacy": ("Health", "Pharmacy"),
        "police": ("Emergency", "Police station"),
        "post_office": ("Community", "Post office"),
        "restaurant": ("Food & drink", "Restaurant"),
        "school": ("Education", "School"),
        "toilets": ("Public services", "Public toilet"),
        "townhall": ("Civic", "Town hall"),
        "university": ("Education", "University"),
    }
    amenity = str(tags.get("amenity") or "")
    if amenity in amenity_labels:
        return amenity_labels[amenity]
    leisure = str(tags.get("leisure") or "")
    if leisure in {"park", "playground", "sports_centre"}:
        category = "Green space" if leisure == "park" else "Recreation"
        return category, leisure.replace("_", " ").title()
    shop = str(tags.get("shop") or "")
    if shop in {"mall", "supermarket", "convenience"}:
        return "Shopping", shop.title()
    if tags.get("public_transport") == "station" or tags.get("railway") == "station":
        return "Transit", "Station"
    tourism = str(tags.get("tourism") or "")
    if tourism in {"attraction", "museum", "viewpoint", "zoo"}:
        return "Culture", tourism.replace("_", " ").title()
    return None


@track_feed_refresh("Nearby places")
def _fetch_places(
    latitude: float,
    longitude: float,
    radius_km: int,
    timeout_seconds: float,
) -> list[NearbyPlace]:
    radius_m = radius_km * 1000
    query = (
        f"[out:json][timeout:20];("
        f'nwr(around:{radius_m},{latitude},{longitude})["amenity"~"restaurant|cafe|hospital|'
        f'pharmacy|police|fuel|school|atm"];'
        f'nwr(around:{radius_m},{latitude},{longitude})["leisure"="park"];'
        f'nwr(around:{radius_m},{latitude},{longitude})["shop"="supermarket"];'
        ");out center tags qt 120;"
    )
    # The Overpass query itself allows 20 seconds; allow a little extra time for transfer.
    request_timeout = max(timeout_seconds, 25.0)
    payload = _rate_limited_get_json(
        "overpass",
        OVERPASS_URL,
        request_timeout,
        form_data={"data": query},
    )
    places: list[NearbyPlace] = []
    refreshed_at = datetime.now(UTC)
    for element in payload.get("elements", []):
        if not isinstance(element, dict):
            continue
        tags = element.get("tags", {})
        if not isinstance(tags, dict):
            continue
        name = str(tags.get("name") or tags.get("name:en") or "").strip()
        classification = _place_category(tags)
        if not name or classification is None:
            continue
        coordinates = element.get("center", element)
        if not isinstance(coordinates, dict) or "lat" not in coordinates or "lon" not in coordinates:
            continue
        place_latitude = float(coordinates["lat"])
        place_longitude = float(coordinates["lon"])
        distance = distance_km(latitude, longitude, place_latitude, place_longitude)
        if distance > radius_km:
            continue
        street = " ".join(
            part
            for part in (
                str(tags.get("addr:housenumber") or ""),
                str(tags.get("addr:street") or ""),
            )
            if part
        )
        district = str(tags.get("addr:suburb") or tags.get("addr:city") or "")
        full_address = str(tags.get("addr:full") or "").strip()
        postcode = str(tags.get("addr:postcode") or "")
        address = full_address or " | ".join(part for part in (street, district, postcode) if part)
        osm_type = str(element.get("type") or "")
        osm_id = int(element["id"]) if element.get("id") is not None else None
        places.append(
            NearbyPlace(
                id=f"{osm_type or 'osm'}/{osm_id or ''}",
                name=name,
                category=classification[0],
                subtype=classification[1],
                latitude=place_latitude,
                longitude=place_longitude,
                distance_km=distance,
                address=address,
                osm_type=osm_type,
                osm_id=osm_id,
                last_updated_at=refreshed_at,
            )
        )
    places.sort(key=lambda place: place.distance_km)
    return places[:120]


@st.cache_data(ttl=3600, max_entries=96, show_spinner=False)
def _cached_places_success(
    latitude: float,
    longitude: float,
    radius_km: int,
    timeout_seconds: float,
) -> list[NearbyPlace]:
    return _fetch_places(latitude, longitude, radius_km, timeout_seconds)


def _cached_places(
    latitude: float,
    longitude: float,
    radius_km: int,
    timeout_seconds: float,
) -> tuple[list[NearbyPlace] | None, str | None]:
    failure_key = (latitude, longitude, radius_km, timeout_seconds)
    now = monotonic()
    with _OVERPASS_FAILURE_LOCK:
        cached_failure = _OVERPASS_FAILURES.get(failure_key)
        if cached_failure and cached_failure[0] > now:
            return None, cached_failure[1]
        _OVERPASS_FAILURES.pop(failure_key, None)

    try:
        places = _cached_places_success(latitude, longitude, radius_km, timeout_seconds)
    except httpx.TimeoutException:
        LOGGER.warning("OpenStreetMap nearby-place request timed out.")
        message = "Overpass timed out. Live nearby places are unavailable."
    except Exception as error:
        LOGGER.warning("OpenStreetMap nearby-place request failed: %s", error)
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code in {406, 429}:
            message = "Overpass is rate-limiting requests. Try again later."
        elif status_code:
            message = f"Overpass returned HTTP {status_code}."
        else:
            message = "Overpass could not refresh nearby places."
    else:
        with _OVERPASS_FAILURE_LOCK:
            _OVERPASS_FAILURES.pop(failure_key, None)
        return places, None

    with _OVERPASS_FAILURE_LOCK:
        if len(_OVERPASS_FAILURES) >= 128:
            _OVERPASS_FAILURES.pop(next(iter(_OVERPASS_FAILURES)))
        _OVERPASS_FAILURES[failure_key] = (monotonic() + OVERPASS_FAILURE_TTL_SECONDS, message)
    return None, message


@track_feed_refresh("Earthquakes")
def _fetch_earthquakes(
    latitude: float,
    longitude: float,
    radius_km: float,
    timeout_seconds: float,
) -> list[Earthquake]:
    now = datetime.now(UTC)
    payload = _get_json(
        USGS_URL,
        timeout_seconds,
        params={
            "format": "geojson",
            "starttime": (now - timedelta(days=1)).isoformat(),
            "endtime": now.isoformat(),
            "latitude": latitude,
            "longitude": longitude,
            "maxradiuskm": radius_km,
            "minmagnitude": 2.5,
            "eventtype": "earthquake",
            "orderby": "time",
            "limit": 200,
        },
    )
    earthquakes: list[Earthquake] = []
    for feature in payload.get("features", []):
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties", {})
        geometry = feature.get("geometry", {})
        coordinates = geometry.get("coordinates", []) if isinstance(geometry, dict) else []
        if not isinstance(properties, dict) or len(coordinates) < 3 or properties.get("mag") is None:
            continue
        source_url = str(properties.get("url") or "")
        if not source_url.startswith(("https://", "http://")):
            continue
        quake_longitude, quake_latitude, depth_km = map(float, coordinates[:3])
        distance = distance_km(latitude, longitude, quake_latitude, quake_longitude)
        timestamp_ms = int(properties.get("time") or 0)
        earthquakes.append(
            Earthquake(
                id=str(feature.get("id") or properties.get("code") or timestamp_ms),
                magnitude=float(properties["mag"]),
                place=str(properties.get("place") or "Location unavailable"),
                occurred_at=datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC),
                latitude=quake_latitude,
                longitude=quake_longitude,
                depth_km=depth_km,
                distance_km=distance,
                url=source_url,
                last_updated_at=now,
            )
        )
    earthquakes.sort(key=lambda quake: quake.occurred_at, reverse=True)
    return earthquakes[:30]


@st.cache_data(ttl=900, max_entries=128, show_spinner=False)
def _cached_earthquakes(
    latitude: float,
    longitude: float,
    radius_km: float,
    timeout_seconds: float,
) -> tuple[list[Earthquake] | None, str | None]:
    try:
        return _fetch_earthquakes(latitude, longitude, radius_km, timeout_seconds), None
    except Exception as error:
        LOGGER.warning("USGS earthquake feed request failed: %s", error)
        return None, "USGS could not refresh nearby earthquakes."


class LiveCityProvider:
    """Assemble a snapshot from live feeds without synthetic fallback values."""

    def __init__(
        self,
        timeout_seconds: float = 8.0,
        places_radius_km: int = 5,
        earthquake_radius_km: float = 300.0,
        gnews_api_key: str | None = None,
        ticketmaster_api_key: str | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._places_radius_km = places_radius_km
        self._earthquake_radius_km = earthquake_radius_km
        self._gnews_api_key = gnews_api_key
        self._ticketmaster_api_key = ticketmaster_api_key

    def load_snapshot(self, city: City) -> CitySnapshot:
        sources: dict[str, str] = {}
        warnings: list[str] = []
        updates: dict[str, Any] = {
            "weather": None,
            "air_quality": None,
            "alerts": [],
            "events": [],
            "news": [],
            "places": [],
            "earthquakes": [],
        }

        weather, warning = _cached_weather(city.latitude, city.longitude, self._timeout_seconds)
        if weather is not None:
            updates["weather"] = weather
            sources["Weather"] = "Live: Open-Meteo Forecast API"
        if warning:
            warnings.append(warning)
            sources["Weather"] = f"Unavailable: {warning}"

        air_quality, warning = _cached_air_quality(city.latitude, city.longitude, self._timeout_seconds)
        if air_quality is not None:
            updates["air_quality"] = air_quality
            sources["Air quality"] = "Live: Open-Meteo Air Quality API | CAMS ENSEMBLE"
        if warning:
            warnings.append(warning)
            sources["Air quality"] = f"Unavailable: {warning}"

        news, warning = _cached_news(
            city.name, city.country, city.country_code, self._gnews_api_key, self._timeout_seconds
        )
        if news is not None:
            updates["news"] = [story.model_copy(update={"state": city.state}) for story in news]
            sources["News"] = "Live: GNews | city and country mention search"
        if warning:
            warnings.append(warning)
            sources["News"] = f"Unavailable: {warning}"

        places, warning = _cached_places(
            city.latitude, city.longitude, self._places_radius_km, self._timeout_seconds
        )
        if places is not None:
            updates["places"] = places
            sources["Nearby places"] = "Live: OpenStreetMap via Overpass API"
        if warning:
            warnings.append(warning)
            sources["Nearby places"] = f"Unavailable: {warning}"

        earthquakes, warning = _cached_earthquakes(
            city.latitude, city.longitude, self._earthquake_radius_km, self._timeout_seconds
        )
        if earthquakes is not None:
            updates["earthquakes"] = earthquakes
            sources["Earthquakes"] = "Live: USGS | M2.5+ past-day feed"
        if warning:
            warnings.append(warning)
            sources["Earthquakes"] = f"Unavailable: {warning}"

        alerts, warning = cached_sachet_alerts(city, self._timeout_seconds)
        if alerts is not None:
            updates["alerts"] = alerts
            sources["Civic alerts"] = "Live: SACHET / NDMA India RSS + CAP"
        else:
            sources["Civic alerts"] = f"Unavailable: {warning or 'No verified SACHET alert feed is available.'}"
            if warning:
                warnings.append(warning)

        events, warning = cached_ticketmaster_events(
            city, self._ticketmaster_api_key, self._timeout_seconds
        )
        if events is not None:
            updates["events"] = events
            sources["Events"] = "Live: Ticketmaster Discovery API"
        else:
            sources["Events"] = f"Unavailable: {warning or 'No verified event feed is configured.'}"
            if warning:
                warnings.append(warning)

        sources["Weather warnings"] = (
            "Unavailable: IMD API requires registered access and an issued credential."
        )
        sources["Community"] = "Unavailable: No verified live community provider is configured."
        updates["sources"] = sources
        updates["warnings"] = warnings
        refreshed_snapshot = CitySnapshot(
            city=city,
            generated_at=datetime.now(city_timezone(city.timezone)),
            **updates,
        )
        return refreshed_snapshot.model_copy(
            update={"neighborhood_alerts": build_neighborhood_alerts(refreshed_snapshot)}
        )
