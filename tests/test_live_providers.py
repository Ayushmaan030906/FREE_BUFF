from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx

from citypulse.data import events, live, sachet
from citypulse.data.feed_health import feed_health_rows
from citypulse.data.neighborhood_alerts import build_neighborhood_alerts
from citypulse.domain.models import (
    AirQualityConditions,
    City,
    CitySnapshot,
    Earthquake,
    NewsStory,
    WeatherConditions,
)


class LiveProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.city = City(
            name="Mumbai",
            state="Maharashtra",
            latitude=19.0760,
            longitude=72.8777,
            timezone="Asia/Kolkata",
            country="India",
            country_code="IN",
        )

    def test_live_snapshot_does_not_fill_failures_with_demo_fixtures(self) -> None:
        unavailable = (None, "provider unavailable")
        with (
            patch.object(live, "_cached_weather", return_value=unavailable),
            patch.object(live, "_cached_air_quality", return_value=unavailable),
            patch.object(live, "_cached_news", return_value=unavailable),
            patch.object(live, "_cached_places", return_value=unavailable),
            patch.object(live, "_cached_earthquakes", return_value=unavailable),
            patch.object(live, "cached_sachet_alerts", return_value=unavailable),
            patch.object(live, "cached_ticketmaster_events", return_value=unavailable),
        ):
            snapshot = live.LiveCityProvider().load_snapshot(self.city)

        self.assertIsNone(snapshot.weather)
        self.assertIsNone(snapshot.air_quality)
        self.assertEqual(snapshot.news, [])
        self.assertEqual(snapshot.places, [])
        self.assertEqual(snapshot.earthquakes, [])
        self.assertEqual(snapshot.alerts, [])
        self.assertEqual(snapshot.events, [])
        self.assertFalse(snapshot.neighborhood_alerts)
        self.assertNotIn("sample", snapshot.model_dump_json().casefold())

    def test_missing_gnews_key_is_an_unavailable_state(self) -> None:
        live._cached_news.clear()
        try:
            result, error = live._cached_news("Mumbai", "India", "IN", None, 2.0)
        finally:
            live._cached_news.clear()
        self.assertIsNone(result)
        self.assertIn("GNEWS_API_KEY", error or "")

    def test_empty_provider_results_remain_empty_live_results(self) -> None:
        with (
            patch.object(live, "_cached_weather", return_value=(None, "unavailable")),
            patch.object(live, "_cached_air_quality", return_value=(None, "unavailable")),
            patch.object(live, "_cached_news", return_value=([], None)),
            patch.object(live, "_cached_places", return_value=([], None)),
            patch.object(live, "_cached_earthquakes", return_value=([], None)),
            patch.object(live, "cached_sachet_alerts", return_value=([], None)),
            patch.object(live, "cached_ticketmaster_events", return_value=([], None)),
        ):
            snapshot = live.LiveCityProvider().load_snapshot(self.city)

        self.assertEqual(snapshot.news, [])
        self.assertEqual(snapshot.places, [])
        self.assertEqual(snapshot.earthquakes, [])
        self.assertEqual(snapshot.alerts, [])
        self.assertEqual(snapshot.events, [])
        self.assertTrue(snapshot.sources["Nearby places"].startswith("Live:"))
        self.assertTrue(snapshot.sources["Events"].startswith("Live:"))

    def test_overpass_timeout_returns_a_safe_error_without_sample_places(self) -> None:
        with patch.object(live, "_cached_places_success", side_effect=httpx.TimeoutException("slow")):
            places, error = live._cached_places(19.0760, 72.8777, 5, 2.0)
        self.assertIsNone(places)
        self.assertIn("timed out", error or "")

    def test_cap_parser_normalizes_severity_and_filters_to_selected_city(self) -> None:
        now = datetime.now(UTC)
        sent = now.isoformat().replace("+00:00", "Z")
        expires = (now + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        expired = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
        xml = f'''<?xml version="1.0" encoding="UTF-8"?>
        <alerts xmlns="urn:oasis:names:tc:emergency:cap:1.2">
        <alert>
          <identifier>rain-1</identifier><sender>agency@example.gov.in</sender>
          <senderName>State Disaster Authority</senderName><status>Actual</status>
          <msgType>Alert</msgType><sent>{sent}</sent>
          <info><event>Heavy Rain</event><headline>Heavy rain warning</headline>
            <description>Heavy rainfall is expected.</description><severity>Severe</severity>
            <expires>{expires}</expires><web>https://authority.gov.in/notice/1</web>
            <area><areaDesc>Mumbai, Maharashtra</areaDesc><circle>19.0760,72.8777 20</circle></area>
          </info>
        </alert>
        <alert>
          <identifier>expired-1</identifier><sender>agency@example.gov.in</sender>
          <status>Actual</status><msgType>Alert</msgType><sent>{sent}</sent>
          <info><event>Flood</event><headline>Expired notice</headline><severity>Extreme</severity>
            <expires>{expired}</expires><area><areaDesc>Mumbai</areaDesc><circle>19.0760,72.8777 20</circle></area>
          </info>
        </alert>
        <alert>
          <identifier>other-city</identifier><sender>agency@example.gov.in</sender>
          <status>Actual</status><msgType>Alert</msgType><sent>{sent}</sent>
          <info><event>Flood</event><headline>Other city notice</headline><severity>Extreme</severity>
            <expires>{expires}</expires><area><areaDesc>Pune</areaDesc><circle>18.5204,73.8567 5</circle></area>
          </info>
        </alert></alerts>'''.encode()

        alerts = sachet._parse_cap(xml, self.city)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].severity, "high")
        self.assertEqual(alerts[0].original_severity, "Severe")
        self.assertTrue(alerts[0].official)
        self.assertTrue(alerts[0].verified)
        self.assertEqual(alerts[0].source_url, "https://authority.gov.in/notice/1")
        self.assertEqual((alerts[0].latitude, alerts[0].longitude), (19.0760, 72.8777))

    def test_ticketmaster_event_response_is_normalized_without_claiming_free_or_official(self) -> None:
        payload = {
            "_embedded": {
                "events": [
                    {
                        "id": "evt-1",
                        "name": "Mumbai Music Night",
                        "url": "https://www.ticketmaster.com/event/evt-1",
                        "dates": {
                            "timezone": "Asia/Kolkata",
                            "start": {"dateTime": "2026-10-01T19:00:00+05:30"},
                        },
                        "classifications": [{"segment": {"name": "Music"}}],
                        "_embedded": {
                            "venues": [
                                {
                                    "name": "City Hall",
                                    "city": {"name": "Mumbai"},
                                    "state": {"name": "Maharashtra"},
                                    "location": {"latitude": "19.07", "longitude": "72.87"},
                                }
                            ]
                        },
                    }
                ]
            }
        }
        response = httpx.Response(
            200,
            json=payload,
            request=httpx.Request("GET", events.TICKETMASTER_URL),
        )
        with patch("citypulse.data.events.httpx.Client.get", return_value=response):
            listings = events.fetch_ticketmaster_events(self.city, "test-key", 2.0)

        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0].title, "Mumbai Music Night")
        self.assertEqual(listings[0].category, "Music")
        self.assertEqual(listings[0].latitude, 19.07)
        self.assertIsNone(listings[0].is_free)
        self.assertFalse(listings[0].verified)
        self.assertTrue(listings[0].source_url.startswith("https://"))

    def test_ticketmaster_empty_response_returns_empty_list(self) -> None:
        response = httpx.Response(
            200,
            json={"_embedded": {"events": []}},
            request=httpx.Request("GET", events.TICKETMASTER_URL),
        )
        with patch("citypulse.data.events.httpx.Client.get", return_value=response):
            listings = events.fetch_ticketmaster_events(self.city, "test-key", 2.0)
        self.assertEqual(listings, [])

    def test_health_rows_do_not_expose_credentials(self) -> None:
        rows = feed_health_rows(
            live_enabled=True,
            configured={"News": True, "Events": True, "Civic alerts": True},
        )
        serialized = repr(rows)
        self.assertNotIn("test-key", serialized)
        self.assertTrue(any(row["Source"] == "GNews" for row in rows))
        self.assertTrue(any(row["Source"] == "SACHET / NDMA CAP" for row in rows))

    def test_neighborhood_stream_uses_only_feeds_marked_live(self) -> None:
        now = datetime.now(UTC)
        snapshot = CitySnapshot(
            city=self.city,
            generated_at=now,
            weather=WeatherConditions(
                observed_at=now,
                temperature_c=24,
                feels_like_c=25,
                relative_humidity_pct=70,
                wind_speed_kmh=10,
                weather_code=95,
                description="Thunderstorm",
                hourly_forecast=[],
                daily_forecast=[],
            ),
            air_quality=AirQualityConditions(
                observed_at=now,
                us_aqi=160,
                european_aqi=80,
                pm2_5_ug_m3=70,
                pm10_ug_m3=90,
                hourly_forecast=[],
            ),
            news=[
                NewsStory(
                    title="Flood warning issued for local roads",
                    url="https://news.example/story",
                    source_domain="Example News",
                    published_at=now,
                )
            ],
            earthquakes=[
                Earthquake(
                    id="quake-1",
                    magnitude=5.5,
                    place="Arabian Sea",
                    occurred_at=now,
                    latitude=19.0,
                    longitude=72.8,
                    depth_km=10,
                    distance_km=12,
                    url="https://earthquake.usgs.gov/earthquakes/eventpage/quake-1",
                )
            ],
            sources={
                "News": "Live: GNews",
                "Weather": "Live: Open-Meteo",
                "Air quality": "Live: Open-Meteo",
                "Earthquakes": "Live: USGS",
            },
        )
        alerts = build_neighborhood_alerts(snapshot)
        categories = {alert.category for alert in alerts}
        self.assertEqual(categories, {"news", "weather", "air_quality", "earthquake"})

        snapshot.sources["News"] = "Unavailable: missing key"
        self.assertNotIn("news", {alert.category for alert in build_neighborhood_alerts(snapshot)})


if __name__ == "__main__":
    unittest.main()
