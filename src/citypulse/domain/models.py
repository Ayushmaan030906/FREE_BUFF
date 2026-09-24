"""Validated domain models for live and demo CityPulse data."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["low", "medium", "high", "critical"]


class City(BaseModel):
    """A named place and its coordinates."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=100)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = "UTC"
    country: str = ""
    country_code: str = ""
    state: str = ""


class LocationOption(BaseModel):
    """A geocoding result suitable for the city picker."""

    id: int
    name: str
    admin1: str = ""
    country: str = ""
    country_code: str = ""
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = "UTC"
    population: int | None = None

    @property
    def label(self) -> str:
        parts = [self.name]
        if self.admin1 and self.admin1.casefold() != self.name.casefold():
            parts.append(self.admin1)
        if self.country:
            parts.append(self.country)
        return ", ".join(parts)


class HourlyWeatherPoint(BaseModel):
    """One forecast point for temperature, rain, humidity, and wind."""

    time: datetime
    temperature_c: float
    precipitation_probability_pct: float = Field(ge=0, le=100)
    relative_humidity_pct: int = Field(ge=0, le=100)
    wind_speed_kmh: float = Field(ge=0)


class DailyWeatherPoint(BaseModel):
    """Daily forecast summary."""

    day: date
    temperature_min_c: float
    temperature_max_c: float
    precipitation_probability_max_pct: float = Field(ge=0, le=100)
    precipitation_sum_mm: float = Field(ge=0)
    uv_index_max: float = Field(ge=0)
    sunrise: datetime | None = None
    sunset: datetime | None = None
    weather_code: int
    description: str


class WeatherConditions(BaseModel):
    """Current weather plus hourly and daily outlooks."""

    observed_at: datetime
    temperature_c: float
    feels_like_c: float
    relative_humidity_pct: int = Field(ge=0, le=100)
    wind_speed_kmh: float = Field(ge=0)
    weather_code: int
    description: str
    hourly_forecast: list[HourlyWeatherPoint]
    daily_forecast: list[DailyWeatherPoint]


class AirQualityPoint(BaseModel):
    """One local-hour air-quality forecast point."""

    time: datetime
    us_aqi: float = Field(ge=0)
    pm2_5_ug_m3: float = Field(ge=0)


class AirQualityConditions(BaseModel):
    """Current air quality and a short AQI outlook."""

    observed_at: datetime
    us_aqi: float = Field(ge=0)
    european_aqi: float = Field(ge=0)
    pm2_5_ug_m3: float = Field(ge=0)
    pm10_ug_m3: float = Field(ge=0)
    hourly_forecast: list[AirQualityPoint]


class CivicAlert(BaseModel):
    """A city service or neighborhood notice."""

    id: str
    title: str
    description: str
    severity: Severity
    neighborhood: str = ""
    source: str
    published_at: datetime
    expires_at: datetime | None = None
    original_severity: str = ""
    normalized_severity: Severity | None = None
    status: str = "Actual"
    city: str = ""
    district: str = ""
    state: str = ""
    source_url: str | None = None
    official: bool = False
    verified: bool = False
    last_updated_at: datetime | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class NeighborhoodAlert(BaseModel):
    """A rule-based alert derived from a live CityPulse feed."""

    id: str
    category: Literal["news", "weather", "air_quality", "earthquake"]
    title: str
    description: str
    severity: Severity
    source: str
    event_at: datetime
    location: str = ""
    url: str | None = None


class CityEvent(BaseModel):
    """An event returned by a public event source or clearly labeled demo fixture."""

    id: str
    title: str
    category: str
    description: str
    venue: str
    neighborhood: str
    starts_at: datetime
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    is_free: bool | None = None
    ends_at: datetime | None = None
    city: str = ""
    state: str = ""
    organizer: str = ""
    source: str = ""
    source_url: str | None = None
    verified: bool = False
    last_updated_at: datetime | None = None


class NewsStory(BaseModel):
    """A recent article returned by the live news index."""

    title: str
    url: str
    source_domain: str
    published_at: datetime
    language: str = ""
    image_url: str | None = None
    description: str = ""
    city: str = ""
    state: str = ""
    category: str = ""
    last_updated_at: datetime | None = None


class NearbyPlace(BaseModel):
    """A mapped point of interest returned by OpenStreetMap."""

    id: str
    name: str
    category: str
    subtype: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    distance_km: float = Field(ge=0)
    address: str = ""
    osm_type: str = ""
    osm_id: int | None = None
    source: str = "OpenStreetMap"
    opening_status: str | None = None
    last_updated_at: datetime | None = None


class Earthquake(BaseModel):
    """A recent USGS earthquake event."""

    id: str
    magnitude: float
    place: str
    occurred_at: datetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    depth_km: float
    distance_km: float = Field(ge=0)
    url: str
    last_updated_at: datetime | None = None


class CitySnapshot(BaseModel):
    """Dashboard-ready view model with per-feed provenance."""

    city: City
    generated_at: datetime
    weather: WeatherConditions | None = None
    air_quality: AirQualityConditions | None = None
    alerts: list[CivicAlert] = Field(default_factory=list)
    events: list[CityEvent] = Field(default_factory=list)
    news: list[NewsStory] = Field(default_factory=list)
    places: list[NearbyPlace] = Field(default_factory=list)
    earthquakes: list[Earthquake] = Field(default_factory=list)
    neighborhood_alerts: list[NeighborhoodAlert] = Field(default_factory=list)
    sources: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
