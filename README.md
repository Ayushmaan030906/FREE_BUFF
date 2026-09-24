# CityPulse

CityPulse is a Streamlit city-intelligence dashboard for India. It combines public weather, air-quality, local-news, nearby-place and earthquake feeds, plus optional official disaster-alert and public-event providers. Live mode contains only records returned by providers; provider errors and empty results remain visibly distinct. Synthetic fixture data is available only when `CITYPULSE_DEMO_MODE=true` and the user selects Demo Preview.

## Current providers

| Section | Provider | Live behavior |
| --- | --- | --- |
| City search | Open-Meteo Geocoding | Searches place names and retains the selected place coordinates and state. |
| Weather and air | Open-Meteo Forecast and Air Quality | Current conditions, forecast, AQI, PM2.5 and PM10; requests use the selected coordinates. |
| Live news | GNews | City and country mention search. Requires a free `GNEWS_API_KEY`; key is sent from Python only. |
| Nearby places | OpenStreetMap Overpass | Real named POIs around the selected coordinates and chosen radius; cached for one hour. |
| Earthquakes | USGS ComCat | Past-day M2.5+ events within the selected radius. |
| Civic alerts | SACHET / NDMA all-India RSS + CAP | Reads the public RSS feed, fetches linked CAP records from matching city/state and regional forecast sources, then filters by CAP area geometry or an explicit city mention. No credential or feed identifier is required. |
| Events | Ticketmaster Discovery API | Optional India city query; requires `TICKETMASTER_API_KEY`. Provider listings are not a complete event calendar and are not labeled official. |
| IMD warnings | Not connected | IMD documents district warnings, nowcasts and current-weather APIs, but its public reference does not specify the API-key transport scheme. CityPulse does not guess that scheme or claim IMD data is live. Register through the official portal and check its current integration instructions before enabling it. |
| Community | Not connected | Live mode says no verified data is available. No sample civic posts or events are shown. |

The Civic Alerts section also displays clearly labeled **CityPulse generated** signals inferred from live headlines, severe Open-Meteo indicators, poor AQI, and USGS earthquakes. These are not official warnings and do not replace instructions from local authorities.

For SACHET CAP records, CityPulse preserves the provider severity and uses this explicit normalized mapping: `Minor` to `low`, `Moderate` to `medium`, `Severe` to `high`, and `Extreme` to `critical`. Unknown CAP severity values are omitted from the normalized alert list rather than guessed.

## Run locally

Python 3.11 or newer is required. From the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
streamlit run app.py
```

On macOS or Linux, activate with `source .venv/bin/activate`. The app uses the selected city coordinates; the initial selection is Mumbai, Maharashtra. Search for another city in the sidebar or enter coordinates manually.

## Configuration

Set credentials in `.env` or the deployment environment. Never put secret values in Streamlit page code or browser-side JavaScript.

```dotenv
CITYPULSE_PROVIDER=live
CITYPULSE_DEMO_MODE=false
CITYPULSE_CITY_NAME=Mumbai
CITYPULSE_STATE_NAME=Maharashtra
CITYPULSE_LATITUDE=19.0760
CITYPULSE_LONGITUDE=72.8777
CITYPULSE_TIMEZONE=Asia/Kolkata
CITYPULSE_REQUEST_TIMEOUT_SECONDS=8
CITYPULSE_PLACES_RADIUS_KM=5
CITYPULSE_EARTHQUAKE_RADIUS_KM=300
GNEWS_API_KEY=
IMD_API_KEY=
TICKETMASTER_API_KEY=
```

- `GNEWS_API_KEY`: create a key with GNews, then restart Streamlit.
- `TICKETMASTER_API_KEY`: register for the Discovery API. India coverage varies.
- `IMD_API_KEY`: CityPulse displays IMD as requiring credentials but does not send this key until the official access instructions specify the authentication scheme.
- `CITYPULSE_DEMO_MODE=true`: exposes the explicitly labeled demo option. It is false by default.

`.env` is ignored by Git. `.env.example` contains blank placeholders only. The Data Sources tab reports provider configuration, latest request time, last successful request and safe error summaries; it never displays credentials.

## Architecture

```text
app.py                                Streamlit entry point
src/citypulse/config.py               Environment configuration
src/citypulse/domain/models.py        Typed normalized domain models
src/citypulse/data/live.py            Live weather, air, Overpass and USGS adapters
src/citypulse/data/news.py            News provider contract and GNews adapter
src/citypulse/data/sachet.py          SACHET RSS/CAP adapter and alert normalization
src/citypulse/data/events.py          Ticketmaster event provider
src/citypulse/data/feed_health.py     Source registry and credential-safe refresh health
src/citypulse/data/neighborhood_alerts.py  Rule-based live signal generation
src/citypulse/ui/dashboard.py         Streamlit pages, map and source transparency
```

Provider calls are server-side. Successful responses are cached by feed: weather (10 min), air quality (15 min), GNews (20 min), SACHET RSS (3 min) and individual CAP documents (15 min), Ticketmaster (30 min), nearby places (1 hour), and USGS (15 min). Retry attempts use short exponential waits only for rate limiting and transient server errors. Public feeds can still be unavailable or rate limited.

## Tests

The test suite uses only mock responses and the Python standard library:

```powershell
python -m unittest discover -s tests -v
```

## Data and limitations

- Weather and air quality: [Open-Meteo](https://open-meteo.com/). Weather forecasts and CAMS air-quality estimates are modeled provider products.
- News: [GNews](https://docs.gnews.io/endpoints/search-endpoint). Results mention the selected city; they are not guaranteed to be physically located there.
- Nearby places and map tiles: (c) [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), queried through [Overpass](https://wiki.openstreetmap.org/wiki/Overpass_API) and displayed with Leaflet.
- Earthquakes: [USGS ComCat GeoJSON API](https://earthquake.usgs.gov/fdsnws/event/1/).
- Disaster alerts: [SACHET / NDMA India CAP RSS](https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml), with linked CAP XML records.
- Official weather warnings: [IMD API Management](https://api.imd.gov.in/public/index.php); registration is required and auth details must be confirmed with IMD.
- Public events: [Ticketmaster Discovery API](https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/); it is optional and may have limited India coverage.

CityPulse is informational and is not an emergency-response service. Missing, stale or unverified feeds are shown as unavailable rather than replaced with invented data.
