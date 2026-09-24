"""CityPulse's immersive live dashboard and interactive city map."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, cast

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from citypulse.config import Settings, get_settings
from citypulse.data.feed_health import SOURCE_REGISTRY, feed_health_rows
from citypulse.data.geocoding import search_cities
from citypulse.data.live import LiveCityProvider
from citypulse.data.providers import CityDataProvider, DemoDataProvider, city_timezone
from citypulse.domain.models import City, CitySnapshot, LocationOption


@st.cache_data(ttl=180, max_entries=48, show_spinner=False)
def load_snapshot(
    provider_mode: str,
    city_name: str,
    state: str,
    latitude: float,
    longitude: float,
    timezone: str,
    country: str,
    country_code: str,
    timeout_seconds: float,
    places_radius_km: int,
    earthquake_radius_km: float,
) -> CitySnapshot:
    """Compose the current view; individual API adapters apply their own cache TTLs."""

    city = City(
        name=city_name,
        state=state,
        latitude=latitude,
        longitude=longitude,
        timezone=timezone,
        country=country,
        country_code=country_code,
    )
    provider: CityDataProvider
    settings = get_settings()
    if provider_mode == "demo" and settings.demo_mode:
        provider = DemoDataProvider()
    else:
        api_key = settings.gnews_api_key
        ticketmaster_key = settings.ticketmaster_api_key
        provider = LiveCityProvider(
            timeout_seconds=timeout_seconds,
            places_radius_km=places_radius_km,
            earthquake_radius_km=earthquake_radius_km,
            gnews_api_key=api_key.get_secret_value() if api_key else None,
            ticketmaster_api_key=(
                ticketmaster_key.get_secret_value() if ticketmaster_key else None
            ),
        )
    return provider.load_snapshot(city)


def _inject_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
            --pulse-mint: #66e3c4;
            --pulse-blue: #75b8ff;
            --pulse-ink: #08111f;
            --pulse-panel: rgba(17, 30, 48, .82);
            --pulse-line: rgba(170, 211, 241, .13);
            --pulse-muted: #91a5bd;
        }
        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(ellipse at 80% -5%, rgba(35, 113, 164, .20), transparent 34%),
                radial-gradient(ellipse at 10% 26%, rgba(37, 175, 151, .10), transparent 32%),
                linear-gradient(145deg, #07101b 0%, #0a1422 45%, #0c1828 100%);
        }
        [data-testid="stMainBlockContainer"] { max-width: 1580px; padding-top: 2rem; }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, rgba(13, 25, 41, .98), rgba(8, 17, 30, .98));
            border-right: 1px solid rgba(163, 206, 234, .12);
        }
        [data-testid="stMetric"] {
            min-height: 126px;
            padding: 19px 20px;
            border: 1px solid rgba(165, 211, 237, .14);
            border-radius: 19px;
            background: linear-gradient(145deg, rgba(27, 47, 68, .88), rgba(13, 25, 41, .94));
            box-shadow: inset 0 1px 0 rgba(255,255,255,.06), 0 18px 38px rgba(0,0,0,.24);
            transform: perspective(1100px) rotateX(.7deg);
        }
        [data-testid="stMetricLabel"] p { color: #9fb4ca; letter-spacing: .04em; }
        [data-testid="stMetricValue"] { color: #f1f7fc; }
        [data-testid="stVerticalBlockBorderWrapper"] {
            border-color: rgba(165, 211, 237, .13) !important;
            background: linear-gradient(150deg, rgba(22, 39, 59, .78), rgba(11, 22, 37, .88));
            box-shadow: 0 16px 38px rgba(0, 0, 0, .18), inset 0 1px 0 rgba(255,255,255,.035);
        }
        [data-testid="stTabs"] button {
            border-radius: 12px 12px 5px 5px;
            font-weight: 650;
        }
        div.stButton > button, div.stLinkButton > a {
            border-radius: 12px;
            border: 1px solid rgba(102, 227, 196, .28);
            background: linear-gradient(135deg, rgba(37, 89, 103, .8), rgba(25, 49, 70, .95));
            color: #e9fffa;
            box-shadow: 0 8px 24px rgba(0, 0, 0, .2), inset 0 1px 0 rgba(255,255,255,.08);
            transition: transform .18s ease, box-shadow .18s ease;
        }
        div.stButton > button:hover, div.stLinkButton > a:hover {
            border-color: rgba(102, 227, 196, .75);
            transform: translateY(-2px);
            box-shadow: 0 13px 28px rgba(0,0,0,.3), 0 0 20px rgba(102,227,196,.12);
        }
        .hero-panel {
            position: relative;
            overflow: hidden;
            min-height: 246px;
            margin: 0 0 1.15rem 0;
            padding: 30px 34px;
            border: 1px solid rgba(164, 217, 243, .19);
            border-radius: 26px;
            background:
                radial-gradient(ellipse at 82% 68%, rgba(74, 205, 183, .18), transparent 34%),
                linear-gradient(120deg, rgba(17, 39, 58, .97), rgba(13, 25, 41, .90) 50%, rgba(15, 39, 54, .95));
            box-shadow: 0 28px 70px rgba(0,0,0,.36), inset 0 1px 0 rgba(255,255,255,.08);
            transform: perspective(1500px) rotateX(.6deg);
        }
        .hero-panel:before {
            content: ""; position: absolute; inset: 0;
            background-image: linear-gradient(rgba(173,219,239,.035) 1px, transparent 1px),
                              linear-gradient(90deg, rgba(173,219,239,.035) 1px, transparent 1px);
            background-size: 38px 38px;
            mask-image: linear-gradient(90deg, black, transparent 82%);
            pointer-events: none;
        }
        .hero-glow {
            position: absolute; width: 440px; height: 300px; right: 3%; top: 12%;
            border-radius: 50%; background: rgba(69, 195, 191, .10);
            filter: blur(45px); pointer-events: none;
        }
        .hero-skyline {
            position: absolute; right: 0; bottom: 0; width: 56%; height: 92%;
            opacity: .90; filter: drop-shadow(0 0 24px rgba(72, 211, 196, .16));
            pointer-events: none;
        }
        .hero-copy { position: relative; z-index: 2; max-width: 58%; }
        .hero-kicker {
            margin: 18px 0 5px 0; color: #85a8bd; font-size: .72rem;
            letter-spacing: .19em; font-weight: 750;
        }
        .hero-title {
            margin: 0; color: #f2f8fc; font-size: clamp(2.25rem, 4vw, 3.7rem);
            line-height: 1.02; letter-spacing: -.045em; font-weight: 760;
        }
        .hero-title span { color: var(--pulse-mint); }
        .hero-subtitle { margin: 12px 0 0 0; color: #aec2d4; font-size: 1rem; }
        .hero-status {
            display: inline-flex; align-items: center; gap: 9px;
            border: 1px solid rgba(102,227,196,.28); border-radius: 99px;
            padding: 7px 12px; background: rgba(8,23,35,.72); color: #b5f7e7;
            font-size: .69rem; font-weight: 760; letter-spacing: .13em;
        }
        .hero-dot {
            width: 8px; height: 8px; border-radius: 50%; background: #66e3c4;
            box-shadow: 0 0 12px #66e3c4, 0 0 25px rgba(102,227,196,.72);
        }
        .section-eyebrow { color: #7f9db4; font-size: .68rem; font-weight: 750; letter-spacing: .16em; }
        .data-note { color: #91a5bd; font-size: .82rem; }
        .legend-row { display:flex; flex-wrap:wrap; gap:9px; margin:10px 0 2px 0; }
        .legend-chip {
            display:inline-flex; align-items:center; gap:7px; padding:6px 10px;
            border:1px solid rgba(162,202,225,.15); border-radius:99px;
            background:rgba(16,31,47,.78); color:#c1d1df; font-size:.75rem;
        }
        .legend-dot { width:8px; height:8px; border-radius:50%; display:inline-block; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _initialize_state(settings: Settings) -> None:
    defaults: dict[str, Any] = {
        "citypulse_city_name": settings.city_name,
        "citypulse_state": settings.state_name,
        "citypulse_latitude": float(settings.latitude),
        "citypulse_longitude": float(settings.longitude),
        "citypulse_timezone": settings.timezone,
        "citypulse_country": "India" if settings.city_name.casefold() == "mumbai" else "",
        "citypulse_country_code": "IN" if settings.city_name.casefold() == "mumbai" else "",
        "citypulse_manual_latitude": float(settings.latitude),
        "citypulse_manual_longitude": float(settings.longitude),
        "citypulse_manual_timezone": settings.timezone,
        "citypulse_provider_mode": (
            "demo" if settings.provider == "demo" and settings.demo_mode else "live"
        ),
        "citypulse_auto_refresh": "Off" if settings.provider == "demo" and settings.demo_mode else "5 minutes",
        "citypulse_places_radius": settings.places_radius_km,
        "citypulse_search_results": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if st.session_state.get("citypulse_provider_mode") == "open_meteo" or (
        st.session_state.get("citypulse_provider_mode") == "demo" and not settings.demo_mode
    ):
        st.session_state["citypulse_provider_mode"] = "live"


def _render_sidebar(settings: Settings) -> tuple[str, City, int, float, str | None]:
    _initialize_state(settings)
    st.sidebar.markdown("## CityPulse")
    st.sidebar.caption("Personalize the city signal and nearby scan.")

    with st.sidebar.form("citypulse_city_search", clear_on_submit=False):
        query = st.text_input("Find a city", placeholder="e.g. Mumbai, India", key="citypulse_search_query")
        search_submitted = st.form_submit_button("Search locations", use_container_width=True)
    if search_submitted:
        try:
            matches = search_cities(query, settings.request_timeout_seconds)
            st.session_state["citypulse_search_results"] = [item.model_dump() for item in matches]
            st.session_state.pop("citypulse_location_choice", None)
            if not matches:
                st.session_state["citypulse_search_message"] = "No matching cities. Try a city and country name."
            else:
                st.session_state.pop("citypulse_search_message", None)
        except RuntimeError as error:
            st.session_state["citypulse_search_message"] = str(error)
            st.session_state["citypulse_search_results"] = []

    search_message = st.session_state.get("citypulse_search_message")
    if search_message:
        st.sidebar.caption(search_message)

    result_payloads = st.session_state.get("citypulse_search_results", [])
    if result_payloads:
        location_options = [LocationOption.model_validate(item) for item in result_payloads]
        location_by_label = {
            f"{location.label} · {location.latitude:.3f}, {location.longitude:.3f}": location
            for location in location_options
        }
        selected_label = st.sidebar.selectbox(
            "Search results",
            options=list(location_by_label),
            key="citypulse_location_choice",
        )
        selected_location = location_by_label[selected_label]
        if st.session_state.get("citypulse_active_location_id") != selected_location.id:
            st.session_state["citypulse_city_name"] = selected_location.name
            st.session_state["citypulse_state"] = selected_location.admin1
            st.session_state["citypulse_latitude"] = selected_location.latitude
            st.session_state["citypulse_longitude"] = selected_location.longitude
            st.session_state["citypulse_timezone"] = selected_location.timezone
            st.session_state["citypulse_country"] = selected_location.country
            st.session_state["citypulse_country_code"] = selected_location.country_code
            st.session_state["citypulse_manual_latitude"] = selected_location.latitude
            st.session_state["citypulse_manual_longitude"] = selected_location.longitude
            st.session_state["citypulse_manual_timezone"] = selected_location.timezone
            st.session_state["citypulse_active_location_id"] = selected_location.id

    provider_modes = ("live", "demo") if settings.demo_mode else ("live",)
    provider_mode = st.sidebar.selectbox(
        "Data mode",
        options=provider_modes,
        format_func=lambda value: "LIVE CITY FEEDS" if value == "live" else "DEMO PREVIEW",
        key="citypulse_provider_mode",
    )
    refresh_label = st.sidebar.selectbox(
        "Live dashboard refresh",
        options=("Off", "2 minutes", "5 minutes", "15 minutes"),
        key="citypulse_auto_refresh",
    )
    with st.sidebar.expander("Map and coverage", expanded=False):
        places_radius = st.selectbox(
            "Nearby places radius",
            options=tuple(sorted({3, 5, 8, 10, settings.places_radius_km})),
            format_func=lambda value: f"{value} km",
            key="citypulse_places_radius",
        )
        radius_options = sorted({100.0, 300.0, 500.0, 1000.0, float(settings.earthquake_radius_km)})
        earthquake_radius = st.select_slider(
            "Earthquake scan radius",
            options=radius_options,
            value=float(settings.earthquake_radius_km),
            format_func=lambda value: f"{value:.0f} km",
            key="citypulse_earthquake_radius",
        )
        st.caption("Places refresh hourly to respect the shared public OpenStreetMap service.")

    with st.sidebar.expander("Coordinates and timezone", expanded=False):
        st.caption(f"Current location: {st.session_state['citypulse_city_name']}")
        with st.form("citypulse_manual_location"):
            manual_latitude = st.number_input(
                "Latitude",
                min_value=-90.0,
                max_value=90.0,
                step=0.001,
                format="%.4f",
                key="citypulse_manual_latitude",
            )
            manual_longitude = st.number_input(
                "Longitude",
                min_value=-180.0,
                max_value=180.0,
                step=0.001,
                format="%.4f",
                key="citypulse_manual_longitude",
            )
            manual_timezone = st.text_input("Timezone", key="citypulse_manual_timezone")
            apply_location = st.form_submit_button("Apply coordinates", use_container_width=True)
        if apply_location:
            st.session_state["citypulse_latitude"] = float(manual_latitude)
            st.session_state["citypulse_longitude"] = float(manual_longitude)
            st.session_state["citypulse_timezone"] = manual_timezone.strip() or "UTC"

    st.sidebar.caption("Upstream source caches remain active during automatic refresh.")
    city = City(
        name=str(st.session_state["citypulse_city_name"]).strip() or settings.city_name,
        latitude=float(st.session_state["citypulse_latitude"]),
        longitude=float(st.session_state["citypulse_longitude"]),
        timezone=str(st.session_state["citypulse_timezone"]),
        country=str(st.session_state["citypulse_country"]),
        country_code=str(st.session_state["citypulse_country_code"]),
        state=str(st.session_state["citypulse_state"]),
    )
    refresh_intervals = {"Off": None, "2 minutes": "2m", "5 minutes": "5m", "15 minutes": "15m"}
    refresh_interval = refresh_intervals[str(refresh_label)] if provider_mode == "live" else None
    return cast(str, provider_mode), city, int(places_radius), float(earthquake_radius), refresh_interval


def _aqi_status(value: float) -> tuple[str, str]:
    if value <= 50:
        return "Good", "#66e3c4"
    if value <= 100:
        return "Moderate", "#f3c969"
    if value <= 150:
        return "Unhealthy for sensitive groups", "#ff9a68"
    if value <= 200:
        return "Unhealthy", "#ff647c"
    if value <= 300:
        return "Very unhealthy", "#c48bff"
    return "Hazardous", "#ff5567"


def _render_hero(city: City, provider_mode: str, snapshot: CitySnapshot) -> None:
    city_name = escape(city.name)
    if provider_mode == "demo":
        status = "DEMO DATA"
    else:
        core_sources = ("Weather", "Air quality", "News", "Nearby places", "Earthquakes")
        connected = sum(
            snapshot.sources.get(name, "").startswith("Live:") for name in core_sources
        )
        status = "LIVE" if connected == len(core_sources) else "DEGRADED" if connected else "OFFLINE"
    local_now = datetime.now(city_timezone(city.timezone))
    st.markdown(
        f"""
        <section class="hero-panel">
          <div class="hero-glow"></div>
          <svg class="hero-skyline" viewBox="0 0 900 360" preserveAspectRatio="xMaxYMax meet" aria-hidden="true">
            <defs>
              <linearGradient id="building" x1="0" x2="1" y1="0" y2="1">
                <stop offset="0" stop-color="#44c7b7" stop-opacity=".52"/>
                <stop offset="1" stop-color="#172d48" stop-opacity=".08"/>
              </linearGradient>
              <linearGradient id="tower" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0" stop-color="#82ebdb" stop-opacity=".52"/>
                <stop offset="1" stop-color="#1a3551" stop-opacity=".18"/>
              </linearGradient>
            </defs>
            <path d="M0 360V255h52v-72h36v28h24V138h58v74h25v-35h39v67h33V96h65v144h25v-92h40v35h28V65h76v173h27V148h54v88h30V112h43v119h28V83h61v145h35V178h48v65h38v-58h39v98h42v77z" fill="url(#building)"/>
            <path d="M318 360V96h65v264M512 360V65h76v295M694 360V83h61v277" fill="url(#tower)" stroke="#74e4d4" stroke-opacity=".25"/>
            <g fill="#b6f5e9" opacity=".55">
              <path d="M334 124h8v12h-8zm18 0h8v12h-8zm18 0h8v12h-8zm-36 28h8v12h-8zm18 0h8v12h-8zm18 0h8v12h-8zm-36 28h8v12h-8zm18 0h8v12h-8zm18 0h8v12h-8z"/>
              <path d="M530 96h9v13h-9zm20 0h9v13h-9zm20 0h9v13h-9zm-40 31h9v13h-9zm20 0h9v13h-9zm20 0h9v13h-9zm-40 31h9v13h-9zm20 0h9v13h-9zm20 0h9v13h-9z"/>
              <path d="M710 113h8v12h-8zm18 0h8v12h-8zm-18 27h8v12h-8zm18 0h8v12h-8zm-18 27h8v12h-8zm18 0h8v12h-8z"/>
            </g>
            <path d="M0 337c145-22 284 10 423-7s272-35 477 4v26H0z" fill="#55d7c2" opacity=".16"/>
          </svg>
          <div class="hero-copy">
            <div class="hero-status"><span class="hero-dot"></span>{status}</div>
            <p class="hero-kicker">CITY INTELLIGENCE / DAILY BRIEF · {local_now:%A, %d %B}</p>
            <h1 class="hero-title">{city_name} <span>in focus.</span></h1>
            <p class="hero-subtitle">A living view of weather, clean air, neighborhood places, news and earth signals.</p>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_city_map(snapshot: CitySnapshot) -> None:
    st.markdown(
        '<p class="section-eyebrow">SPATIAL SIGNALS / LIVE LEAFLET VIEW</p>',
        unsafe_allow_html=True,
    )
    st.subheader("Your city, at street level")
    places_source = snapshot.sources.get("Nearby places", "")
    if places_source.startswith("Live:"):
        earthquake_source = snapshot.sources.get("Earthquakes", "")
        earthquake_summary = (
            f"{len(snapshot.earthquakes)} M2.5+ earthquakes are within the selected regional radius."
            if earthquake_source.startswith("Live:")
            else "Earthquake data is unavailable."
        )
        st.caption(
            f"Pan and zoom to explore {len(snapshot.places)} nearby mapped places. "
            f"{earthquake_summary}"
        )
    else:
        st.warning("Live place data is unavailable; the map currently shows only the selected city center.")
    st_folium(
        _leaflet_map(snapshot),
        height=515,
        use_container_width=True,
        returned_objects=[],
        key="citypulse_live_leaflet_map",
    )
    st.markdown(
        "<div class='legend-row'>"
        "<span class='legend-chip'><i class='legend-dot' style='background:#68f2db'></i>City center</span>"
        "<span class='legend-chip'><i class='legend-dot' style='background:#5cafff'></i>Health</span>"
        "<span class='legend-chip'><i class='legend-dot' style='background:#ffc15e'></i>Transit</span>"
        "<span class='legend-chip'><i class='legend-dot' style='background:#ff657b'></i>Earthquake</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption("Map data (c) OpenStreetMap contributors; places via Overpass; earthquakes via USGS.")


def _leaflet_map(snapshot: CitySnapshot) -> folium.Map:
    """Build a Leaflet map with OSM tiles and live POI/earthquake layers."""

    city_map = folium.Map(
        location=[snapshot.city.latitude, snapshot.city.longitude],
        zoom_start=12,
        tiles="OpenStreetMap",
        control_scale=True,
        prefer_canvas=True,
    )
    folium.CircleMarker(
        location=[snapshot.city.latitude, snapshot.city.longitude],
        radius=9,
        color="#68f2db",
        weight=3,
        fill=True,
        fill_color="#173c47",
        fill_opacity=0.95,
        tooltip=f"{escape(snapshot.city.name)} · selected city",
        popup=folium.Popup(
            f"<strong>{escape(snapshot.city.name)}</strong><br>Selected city center",
            max_width=280,
        ),
    ).add_to(city_map)

    mapped_alerts = [
        alert
        for alert in snapshot.alerts
        if alert.latitude is not None and alert.longitude is not None
    ]
    if mapped_alerts:
        alert_group = folium.FeatureGroup(name=f"Official alerts ({len(mapped_alerts)})", show=True)
        alert_group.add_to(city_map)
        severity_colors = {
            "critical": "#ff3e58",
            "high": "#ff784f",
            "medium": "#ffc45c",
            "low": "#69dca4",
        }
        for alert in mapped_alerts:
            color = severity_colors[alert.severity]
            popup = (
                f"<strong>{escape(alert.title)}</strong><br>{escape(alert.source)}<br>"
                f"Affected-area marker from CAP geometry; it is not an incident location."
            )
            if alert.source_url:
                popup += (
                    f'<br><a href="{escape(alert.source_url, quote=True)}" target="_blank" '
                    'rel="noopener">Original notice</a>'
                )
            folium.CircleMarker(
                location=[alert.latitude, alert.longitude],
                radius=9,
                color=color,
                weight=2,
                fill=True,
                fill_color=color,
                fill_opacity=0.78,
                tooltip=f"{alert.severity.upper()} | {escape(alert.title)}",
                popup=folium.Popup(popup, max_width=360),
            ).add_to(alert_group)

    category_colors = {
        "Health": "#5cafff",
        "Emergency": "#ff657b",
        "Transit": "#ffc15e",
        "Transport": "#ffc15e",
        "Education": "#5bcfda",
        "Food & drink": "#f0bc66",
        "Green space": "#69dca4",
        "Recreation": "#62d4c9",
        "Shopping": "#f9a56f",
        "Finance": "#85b8ff",
        "Culture": "#d187ff",
        "Community": "#9984ff",
    }
    place_groups: dict[str, folium.FeatureGroup] = {}
    for place in snapshot.places:
        group = place_groups.get(place.category)
        if group is None:
            count = sum(item.category == place.category for item in snapshot.places)
            group = folium.FeatureGroup(name=f"{place.category} ({count})", show=True)
            group.add_to(city_map)
            place_groups[place.category] = group
        color = category_colors.get(place.category, "#7ab8ff")
        address = f"<br>{escape(place.address)}" if place.address else ""
        osm_link = ""
        if place.osm_id is not None and place.osm_type:
            osm_link = (
                f'<br><a href="https://www.openstreetmap.org/{escape(place.osm_type)}/'
                f'{place.osm_id}" target="_blank" rel="noopener">OSM {escape(place.osm_type)}/'
                f'{place.osm_id}</a>'
            )
        popup_html = (
            f"<strong>{escape(place.name)}</strong><br>{escape(place.category)} · "
            f"{escape(place.subtype)}<br>{place.distance_km:.1f} km from center"
            f"{address}<br>{place.latitude:.5f}, {place.longitude:.5f}{osm_link}"
        )
        folium.CircleMarker(
            location=[place.latitude, place.longitude],
            radius=6,
            color=color,
            weight=2,
            fill=True,
            fill_color=color,
            fill_opacity=0.86,
            tooltip=f"{escape(place.name)} · {escape(place.subtype)}",
            popup=folium.Popup(popup_html, max_width=330),
        ).add_to(group)

    mapped_events = [
        event
        for event in snapshot.events
        if event.latitude is not None and event.longitude is not None
    ]
    if mapped_events:
        event_group = folium.FeatureGroup(name=f"Events ({len(mapped_events)})", show=True)
        event_group.add_to(city_map)
        for event in mapped_events:
            event_url = (
                f'<br><a href="{escape(event.source_url, quote=True)}" target="_blank" '
                'rel="noopener">Event source</a>'
                if event.source_url
                else ""
            )
            folium.CircleMarker(
                location=[event.latitude, event.longitude],
                radius=7,
                color="#bd8cff",
                weight=2,
                fill=True,
                fill_color="#bd8cff",
                fill_opacity=0.82,
                tooltip=escape(event.title),
                popup=folium.Popup(
                    f"<strong>{escape(event.title)}</strong><br>{escape(event.venue)}{event_url}",
                    max_width=320,
                ),
            ).add_to(event_group)

    if snapshot.earthquakes:
        earthquake_group = folium.FeatureGroup(name="Recent earthquakes", show=True)
        earthquake_group.add_to(city_map)
        for quake in snapshot.earthquakes:
            popup_html = (
                f"<strong>M{quake.magnitude:.1f} · {escape(quake.place)}</strong><br>"
                f"{quake.distance_km:.0f} km away · {quake.depth_km:.1f} km deep<br>"
                f"{quake.occurred_at:%Y-%m-%d %H:%M UTC}<br>"
                f'<a href="{escape(quake.url, quote=True)}" target="_blank" rel="noopener">USGS details</a>'
            )
            folium.CircleMarker(
                location=[quake.latitude, quake.longitude],
                radius=max(6, min(18, 3 + quake.magnitude * 2)),
                color="#ff657b",
                weight=2,
                fill=True,
                fill_color="#ff657b",
                fill_opacity=0.72,
                tooltip=f"M{quake.magnitude:.1f} · {escape(quake.place)}",
                popup=folium.Popup(popup_html, max_width=340),
            ).add_to(earthquake_group)

    folium.LayerControl(collapsed=False).add_to(city_map)
    return city_map


def _render_weather_and_air(snapshot: CitySnapshot) -> None:
    weather = snapshot.weather
    air = snapshot.air_quality
    weather_column, air_column = st.columns((1.1, 1), gap="large")
    with weather_column:
        st.subheader("Next 24 hours")
        if weather is None:
            st.info(snapshot.sources.get("Weather", "Live data unavailable."))
        else:
            hourly = pd.DataFrame(
                [
                    {
                        "Local time": point.time.strftime("%H:%M"),
                        "Temperature (deg C)": point.temperature_c,
                        "Rain chance (%)": point.precipitation_probability_pct,
                    }
                    for point in weather.hourly_forecast
                ]
            )
            if hourly.empty:
                st.info("No hourly weather data is available from the live source.")
            else:
                st.line_chart(hourly, x="Local time", y="Temperature (deg C)", height=240)
                st.area_chart(hourly, x="Local time", y="Rain chance (%)", height=160)
    with air_column:
        st.subheader("Air quality trend")
        if air is None:
            st.info(snapshot.sources.get("Air quality", "Live data unavailable."))
        else:
            air_points = pd.DataFrame(
                [
                    {
                        "Local time": point.time.strftime("%H:%M"),
                        "US AQI": point.us_aqi,
                        "PM2.5 (ug/m3)": point.pm2_5_ug_m3,
                    }
                    for point in air.hourly_forecast
                ]
            )
            if air_points.empty:
                st.info("No hourly air-quality data is available from the live source.")
            else:
                st.line_chart(air_points, x="Local time", y="US AQI", height=240)
                st.area_chart(air_points, x="Local time", y="PM2.5 (ug/m3)", height=160)

    st.subheader("Seven-day forecast")
    if weather is None or not weather.daily_forecast:
        st.info("Live forecast data unavailable.")
        return
    forecast_columns = st.columns(min(7, len(weather.daily_forecast)))
    for column, day in zip(forecast_columns, weather.daily_forecast):
        with column:
            st.markdown(f"**{day.day:%a}**")
            st.markdown(f"{day.temperature_max_c:.0f} C / {day.temperature_min_c:.0f} C")
            st.caption(f"Rain {day.precipitation_probability_max_pct:.0f}% | UV {day.uv_index_max:.0f}")
            if day.sunrise and day.sunset:
                st.caption(f"Sunrise {day.sunrise:%H:%M} | sunset {day.sunset:%H:%M}")

def _render_news(snapshot: CitySnapshot) -> None:
    st.markdown('<p class="section-eyebrow">GNEWS / STORIES MENTIONING THIS CITY</p>', unsafe_allow_html=True)
    st.subheader("Live local news pulse")
    st.caption(
        "Searches recent coverage using the selected city and country. Results are mention-based, "
        "not geocoded; freshness depends on the provider."
    )
    source = snapshot.sources.get("News", "Unavailable")
    st.caption(f"Feed status: {source}")
    if not snapshot.news:
        if source.startswith("Live:"):
            st.info("No recent local news found for this area.")
        else:
            st.warning("Live news unavailable. Configure GNEWS_API_KEY or check the Data Sources page.")
        return
    for story in snapshot.news:
        with st.container(border=True):
            if story.image_url:
                st.image(story.image_url, use_container_width=True)
            st.markdown(f"**{story.title}**")
            if story.description:
                st.write(story.description)
            updated = (
                f" | updated {story.last_updated_at:%b %d, %H:%M UTC}"
                if story.last_updated_at
                else ""
            )
            st.caption(f"{story.source_domain} | {story.published_at:%b %d, %H:%M UTC}{updated}")
            st.link_button("Read source ?", story.url, use_container_width=True)


def _render_civic_alerts(snapshot: CitySnapshot, provider_mode: str) -> None:
    st.markdown('<p class="section-eyebrow">OFFICIAL DISASTER AND CIVIC INFORMATION</p>', unsafe_allow_html=True)
    st.subheader("Civic alerts")
    st.caption(f"Source status: {snapshot.sources.get('Civic alerts', 'Unavailable')}")
    active_alerts = [
        alert for alert in snapshot.alerts
        if alert.expires_at is None or alert.expires_at > datetime.now(alert.expires_at.tzinfo)
    ]
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    active_alerts.sort(
        key=lambda item: (severity_order[item.severity], -item.published_at.timestamp())
    )
    if not active_alerts:
        if snapshot.sources.get("Civic alerts", "").startswith("Live:"):
            st.info("No active verified disaster alerts found for this area.")
        elif provider_mode == "demo":
            st.info("DEMO DATA: no fixture alert is currently available.")
        else:
            st.info("No verified live data available for this area.")
    for alert in active_alerts:
        with st.container(border=True):
            badge = "OFFICIAL | VERIFIED" if alert.official and alert.verified else "DEMO DATA"
            st.markdown(f"**{alert.severity.upper()} | {alert.title}** · `{badge}`")
            location = alert.neighborhood or ", ".join(filter(None, (alert.city, alert.district, alert.state)))
            st.caption(f"{location or snapshot.city.name} | {alert.source} | Issued {alert.published_at:%b %d, %H:%M UTC}")
            if alert.last_updated_at:
                st.caption(f"Feed updated {alert.last_updated_at:%b %d, %H:%M UTC}")
            if alert.expires_at:
                st.caption(f"Valid until {alert.expires_at:%b %d, %H:%M UTC}")
            if alert.description:
                st.write(alert.description)
            if alert.source_url:
                st.link_button("View original notice ?", alert.source_url, use_container_width=True)

    st.divider()
    st.markdown("#### CityPulse generated neighborhood signals")
    _render_neighborhood_alerts(snapshot, provider_mode)


def _render_events(snapshot: CitySnapshot, provider_mode: str) -> None:
    st.markdown('<p class="section-eyebrow">PUBLIC EVENT LISTINGS / ATTRIBUTED PROVIDERS</p>', unsafe_allow_html=True)
    st.subheader("Events")
    st.caption(f"Feed status: {snapshot.sources.get('Events', 'Unavailable')}")
    if not snapshot.events:
        if snapshot.sources.get("Events", "").startswith("Live:"):
            st.info("No verified events found for this area.")
        elif provider_mode == "demo":
            st.info("DEMO DATA: no event fixtures are available.")
        else:
            st.info("No verified live data available for this area.")
        return
    now = datetime.now(city_timezone(snapshot.city.timezone))
    for event in sorted(snapshot.events, key=lambda item: item.starts_at):
        with st.container(border=True):
            st.markdown(f"**{event.category.upper()}**")
            st.markdown(f"### {event.title}")
            local_time = event.starts_at.astimezone(city_timezone(snapshot.city.timezone))
            st.caption(f"{event.venue} | {event.city or snapshot.city.name} | {local_time:%a, %b %d | %H:%M %Z}")
            if event.ends_at:
                event_end = event.ends_at.astimezone(city_timezone(snapshot.city.timezone))
                st.caption(f"Ends {event_end:%b %d, %H:%M %Z}")
            if event.description:
                st.write(event.description)
            st.caption(f"Source: {event.source or 'DEMO DATA'} | Updated {event.last_updated_at or now:%b %d, %H:%M %Z}")
            if event.source_url:
                st.link_button("View event listing ?", event.source_url, use_container_width=True)


def _render_nearby_places(snapshot: CitySnapshot) -> None:
    st.markdown('<p class="section-eyebrow">OPENSTREETMAP / NEIGHBORHOOD INVENTORY</p>', unsafe_allow_html=True)
    st.subheader("Places around you")
    source = snapshot.sources.get("Nearby places", "Unavailable")
    st.caption(f"Feed status: {source}")
    if not snapshot.places:
        if source.startswith("Live:"):
            st.info("No named places were returned within this radius. Try increasing the scan radius.")
        else:
            st.warning("Live nearby places are unavailable. Check the Data Sources page for status.")
        return
    category_filter = st.selectbox(
        "Filter places",
        options=("All categories", *sorted({place.category for place in snapshot.places})),
        key="citypulse_place_filter",
    )
    places = snapshot.places
    if category_filter != "All categories":
        places = [place for place in places if place.category == category_filter]
    for place in places:
        with st.container(border=True):
            st.markdown(f"**{place.name}**")
            details = (
                f"{place.subtype} | {place.distance_km:.1f} km away | "
                f"{place.latitude:.5f}, {place.longitude:.5f}"
            )
            if place.address:
                details += f" | {place.address}"
            if place.osm_id is not None and place.osm_type:
                details += f" | OSM {place.osm_type}/{place.osm_id}"
            if place.last_updated_at:
                details += f" | Updated {place.last_updated_at:%b %d, %H:%M UTC}"
            st.caption(details)


def _render_earthquakes(snapshot: CitySnapshot) -> None:
    st.markdown('<p class="section-eyebrow">USGS / M2.5+ PAST-DAY SIGNALS</p>', unsafe_allow_html=True)
    st.subheader("Seismic activity nearby")
    source = snapshot.sources.get("Earthquakes", "Unavailable")
    st.caption(f"Feed status: {source}")
    if not snapshot.earthquakes:
        if source.startswith("Live:"):
            st.success("No M2.5+ earthquakes were detected inside this scan radius in the past day.")
        else:
            st.warning("Live earthquake data is unavailable; the current count is unknown.")
        return
    for quake in snapshot.earthquakes:
        with st.container(border=True):
            st.markdown(f"**M{quake.magnitude:.1f} | {quake.place}**")
            st.caption(
                f"{quake.distance_km:.0f} km away | {quake.depth_km:.1f} km deep | "
                f"{quake.occurred_at:%b %d, %H:%M UTC}"
            )
            if quake.last_updated_at:
                st.caption(f"Feed updated {quake.last_updated_at:%b %d, %H:%M UTC}")
            st.link_button("USGS event details ?", quake.url, use_container_width=True)


def _render_community(snapshot: CitySnapshot, provider_mode: str) -> None:
    st.markdown('<p class="section-eyebrow">COMMUNITY / VERIFIED LOCAL CONTRIBUTIONS</p>', unsafe_allow_html=True)
    st.subheader("Community")
    if provider_mode == "demo":
        st.warning("DEMO DATA | the entries below are illustrative fixtures, not real notices or events.")
        st.caption("Switch to Live City Feeds to see only verified provider data.")
        if not snapshot.alerts and not snapshot.events:
            st.info("This demo has no community fixtures.")
            return
        for alert in snapshot.alerts:
            st.markdown(f"**DEMO | {alert.severity.upper()} | {alert.title}**")
            st.caption(alert.source)
        for event in snapshot.events:
            st.markdown(f"**DEMO | {event.title}**")
            st.caption(f"{event.venue} | {event.starts_at:%b %d, %H:%M}")
        return
    st.info("No verified live data available for this area.")
    st.caption("Community-submitted posts are not connected. No sample notices are shown in Live mode.")

def _render_neighborhood_alerts(snapshot: CitySnapshot, provider_mode: str) -> None:
    st.caption(
        "Rule-based signals generated from live local news, Open-Meteo weather and air quality, "
        "and USGS earthquakes. These are informational signals, not official emergency warnings."
    )
    if provider_mode != "live":
        st.info("DEMO DATA is excluded from CityPulse generated neighborhood alerts.")
        return

    feeds = ("News", "Weather", "Air quality", "Earthquakes")
    unavailable = [
        label for label in feeds if not snapshot.sources.get(label, "").startswith("Live:")
    ]
    if not snapshot.neighborhood_alerts:
        if len(unavailable) == len(feeds):
            st.warning("No live alert signals are available right now. Check Data Sources for feed health.")
        elif unavailable:
            st.info(
                "No signal crossed the alert thresholds in available feeds. "
                f"Unavailable feeds: {', '.join(unavailable)}."
            )
        else:
            st.success("No live signals crossed CityPulse's informational alert thresholds.")
        return

    st.caption(f"{len(snapshot.neighborhood_alerts)} CityPulse generated signal(s), ordered by severity and recency.")
    if unavailable:
        st.warning(f"Some feeds are unavailable: {', '.join(unavailable)}.")
    for alert in snapshot.neighborhood_alerts:
        with st.container(border=True):
            st.markdown(f"**{alert.severity.upper()} | {alert.title}**")
            local_time = alert.event_at.astimezone(city_timezone(snapshot.city.timezone))
            category = alert.category.replace("_", " ").title()
            st.caption(f"{category} | {alert.source} | {local_time:%b %d, %H:%M %Z}")
            st.write(alert.description)
            if alert.url:
                st.link_button("Open source ?", alert.url, use_container_width=True)


def _render_sources(snapshot: CitySnapshot, provider_mode: str) -> None:
    settings = get_settings()
    secrets_configured = {
        "News": bool(settings.gnews_api_key and settings.gnews_api_key.get_secret_value().strip()),
        "Weather warnings": bool(settings.imd_api_key and settings.imd_api_key.get_secret_value().strip()),
        "Events": bool(settings.ticketmaster_api_key and settings.ticketmaster_api_key.get_secret_value().strip()),
    }
    rows = feed_health_rows(live_enabled=provider_mode == "live", configured=secrets_configured)
    current_status = snapshot.sources
    for row in rows:
        feed_name = next(
            (definition.feed for definition in SOURCE_REGISTRY if definition.provider == row["Source"]),
            "",
        )
        if feed_name and feed_name in current_status:
            row["Current snapshot"] = current_status[feed_name]
    st.markdown('<p class="section-eyebrow">PROVIDER HEALTH / FRESHNESS / CONFIGURATION</p>', unsafe_allow_html=True)
    st.subheader("Data sources")
    st.caption("Configuration shows whether a source needs credentials. Credential values are never displayed.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.markdown("#### Data timestamps")
    freshness: list[tuple[str, datetime | None]] = [
        ("Weather observation", snapshot.weather.observed_at if snapshot.weather else None),
        ("Air-quality observation", snapshot.air_quality.observed_at if snapshot.air_quality else None),
    ]
    for label, observed_at in freshness:
        st.caption(f"{label}: {observed_at:%Y-%m-%d %H:%M %Z}" if observed_at else f"{label}: Live data unavailable")
    for label in ("News", "Nearby places", "Earthquakes", "Civic alerts", "Events", "Weather warnings", "Community"):
        st.caption(f"{label}: {snapshot.sources.get(label, 'No verified provider status')}")
    st.markdown(
        "SACHET civic alerts use the public India RSS feed and linked CAP records. IMD access requires registration "
        "and an issued API credential; the documented endpoint is currently not available in this environment. Events are queried from Ticketmaster "
        "only when its key is configured; its India listings are not comprehensive."
    )
    st.markdown(
        "[SACHET / NDMA](https://sachet.ndma.gov.in/) | "
        "[IMD API Management](https://api.imd.gov.in/public/index.php) | "
        "[Open-Meteo](https://open-meteo.com/) | "
        "[GNews](https://docs.gnews.io/endpoints/search-endpoint) | "
        "[Ticketmaster Discovery API](https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/) | "
        "[USGS earthquakes](https://earthquake.usgs.gov/fdsnws/event/1/) | "
        "[OpenStreetMap](https://www.openstreetmap.org/copyright)"
    )


def _render_dashboard_content(
    provider_mode: str,
    city: City,
    places_radius: int,
    earthquake_radius: float,
    timeout_seconds: float,
) -> None:
    toolbar_left, toolbar_right = st.columns((6, 1))
    with toolbar_left:
        st.markdown(
            f"<p class='data-note'>Centered at {city.latitude:.4f}, {city.longitude:.4f} | "
            f"{places_radius} km place scan | {earthquake_radius:.0f} km hazard scan</p>",
            unsafe_allow_html=True,
        )
    with toolbar_right:
        if st.button("Refresh", use_container_width=True, help="Rebuild using the provider cache windows"):
            load_snapshot.clear()
            st.rerun()

    with st.spinner("Refreshing available city feeds?"):
        snapshot = load_snapshot(
            provider_mode,
            city.name,
            city.state,
            city.latitude,
            city.longitude,
            city.timezone,
            city.country,
            city.country_code,
            timeout_seconds,
            places_radius,
            earthquake_radius,
        )

    _render_hero(city, provider_mode, snapshot)
    if provider_mode == "demo":
        st.warning("DEMO DATA | all fixture content is illustrative and must not be used for safety decisions.")
    for warning in snapshot.warnings:
        st.warning(warning)

    weather = snapshot.weather
    air = snapshot.air_quality
    metrics = st.columns(4)
    metrics[0].metric(
        "Current temperature",
        f"{weather.temperature_c:.1f} deg C" if weather else "Unavailable",
        f"Feels like {weather.feels_like_c:.1f} deg C" if weather else snapshot.sources.get("Weather", ""),
    )
    metrics[1].metric(
        "Air quality | US AQI",
        f"{air.us_aqi:.0f}" if air else "Unavailable",
        _aqi_status(air.us_aqi)[0] if air else snapshot.sources.get("Air quality", ""),
    )
    places_source = snapshot.sources.get("Nearby places", "")
    metrics[2].metric(
        "Mapped nearby places",
        str(len(snapshot.places)) if places_source.startswith("Live:") else "Unavailable",
        f"within {places_radius} km" if places_source.startswith("Live:") else "feed unavailable",
    )
    quake_source = snapshot.sources.get("Earthquakes", "")
    metrics[3].metric(
        "Recent earthquakes",
        str(len(snapshot.earthquakes)) if quake_source.startswith("Live:") else "Unavailable",
        f"within {earthquake_radius:.0f} km" if quake_source.startswith("Live:") else "feed unavailable",
    )
    notes: list[str] = []
    if air:
        aqi_label, aqi_color = _aqi_status(air.us_aqi)
        notes.append(
            f"AQI band: <span style='color:{aqi_color};font-weight:700'>{aqi_label}</span> | "
            f"PM2.5 {air.pm2_5_ug_m3:.1f} ug/m3 | PM10 {air.pm10_ug_m3:.1f} ug/m3"
        )
    if weather:
        notes.append(f"Wind {weather.wind_speed_kmh:.0f} km/h")
    if notes:
        st.markdown(f"<p class='data-note'>{' | '.join(notes)}</p>", unsafe_allow_html=True)
    st.caption(f"Snapshot assembled {snapshot.generated_at:%Y-%m-%d %H:%M:%S %Z}")

    map_tab, weather_tab, news_tab, civic_tab, events_tab, nearby_tab, community_tab, sources_tab = st.tabs(
        ("CITY MAP", "WEATHER & AIR", "LIVE NEWS", "CIVIC ALERTS", "EVENTS", "NEARBY & HAZARDS", "COMMUNITY", "DATA SOURCES")
    )
    with map_tab:
        _render_city_map(snapshot)
    with weather_tab:
        _render_weather_and_air(snapshot)
    with news_tab:
        _render_news(snapshot)
    with civic_tab:
        _render_civic_alerts(snapshot, provider_mode)
    with events_tab:
        _render_events(snapshot, provider_mode)
    with nearby_tab:
        places_column, hazard_column = st.columns((1.15, 1), gap="large")
        with places_column:
            _render_nearby_places(snapshot)
        with hazard_column:
            _render_earthquakes(snapshot)
    with community_tab:
        _render_community(snapshot, provider_mode)
    with sources_tab:
        _render_sources(snapshot, provider_mode)

def run_dashboard() -> None:
    """Render CityPulse and optionally refresh its content in the background."""

    st.set_page_config(
        page_title="CityPulse | Live city intelligence",
        page_icon="🌆",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_theme()
    settings = get_settings()
    provider_mode, city, places_radius, earthquake_radius, refresh_interval = _render_sidebar(settings)
    dashboard_fragment = st.fragment(run_every=refresh_interval)(_render_dashboard_content)
    dashboard_fragment(
        provider_mode,
        city,
        places_radius,
        earthquake_radius,
        settings.request_timeout_seconds,
    )
