"""Application settings loaded from environment variables and an optional .env file."""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated defaults for a local CityPulse instance."""

    model_config = SettingsConfigDict(
        env_prefix="CITYPULSE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider: Literal["demo", "live", "open_meteo"] = "live"
    demo_mode: bool = False
    city_name: str = Field(default="Mumbai", min_length=1, max_length=80)
    state_name: str = "Maharashtra"
    latitude: float = Field(default=19.0760, ge=-90, le=90)
    longitude: float = Field(default=72.8777, ge=-180, le=180)
    timezone: str = "Asia/Kolkata"
    request_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
    places_radius_km: int = Field(default=5, ge=1, le=10)
    earthquake_radius_km: float = Field(default=300.0, ge=25, le=1000)
    gnews_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GNEWS_API_KEY", "CITYPULSE_GNEWS_API_KEY"),
    )
    imd_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("IMD_API_KEY", "CITYPULSE_IMD_API_KEY"),
    )
    ticketmaster_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("TICKETMASTER_API_KEY", "CITYPULSE_TICKETMASTER_API_KEY"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings object."""

    return Settings()
