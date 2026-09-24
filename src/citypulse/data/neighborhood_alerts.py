"""Build a small, rule-based alert stream from refreshed live city feeds."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from citypulse.domain.models import CitySnapshot, NeighborhoodAlert, Severity

_CRITICAL_NEWS_TERMS = (
    "evacuat",
    "bomb threat",
    "building collapse",
    "explosion",
    "landslide",
    "tsunami",
    "terror attack",
)
_HIGH_NEWS_TERMS = (
    "emergency",
    "warning",
    "flood",
    "cyclone",
    "wildfire",
    "fire breaks",
    "major fire",
    "gas leak",
    "train derailment",
    "outbreak",
    "road closure",
    "power outage",
    "water contamination",
    "severe storm",
)
_MEDIUM_NEWS_TERMS = (
    "alert",
    "accident",
    "crash",
    "closure",
    "disruption",
    "heatwave",
    "heat wave",
    "heavy rain",
    "traffic diversion",
)
_SEVERE_WEATHER_CODES = {
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Freezing rain",
    75: "Heavy snow",
    82: "Violent rain showers",
    86: "Heavy snow showers",
    95: "Thunderstorms",
    96: "Thunderstorms with hail",
    99: "Severe thunderstorms with hail",
}
_SEVERITY_ORDER: dict[Severity, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _feed_is_live(snapshot: CitySnapshot, feed_name: str) -> bool:
    source = snapshot.sources.get(feed_name, "").casefold()
    return source.startswith("live:")


def _news_severity(title: str, description: str) -> Severity | None:
    text = f"{title} {description}".casefold()
    if any(term in text for term in _CRITICAL_NEWS_TERMS):
        return "critical"
    if any(term in text for term in _HIGH_NEWS_TERMS):
        return "high"
    if any(term in text for term in _MEDIUM_NEWS_TERMS):
        return "medium"
    return None


def _add_news_alerts(snapshot: CitySnapshot, alerts: list[NeighborhoodAlert]) -> None:
    if not _feed_is_live(snapshot, "News"):
        return

    now = datetime.now(UTC)
    for story in snapshot.news:
        published_at = story.published_at
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=UTC)
        published_at = published_at.astimezone(UTC)
        age = now - published_at
        if age > timedelta(hours=24) or age < -timedelta(hours=1):
            continue

        severity = _news_severity(story.title, story.description)
        if severity is None:
            continue
        description = story.description or "The headline matched a CityPulse urgent-news signal."
        alerts.append(
            NeighborhoodAlert(
                id=f"news:{story.url}",
                category="news",
                title=story.title,
                description=description,
                severity=severity,
                source=f"GNews · {story.source_domain}",
                event_at=published_at,
                url=story.url,
            )
        )


def _add_weather_alerts(snapshot: CitySnapshot, alerts: list[NeighborhoodAlert]) -> None:
    if not _feed_is_live(snapshot, "Weather"):
        return

    weather = snapshot.weather
    if weather is None:
        return
    current_label = _SEVERE_WEATHER_CODES.get(weather.weather_code)
    if current_label:
        severity: Severity = "critical" if weather.weather_code == 99 else "high"
        alerts.append(
            NeighborhoodAlert(
                id=f"weather:current:{weather.observed_at.isoformat()}:{weather.weather_code}",
                category="weather",
                title=f"Severe weather observed: {current_label}",
                description=(
                    f"Open-Meteo reports {weather.description.lower()} near the selected city. "
                    "This is a forecast-feed signal, not an official local warning."
                ),
                severity=severity,
                source="Open-Meteo current weather",
                event_at=weather.observed_at,
            )
        )

    if weather.wind_speed_kmh >= 70:
        severity = "critical" if weather.wind_speed_kmh >= 100 else "high"
        alerts.append(
            NeighborhoodAlert(
                id=f"weather:wind:{weather.observed_at.isoformat()}",
                category="weather",
                title=f"Severe wind observed: {weather.wind_speed_kmh:.0f} km/h",
                description=(
                    "Current wind speed is above CityPulse's 70 km/h severe-weather "
                    "signal threshold. "
                    "Follow local authority guidance."
                ),
                severity=severity,
                source="Open-Meteo current weather",
                event_at=weather.observed_at,
            )
        )

    forecast_days = weather.daily_forecast[:2]
    for forecast in forecast_days:
        if forecast.day == weather.observed_at.date() and current_label:
            continue

        signals: list[str] = []
        forecast_label = _SEVERE_WEATHER_CODES.get(forecast.weather_code)
        if forecast_label:
            signals.append(forecast_label)
        if forecast.precipitation_sum_mm >= 50:
            signals.append("heavy rainfall")
        if forecast.temperature_max_c >= 40:
            signals.append("extreme heat")
        if not signals:
            continue

        critical = (
            forecast.weather_code == 99
            or forecast.precipitation_sum_mm >= 100
            or forecast.temperature_max_c >= 45
        )
        tzinfo = weather.observed_at.tzinfo or UTC
        event_at = datetime.combine(forecast.day, time(hour=12), tzinfo=tzinfo)
        details = [f"Forecast risk for {forecast.day:%b %d}: {', '.join(dict.fromkeys(signals))}."]
        if forecast.precipitation_sum_mm > 0:
            details.append(f"Expected precipitation: {forecast.precipitation_sum_mm:.0f} mm.")
        details.append("Forecast indicators are not official local warnings.")
        alerts.append(
            NeighborhoodAlert(
                id=f"weather:forecast:{forecast.day.isoformat()}:{forecast.weather_code}",
                category="weather",
                title=f"Severe weather forecast: {' / '.join(dict.fromkeys(signals))}",
                description=" ".join(details),
                severity="critical" if critical else "high",
                source="Open-Meteo forecast",
                event_at=event_at,
            )
        )


def _add_air_quality_alert(snapshot: CitySnapshot, alerts: list[NeighborhoodAlert]) -> None:
    if not _feed_is_live(snapshot, "Air quality"):
        return

    air = snapshot.air_quality
    if air is None:
        return
    aqi = air.us_aqi
    if aqi < 101:
        return

    if aqi >= 301:
        severity: Severity = "critical"
        band = "hazardous"
    elif aqi >= 201:
        severity = "high"
        band = "very unhealthy"
    elif aqi >= 151:
        severity = "high"
        band = "unhealthy"
    else:
        severity = "medium"
        band = "unhealthy for sensitive groups"

    alerts.append(
        NeighborhoodAlert(
            id=f"air-quality:{air.observed_at.isoformat()}",
            category="air_quality",
            title=f"Poor air quality: {band.title()} (US AQI {aqi:.0f})",
            description=(
                f"PM2.5 is {air.pm2_5_ug_m3:.1f} µg/m³ and PM10 is {air.pm10_ug_m3:.1f} µg/m³. "
                "Consider reducing prolonged outdoor exertion and follow local health guidance."
            ),
            severity=severity,
            source="Open-Meteo Air Quality · CAMS ENSEMBLE",
            event_at=air.observed_at,
        )
    )


def _add_earthquake_alerts(snapshot: CitySnapshot, alerts: list[NeighborhoodAlert]) -> None:
    if not _feed_is_live(snapshot, "Earthquakes"):
        return

    for quake in snapshot.earthquakes:
        if quake.magnitude < 4.5 and quake.distance_km > 100:
            continue
        if quake.magnitude >= 5.5:
            severity: Severity = "critical" if quake.distance_km <= 50 else "high"
        elif quake.magnitude >= 4.5:
            severity = "high" if quake.distance_km <= 100 else "medium"
        elif quake.magnitude >= 4.0 or quake.distance_km <= 25:
            severity = "medium"
        else:
            severity = "low"

        alerts.append(
            NeighborhoodAlert(
                id=f"earthquake:{quake.id}",
                category="earthquake",
                title=f"Nearby earthquake · M{quake.magnitude:.1f}",
                description=(
                    f"{quake.place}; {quake.distance_km:.0f} km from the selected city, "
                    f"{quake.depth_km:.1f} km deep."
                ),
                severity=severity,
                source="USGS · M2.5+ past-day feed",
                event_at=quake.occurred_at,
                location=quake.place,
                url=quake.url,
            )
        )


def build_neighborhood_alerts(snapshot: CitySnapshot) -> list[NeighborhoodAlert]:
    """Create alerts only from feeds marked live in the assembled snapshot."""

    alerts: list[NeighborhoodAlert] = []
    _add_news_alerts(snapshot, alerts)
    _add_weather_alerts(snapshot, alerts)
    _add_air_quality_alert(snapshot, alerts)
    _add_earthquake_alerts(snapshot, alerts)
    alerts.sort(key=lambda alert: (_SEVERITY_ORDER[alert.severity], -alert.event_at.timestamp()))
    return alerts[:20]
