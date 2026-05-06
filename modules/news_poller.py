"""
Background news poller — auto-fetches market and company news every 60 seconds.
Uses FinnhubClient.get_all_news() to pull general, forex, merger and per-symbol
company news in one pass (with full article content).
Saves everything to NewsStore and updates SymbolBrain with newly discovered tickers.
Emits news_updated(int) when new articles arrive.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

if TYPE_CHECKING:
    from modules.symbol_brain import SymbolBrain

logger = logging.getLogger("777moneymaker")

_INTERVAL = 60  # seconds between fetch cycles


class NewsPoller(QThread):
    news_updated = Signal(int)   # number of new articles saved this cycle

    def __init__(
        self,
        config: dict,
        brain: Optional["SymbolBrain"] = None,
        journal=None,
        parent=None,
    ):
        super().__init__(parent)
        self._config      = config
        self._brain       = brain
        self._journal     = journal
        self._stop_event  = threading.Event()

    # ── QThread lifecycle ─────────────────────────────────────────────────────

    def run(self):
        logger.info(f"NewsPoller started — auto-fetch every {_INTERVAL}s")
        self._fetch_cycle()
        while not self._stop_event.wait(_INTERVAL):
            self._fetch_cycle()
        logger.info("NewsPoller stopped")

    def stop(self):
        self._stop_event.set()

    def force_refresh(self):
        """Trigger an out-of-band fetch without resetting the main timer."""
        threading.Thread(target=self._fetch_cycle, daemon=True).start()

    # ── Fetch logic ───────────────────────────────────────────────────────────

    def _fetch_cycle(self):
        api_key = os.getenv("FINNHUB_API_KEY", "")
        if not api_key:
            logger.debug("NewsPoller: FINNHUB_API_KEY not set — skipping")
            return
        try:
            from modules.finnhub_client import FinnhubClient
            from modules.news_store import NewsStore

            # Build expanded symbol list:
            # 1. TradeBot watchlist (open positions + scored symbols)
            # 2. BrainBot recommended + watch_later (what BrainBot is tracking)
            symbols: set[str] = set()
            if self._brain:
                symbols.update(self._brain.get_watchlist())
            if self._journal:
                symbols.update(self._journal.get_recommended_symbols())
                symbols.update(
                    entry["symbol"]
                    for entry in self._journal.get_watch_later()[:50]
                )
            if not symbols:
                symbols = set(self._config.get("symbols", []))
            symbols = sorted(symbols)[:150]  # cap: stay within Finnhub rate limits

            client = FinnhubClient(api_key)
            store  = NewsStore(self._config)

            items = client.get_all_news(symbols, count_market=50)
            saved = store.save(items)

            if saved > 0:
                logger.info(
                    f"NewsPoller: +{saved} new articles ({len(items)} fetched, "
                    f"{len(symbols)} symbols)"
                )
                # Update brain only when there are genuinely new articles
                if self._brain and items:
                    new_syms = self._brain.update_from_news(items)
                    if new_syms > 0:
                        logger.info(
                            f"NewsPoller → SymbolBrain: {new_syms} new symbol(s) discovered"
                        )
                self.news_updated.emit(saved)
            else:
                logger.debug(f"NewsPoller: no new articles ({len(items)} checked)")
        except Exception as exc:
            logger.debug(f"NewsPoller error: {exc}")
