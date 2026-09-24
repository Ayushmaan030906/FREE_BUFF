"""SACHET / NDMA all-India RSS and linked CAP feed adapter."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import monotonic, sleep
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import httpx
import streamlit as st

from citypulse.data.feed_health import track_feed_refresh
from citypulse.data.providers import distance_km
from citypulse.domain.models import City, CivicAlert, Severity

LOGGER = logging.getLogger(__name__)
SACHET_RSS_URL = "https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml"
SACHET_CAP_URL = "https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile"
_DOCUMENT_CACHE_LOCK = Lock()
_DOCUMENT_CACHE: dict[str, tuple[str | None, bytes, float]] = {}
_RSS_CACHE_SECONDS = 180
_CAP_CACHE_SECONDS = 900
_SEVERITY: dict[str, Severity] = {
    "minor": "low",
    "moderate": "medium",
    "severe": "high",
    "extreme": "critical",
}
_STATE_FEED_SOURCES: dict[str, tuple[str, ...]] = {
    "andhra pradesh": ("andhra pradesh sdma", "imd visakhapatnam"),
    "assam": ("imd guwahati",),
    "chhattisgarh": ("imd raipur",),
    "goa": ("imd goa", "imd mumbai"),
    "karnataka": ("imd bengaluru", "imd bangalore"),
    "kerala": ("imd thiruvananthapuram", "imd trivandrum"),
    "madhya pradesh": ("imd bhopal",),
    "maharashtra": ("imd mumbai", "imd nagpur"),
    "odisha": ("imd bhubaneswar",),
    "sikkim": ("imd gangtok",),
    "telangana": ("imd hyderabad",),
    "tripura": ("imd agartala",),
    "uttarakhand": ("imd dehradun",),
    "west bengal": ("imd kolkata",),
}


@dataclass(frozen=True)
class _RssItem:
    identifier: str
    title: str
    description: str
    author: str
    source_url: str


def _fetch_document(
    cache_key: str,
    url: str,
    timeout_seconds: float,
    *,
    params: dict[str, str] | None = None,
    cache_seconds: int,
) -> bytes:
    """Fetch a SACHET document with an in-memory TTL and conditional ETag request."""

    now = monotonic()
    with _DOCUMENT_CACHE_LOCK:
        cached = _DOCUMENT_CACHE.get(cache_key)
    if cached and now - cached[2] < cache_seconds:
        return cached[1]

    headers = {
        "User-Agent": "CityPulse/0.2 (civic information dashboard)",
        "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.1",
    }
    if cached and cached[0]:
        headers["If-None-Match"] = cached[0] or ""
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
        response = None
        for attempt in range(3):
            response = client.get(url, params=params)
            if response.status_code not in {429, 500, 502, 503, 504} or attempt == 2:
                break
            sleep(0.5 * (2**attempt))
        assert response is not None

    if response.status_code == 304 and cached:
        document = cached[1]
        etag = cached[0]
    else:
        response.raise_for_status()
        document = response.content
        etag = response.headers.get("ETag")
    with _DOCUMENT_CACHE_LOCK:
        _DOCUMENT_CACHE[cache_key] = (etag, document, monotonic())
    return document


@st.cache_data(ttl=_RSS_CACHE_SECONDS, max_entries=1, show_spinner=False)
def _cached_rss_document(timeout_seconds: float) -> bytes:
    return _fetch_document(
        "rss:india",
        SACHET_RSS_URL,
        timeout_seconds,
        cache_seconds=_RSS_CACHE_SECONDS,
    )


@st.cache_data(ttl=_CAP_CACHE_SECONDS, max_entries=256, show_spinner=False)
def _cached_cap_document(identifier: str, timeout_seconds: float) -> bytes:
    return _fetch_document(
        f"cap:{identifier}",
        SACHET_CAP_URL,
        timeout_seconds,
        params={"identifier": identifier},
        cache_seconds=_CAP_CACHE_SECONDS,
    )


def _inside_polygon(latitude: float, longitude: float, polygon: list[tuple[float, float]]) -> bool:
    inside = False
    previous = len(polygon) - 1
    for index, (lat_i, lon_i) in enumerate(polygon):
        lat_prev, lon_prev = polygon[previous]
        crosses = (lon_i > longitude) != (lon_prev > longitude)
        if crosses:
            crossing_lat = (lat_prev - lat_i) * (longitude - lon_i) / (lon_prev - lon_i) + lat_i
            if latitude < crossing_lat:
                inside = not inside
        previous = index
    return inside


def _area_matches(
    area: ElementTree.Element,
    city: City,
    namespace: dict[str, str],
    location_context: str = "",
) -> bool:
    for circle in area.findall("cap:circle", namespace):
        parts = (circle.text or "").split()
        if not parts:
            continue
        try:
            latitude, longitude = (float(part) for part in parts[0].split(",", 1))
            radius_km = float(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            continue
        if distance_km(city.latitude, city.longitude, latitude, longitude) <= radius_km:
            return True
    for polygon_element in area.findall("cap:polygon", namespace):
        points: list[tuple[float, float]] = []
        for pair in (polygon_element.text or "").split():
            try:
                latitude, longitude = pair.split(",", 1)
                points.append((float(latitude), float(longitude)))
            except ValueError:
                continue
        if len(points) >= 3 and _inside_polygon(city.latitude, city.longitude, points):
            return True
    city_name = city.name.strip()
    if city_name:
        area_text = " ".join(
            [element.text or "" for element in area.findall("cap:areaDesc", namespace)]
            + [location_context]
        )
        if re.search(rf"(?<!\w){re.escape(city_name)}(?!\w)", area_text, re.IGNORECASE):
            return True
    return False


def _area_marker(
    area: ElementTree.Element, city: City, namespace: dict[str, str]
) -> tuple[float, float] | None:
    """Return a source-derived marker center, not an assumed incident location."""

    for circle in area.findall("cap:circle", namespace):
        parts = (circle.text or "").split()
        if not parts:
            continue
        try:
            latitude_text, longitude_text = parts[0].split(",", 1)
            latitude, longitude = float(latitude_text), float(longitude_text)
            radius_km = float(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            continue
        if distance_km(city.latitude, city.longitude, latitude, longitude) <= radius_km:
            return latitude, longitude
    for polygon_element in area.findall("cap:polygon", namespace):
        points: list[tuple[float, float]] = []
        for pair in (polygon_element.text or "").split():
            try:
                latitude_text, longitude_text = pair.split(",", 1)
                points.append((float(latitude_text), float(longitude_text)))
            except ValueError:
                continue
        if len(points) >= 3 and _inside_polygon(city.latitude, city.longitude, points):
            return (
                sum(point[0] for point in points) / len(points),
                sum(point[1] for point in points) / len(points),
            )
    return None


def _info_text(info: ElementTree.Element, name: str, namespace: dict[str, str]) -> str:
    element = info.find(f"cap:{name}", namespace)
    return (element.text or "").strip() if element is not None else ""


def _parse_cap(
    xml_bytes: bytes, city: City, source_url: str | None = None
) -> list[CivicAlert]:
    root = ElementTree.fromstring(xml_bytes)
    namespace_uri = root.tag.split("}", 1)[0].lstrip("{") if "}" in root.tag else ""
    namespace = {"cap": namespace_uri} if namespace_uri else {"cap": ""}
    now = datetime.now(UTC)
    alerts: list[CivicAlert] = []
    cap_tag = f"{{{namespace_uri}}}alert" if namespace_uri else "alert"
    alert_nodes = [root] if root.tag == cap_tag else root.findall(".//cap:alert", namespace)
    for alert in alert_nodes:
        if _info_text(alert, "status", namespace).casefold() != "actual":
            continue
        msg_type = _info_text(alert, "msgType", namespace).casefold()
        if msg_type == "cancel":
            continue
        sent_text = _info_text(alert, "sent", namespace)
        if not sent_text:
            continue
        try:
            sent = datetime.fromisoformat(sent_text.replace("Z", "+00:00"))
        except ValueError:
            continue
        sent = sent.replace(tzinfo=UTC) if sent.tzinfo is None else sent.astimezone(UTC)
        infos = alert.findall("cap:info", namespace)
        if not infos:
            continue
        info = next(
            (
                candidate
                for candidate in infos
                if candidate.attrib.get("{http://www.w3.org/XML/1998/namespace}lang", "").startswith("en")
            ),
            infos[0],
        )
        severity_text = _info_text(info, "severity", namespace)
        normalized_severity = _SEVERITY.get(severity_text.casefold())
        if normalized_severity is None:
            continue
        expires_text = _info_text(info, "expires", namespace)
        expires = None
        if expires_text:
            try:
                expires = datetime.fromisoformat(expires_text.replace("Z", "+00:00"))
            except ValueError:
                expires = None
            else:
                expires = expires.replace(tzinfo=UTC) if expires.tzinfo is None else expires.astimezone(UTC)
        if expires is not None and expires <= now:
            continue
        areas = info.findall("cap:area", namespace)
        location_context = " ".join(
            filter(None, (_info_text(info, "headline", namespace), _info_text(info, "event", namespace)))
        )
        matching_areas = [
            area for area in areas if _area_matches(area, city, namespace, location_context)
        ]
        if not matching_areas:
            continue
        identifier = _info_text(alert, "identifier", namespace) or _info_text(alert, "sender", namespace)
        if not identifier:
            continue
        headline = _info_text(info, "headline", namespace) or _info_text(info, "event", namespace)
        if not headline:
            continue
        sender = _info_text(alert, "senderName", namespace) or _info_text(alert, "sender", namespace)
        web_url = _info_text(info, "web", namespace)
        official_url = web_url if web_url.startswith(("https://", "http://")) else source_url
        areas_label = ", ".join(
            filter(None, (_info_text(area, "areaDesc", namespace) for area in areas))
        )
        marker = _area_marker(matching_areas[0], city, namespace)
        alerts.append(
            CivicAlert(
                id=identifier,
                title=headline,
                description=_info_text(info, "description", namespace)
                or _info_text(info, "instruction", namespace),
                severity=normalized_severity,
                normalized_severity=normalized_severity,
                original_severity=severity_text,
                status=msg_type.title() or "Actual",
                neighborhood=areas_label,
                source=f"SACHET / NDMA{f' | {sender}' if sender else ''}",
                source_url=official_url,
                official=True,
                verified=True,
                city=city.name,
                state=city.state,
                published_at=sent,
                expires_at=expires,
                last_updated_at=now,
                latitude=marker[0] if marker else None,
                longitude=marker[1] if marker else None,
            )
        )
    latest_by_id: dict[str, CivicAlert] = {}
    for item in alerts:
        current = latest_by_id.get(item.id)
        if current is None or item.published_at > current.published_at:
            latest_by_id[item.id] = item
    priority = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(
        latest_by_id.values(),
        key=lambda item: (priority[item.severity], -item.published_at.timestamp()),
    )


def _rss_items(xml_bytes: bytes) -> list[_RssItem]:
    root = ElementTree.fromstring(xml_bytes)
    items: list[_RssItem] = []
    for item in root.findall(".//item"):
        link = (item.findtext("link") or "").strip()
        parsed = urlparse(link)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "sachet.ndma.gov.in"
            or parsed.path.rstrip("/") != "/cap_public_website/FetchXMLFile"
        ):
            continue
        identifier = (parse_qs(parsed.query).get("identifier") or [""])[0].strip()
        if not identifier:
            identifier = (item.findtext("guid") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", identifier):
            continue
        items.append(
            _RssItem(
                identifier=identifier,
                title=(item.findtext("title") or "").strip(),
                description=(item.findtext("description") or "").strip(),
                author=(item.findtext("author") or "").strip(),
                source_url=link,
            )
        )
    return items


def _rss_item_may_apply(item: _RssItem, city: City) -> bool:
    """Use RSS locality text to limit CAP lookups, then let CAP geometry decide."""

    text = " ".join((item.title, item.description, item.author)).casefold()
    places = (city.name, city.state)
    if any(place.strip() and place.casefold() in text for place in places):
        return True
    author = item.author.casefold()
    return any(alias in author for alias in _STATE_FEED_SOURCES.get(city.state.casefold(), ()))


@track_feed_refresh("Civic alerts")
def fetch_sachet_alerts(city: City, timeout_seconds: float) -> list[CivicAlert]:
    """Read India's SACHET RSS and inspect linked CAP records relevant to the city."""

    items = _rss_items(_cached_rss_document(timeout_seconds))
    candidates = [item for item in items if _rss_item_may_apply(item, city)]
    alerts: list[CivicAlert] = []
    for item in candidates:
        try:
            cap_document = _cached_cap_document(item.identifier, timeout_seconds)
        except httpx.TimeoutException:
            LOGGER.warning("SACHET CAP record timed out.")
            raise
        alerts.extend(_parse_cap(cap_document, city, item.source_url))
    latest_by_id: dict[str, CivicAlert] = {}
    for alert in alerts:
        existing = latest_by_id.get(alert.id)
        if existing is None or alert.published_at > existing.published_at:
            latest_by_id[alert.id] = alert
    priority = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(
        latest_by_id.values(),
        key=lambda alert: (priority[alert.severity], -alert.published_at.timestamp()),
    )


@st.cache_data(ttl=180, max_entries=48, show_spinner=False)
def cached_sachet_alerts(
    city: City, timeout_seconds: float
) -> tuple[list[CivicAlert] | None, str | None]:
    try:
        return fetch_sachet_alerts(city, timeout_seconds), None
    except httpx.TimeoutException:
        LOGGER.warning("SACHET RSS/CAP refresh timed out.")
        return None, "SACHET / NDMA alert refresh timed out."
    except (httpx.HTTPError, ElementTree.ParseError, ValueError) as error:
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        LOGGER.warning("SACHET RSS/CAP request failed (HTTP %s; %s).", status or "unknown", type(error).__name__)
        return None, "SACHET / NDMA alert feed is temporarily unavailable."
