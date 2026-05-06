"""
Klient Finnhub API — pobiera newsy rynkowe i spółkowe.
Pobiera też pełną treść artykułów (jeśli dostępna) dla LLM.
Dokumentacja: https://finnhub.io/docs/api
"""

from __future__ import annotations

import html
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import date, timedelta, datetime
from typing import Optional

import requests

logger = logging.getLogger("777moneymaker")

BASE_URL  = "https://finnhub.io/api/v1"
_HEADERS  = {"User-Agent": "Mozilla/5.0 (compatible; 777moneymaker/1.0)"}
_FETCH_TIMEOUT   = 8    # seconds per article HTTP request
_CONTENT_WORKERS = 8    # parallel article fetches
_CONTENT_MAX     = 2000  # max chars of article content to keep


class FinnhubClient:

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.getenv("FINNHUB_API_KEY", "")

    def is_available(self) -> bool:
        if not self._api_key:
            return False
        try:
            r = requests.get(
                f"{BASE_URL}/news",
                params={"category": "general", "token": self._api_key},
                timeout=5,
            )
            return r.status_code == 200
        except Exception:
            return False

    # ── Public news API ───────────────────────────────────────────────────

    def get_company_news(self, symbol: str, days_back: int = 3) -> list[dict]:
        """Newsy dla konkretnej spółki z ostatnich N dni, z pełną treścią artykułów."""
        if not self._api_key:
            return []
        today     = date.today()
        from_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
        to_date   = today.strftime("%Y-%m-%d")
        try:
            r = requests.get(
                f"{BASE_URL}/company-news",
                params={"symbol": symbol, "from": from_date, "to": to_date,
                        "token": self._api_key},
                timeout=10,
            )
            r.raise_for_status()
            items = r.json()
            if not isinstance(items, list):
                return []
            normalized = self._normalize(items[:15], symbol)
            return self._enrich_content(normalized)
        except Exception as exc:
            logger.debug(f"Finnhub company-news {symbol}: {exc}")
            return []

    def get_market_news(self, category: str = "general", count: int = 30) -> list[dict]:
        """Ogólne newsy rynkowe z pełną treścią artykułów."""
        if not self._api_key:
            return []
        try:
            r = requests.get(
                f"{BASE_URL}/news",
                params={"category": category, "token": self._api_key},
                timeout=10,
            )
            r.raise_for_status()
            items = r.json()
            if not isinstance(items, list):
                return []
            normalized = self._normalize(items[:count], "MARKET")
            return self._enrich_content(normalized)
        except Exception as exc:
            logger.debug(f"Finnhub market-news: {exc}")
            return []

    def get_all_news(self, symbols: list[str], count_market: int = 50) -> list[dict]:
        """
        Pobiera wszystkie kategorie newsów — rynek ogólny + forex + crypto
        + newsy spółkowe dla każdego symbolu z listy.
        Zwraca połączoną, posortowaną listę (bez duplikatów).
        """
        seen_urls: set[str] = set()
        result: list[dict] = []

        def _add(items: list[dict]):
            for item in items:
                url = item.get("url", "")
                key = url or item.get("headline", "")
                if key and key not in seen_urls:
                    seen_urls.add(key)
                    result.append(item)

        # Categories
        for cat in ("general", "forex", "merger"):
            _add(self.get_market_news(category=cat, count=count_market))

        # Company-specific
        for sym in symbols:
            _add(self.get_company_news(sym, days_back=3))

        # Sort newest-first by timestamp
        result.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return result

    # ── Article content enrichment ────────────────────────────────────────

    def _enrich_content(self, items: list[dict]) -> list[dict]:
        """
        Fetches full article text for each item in parallel.
        Items without a URL or where fetch fails keep content="".
        """
        urls = [item.get("url", "") for item in items]
        if not any(urls):
            return items

        futures_map: dict = {}
        with ThreadPoolExecutor(max_workers=_CONTENT_WORKERS) as pool:
            for idx, url in enumerate(urls):
                if url:
                    futures_map[pool.submit(self._fetch_article_content, url)] = idx

            for future in as_completed(futures_map, timeout=_FETCH_TIMEOUT + 2):
                idx = futures_map[future]
                try:
                    content = future.result(timeout=1)
                    items[idx]["content"] = content
                except Exception:
                    items[idx]["content"] = ""

        # Fill blanks for items that had no URL or timed out
        for item in items:
            if "content" not in item:
                item["content"] = ""

        return items

    @staticmethod
    def _fetch_article_content(url: str) -> str:
        """Fetch and extract plain text from an article URL."""
        if not url:
            return ""
        try:
            r = requests.get(url, timeout=_FETCH_TIMEOUT, headers=_HEADERS)
            r.raise_for_status()

            # Try trafilatura (best quality)
            try:
                import trafilatura
                text = trafilatura.extract(r.text, include_comments=False,
                                           include_tables=False)
                if text and len(text) > 50:
                    return text[:_CONTENT_MAX].strip()
            except ImportError:
                pass

            # Fallback: strip HTML tags
            text = re.sub(r"<script[^>]*>.*?</script>", " ", r.text,
                          flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<style[^>]*>.*?</style>", " ", text,
                          flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            text = html.unescape(text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:_CONTENT_MAX]
        except Exception:
            return ""

    # ── Internal normalization ────────────────────────────────────────────

    @staticmethod
    def _normalize(items: list, default_symbol: str) -> list[dict]:
        result = []
        for item in items:
            ts = item.get("datetime", 0)
            try:
                dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            except Exception:
                dt = "—"
            result.append({
                "symbol":    item.get("related") or default_symbol,
                "headline":  item.get("headline", ""),
                "summary":   item.get("summary", ""),
                "content":   "",          # filled by _enrich_content
                "source":    item.get("source", ""),
                "url":       item.get("url", ""),
                "datetime":  dt,
                "timestamp": ts,
            })
        return result

    def format_for_llm(self, news: list[dict], max_items: int = 5) -> str:
        """Formatuje newsy do wklejenia w prompt LLM."""
        if not news:
            return "No recent news available."
        lines = []
        for item in news[:max_items]:
            summary = item.get("content") or item.get("summary", "")
            summary = summary[:300].strip()
            headline = item["headline"]
            if summary and summary[:40] != headline[:40]:
                lines.append(
                    f"• [{item['datetime']}] {headline} ({item['source']})\n"
                    f"  {summary}"
                )
            else:
                lines.append(
                    f"• [{item['datetime']}] {headline} ({item['source']})"
                )
        return "\n".join(lines)
