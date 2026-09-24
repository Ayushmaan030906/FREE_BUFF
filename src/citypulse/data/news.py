"""News provider contract and GNews implementation."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from time import monotonic, sleep
from typing import Protocol

import httpx

from citypulse.data.feed_health import track_feed_refresh
from citypulse.domain.models import NewsStory

GNEWS_URL = "https://gnews.io/api/v4/search"
_REQUEST_LOCK = Lock()
_LAST_REQUEST_AT = 0.0


class NewsProvider(Protocol):
    """Backend contract for interchangeable news search providers."""

    def search(
        self,
        city_name: str,
        country: str,
        country_code: str,
        api_key: str,
        timeout_seconds: float,
    ) -> list[NewsStory]: ...


class GNewsProvider:
    """Search GNews from the Python server; API credentials never reach the UI."""

    @track_feed_refresh("News")
    def search(
        self,
        city_name: str,
        country: str,
        country_code: str,
        api_key: str,
        timeout_seconds: float,
    ) -> list[NewsStory]:
        global _LAST_REQUEST_AT
        with _REQUEST_LOCK:
            delay = 1.0 - (monotonic() - _LAST_REQUEST_AT)
            if delay > 0:
                sleep(delay)
            _LAST_REQUEST_AT = monotonic()
        query = f'"{city_name}" "{country}"' if country else f'"{city_name}"'
        params: dict[str, object] = {
            "q": query[:200],
            "max": 10,
            "sortby": "publishedAt",
            "apikey": api_key,
            "nullable": "description,image",
        }
        if len(country_code) == 2:
            params["country"] = country_code.lower()
        with httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "CityPulse/0.2 (local city dashboard)"},
        ) as client:
            response = None
            for attempt in range(3):
                response = client.get(GNEWS_URL, params=params)
                if response.status_code not in {429, 500, 502, 503, 504} or attempt == 2:
                    break
                sleep(0.5 * (2**attempt))
            assert response is not None
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("GNews returned an unexpected response.")
        stories: list[NewsStory] = []
        for article in payload.get("articles", []):
            if not isinstance(article, dict):
                continue
            url = str(article.get("url") or "")
            title = str(article.get("title") or "").strip()
            if not title or not url.startswith(("http://", "https://")):
                continue
            raw_date = str(article.get("publishedAt") or "")
            try:
                published_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=UTC)
            except ValueError:
                continue
            image = str(article.get("image") or "")
            source = article.get("source", {})
            source_name = str(source.get("name") or "") if isinstance(source, dict) else ""
            stories.append(
                NewsStory(
                    title=title,
                    url=url,
                    source_domain=source_name or "News source",
                    published_at=published_at,
                    language=str(article.get("lang") or ""),
                    image_url=image if image.startswith(("http://", "https://")) else None,
                    description=str(article.get("description") or "").strip(),
                    city=city_name,
                    state="",
                    last_updated_at=datetime.now(UTC),
                )
            )
        return stories
