"""Provider contracts and network-free demonstration data."""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from citypulse.domain.models import (
    AirQualityConditions,
    AirQualityPoint,
    City,
    CityEvent,
    CitySnapshot,
    CivicAlert,
    DailyWeatherPoint,
    HourlyWeatherPoint,
    NearbyPlace,
    NewsStory,
    WeatherConditions,
)


class CityDataProvider(Protocol):
    """Contract implemented by providers that assemble a dashboard snapshot."""

    def load_snapshot(self, city: City) -> CitySnapshot:
        """Return a snapshot for the requested city."""


def distance_km(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    """Calculate great-circle distance using the haversine formula."""

    earth_radius_km = 6371.0088
    lat_a, lat_b = radians(latitude_a), radians(latitude_b)
    delta_lat = radians(latitude_b - latitude_a)
    delta_lon = radians(longitude_b - longitude_a)
    haversine = sin(delta_lat / 2) ** 2 + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    return 2 * earth_radius_km * asin(sqrt(haversine))


def city_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


class DemoDataProvider:
    """Clearly labeled local fixtures, useful without a network connection."""

    def load_snapshot(self, city: City) -> CitySnapshot:
        local_now = datetime.now(city_timezone(city.timezone))
        hourly_weather = [
            HourlyWeatherPoint(
                time=local_now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=hour),
                temperature_c=round(28.5 + 2.3 * math.sin((local_now.hour + hour - 9) / 4), 1),
                precipitation_probability_pct=float((hour * 13 + 15) % 75),
                relative_humidity_pct=max(35, min(96, 74 + (hour % 5) - 2)),
                wind_speed_kmh=round(10 + 1.4 * (hour % 6), 1),
            )
            for hour in range(24)
        ]
        daily_weather = [
            DailyWeatherPoint(
                day=(local_now + timedelta(days=offset)).date(),
                temperature_min_c=round(24 + offset * 0.2, 1),
                temperature_max_c=round(31 + math.sin(offset / 2) * 1.5, 1),
                precipitation_probability_max_pct=float((offset * 17 + 20) % 85),
                precipitation_sum_mm=float((offset * 2) % 11),
                uv_index_max=round(7.5 + (offset % 3) * 0.4, 1),
                sunrise=datetime.combine(
                    (local_now + timedelta(days=offset)).date(), time(6, 15), city_timezone(city.timezone)
                ),
                sunset=datetime.combine(
                    (local_now + timedelta(days=offset)).date(), time(18, 42), city_timezone(city.timezone)
                ),
                weather_code=(2, 3, 61, 1, 2, 80, 3)[offset],
                description=(
                    "Partly cloudy",
                    "Overcast",
                    "Slight rain",
                    "Mainly clear",
                    "Partly cloudy",
                    "Rain showers",
                    "Overcast",
                )[offset],
            )
            for offset in range(7)
        ]
        hourly_air = [
            AirQualityPoint(
                time=local_now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=hour),
                us_aqi=float(max(20, min(190, 86 + int(20 * math.sin(hour / 4))))),
                pm2_5_ug_m3=round(max(5.0, 28.4 + 5 * math.sin(hour / 5)), 1),
            )
            for hour in range(24)
        ]

        place_specs = [
            ("demo-hospital", "City General Hospital", "Health", "hospital", -0.008, 0.014),
            ("demo-park", "Harborfront Park", "Green space", "park", -0.018, -0.007),
            ("demo-station", "Central Transit Hub", "Transit", "station", 0.006, 0.011),
            ("demo-market", "Old Town Market", "Shopping", "marketplace", 0.015, -0.011),
            ("demo-library", "Civic Library", "Community", "library", -0.003, -0.018),
            ("demo-clinic", "Riverside Clinic", "Health", "clinic", 0.019, 0.017),
        ]
        places = []
        for place_id, name, category, subtype, lat_offset, lon_offset in place_specs:
            place_lat = max(-90, min(90, city.latitude + lat_offset))
            place_lon = max(-180, min(180, city.longitude + lon_offset))
            places.append(
                NearbyPlace(
                    id=place_id,
                    name=name,
                    category=category,
                    subtype=subtype,
                    latitude=place_lat,
                    longitude=place_lon,
                    distance_km=distance_km(city.latitude, city.longitude, place_lat, place_lon),
                    address="Sample location · Demo fixture",
                )
            )

        events = [
            CityEvent(
                id="community-cleanup",
                title="Waterfront clean-up walk",
                category="Community",
                description="A volunteer-led morning walk with a short shoreline clean-up.",
                venue=f"{city.name} waterfront promenade",
                neighborhood=f"{city.name} central district",
                starts_at=local_now + timedelta(hours=2),
                latitude=max(-90, min(90, city.latitude - 0.012)),
                longitude=max(-180, min(180, city.longitude + 0.018)),
            ),
            CityEvent(
                id="open-air-film",
                title="Open-air film evening",
                category="Culture",
                description="A neighborhood screening with seating available on a first-come basis.",
                venue=f"{city.name} civic park",
                neighborhood=f"{city.name} central district",
                starts_at=local_now + timedelta(hours=8),
                latitude=max(-90, min(90, city.latitude - 0.022)),
                longitude=max(-180, min(180, city.longitude + 0.004)),
            ),
        ]
        alerts = [
            CivicAlert(
                id="demo-rain-watch",
                title="Heavy rain watch",
                description="Sample notice: intense rain may affect low-lying streets.",
                severity="high",
                neighborhood=f"{city.name} central district",
                source="CityPulse demo fixture",
                published_at=local_now - timedelta(minutes=22),
                expires_at=local_now + timedelta(hours=5),
            ),
            CivicAlert(
                id="demo-maintenance",
                title="Scheduled water maintenance",
                description="Sample notice: water pressure may be reduced during maintenance.",
                severity="medium",
                neighborhood=f"{city.name} central district",
                source="CityPulse demo fixture",
                published_at=local_now - timedelta(hours=1),
                expires_at=local_now + timedelta(hours=8),
            ),
        ]
        stories = [
            NewsStory(
                title="A sample local headline for the CityPulse preview",
                url="https://example.org/citypulse-demo-story",
                source_domain="Example news · demo",
                published_at=local_now - timedelta(minutes=35),
            ),
            NewsStory(
                title="Neighborhood groups plan a public-space cleanup",
                url="https://example.org/citypulse-demo-community",
                source_domain="Example news · demo",
                published_at=local_now - timedelta(hours=2),
            ),
        ]

        return CitySnapshot(
            city=city,
            generated_at=local_now,
            weather=WeatherConditions(
                observed_at=local_now,
                temperature_c=30.2,
                feels_like_c=33.6,
                relative_humidity_pct=74,
                wind_speed_kmh=13.4,
                weather_code=2,
                description="Partly cloudy",
                hourly_forecast=hourly_weather,
                daily_forecast=daily_weather,
            ),
            air_quality=AirQualityConditions(
                observed_at=local_now,
                us_aqi=86,
                european_aqi=41,
                pm2_5_ug_m3=28.4,
                pm10_ug_m3=47.2,
                hourly_forecast=hourly_air,
            ),
            alerts=alerts,
            events=events,
            news=stories,
            places=places,
            earthquakes=[],
            sources={
                "Weather": "Demo fixture",
                "Air quality": "Demo fixture",
                "News": "Demo fixtures",
                "Nearby places": "Demo fixtures",
                "Earthquakes": "No demo events",
                "Civic alerts": "Demo fixtures",
                "Events": "Demo fixtures",
            },
        )
