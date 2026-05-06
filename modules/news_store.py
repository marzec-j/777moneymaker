"""
Przechowuje newsy z Finnhub w data/news.jsonl.
Każda linia to jeden artykuł w formacie JSON.
Umożliwia filtrowanie po symbolu i zakresie dat.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("777moneymaker")


class NewsStore:

    def __init__(self, config: dict):
        data_cfg  = config.get("data", {})
        data_dir  = Path(data_cfg.get("data_dir", "data")).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        self._path = data_dir / data_cfg.get("news_file", "news.jsonl")

    # ── Write ─────────────────────────────────────────────────────────────

    def save(self, items: list[dict]) -> int:
        """Zapisuje nowe artykuły (dedup po headline+datetime). Zwraca liczbę zapisanych."""
        existing = {
            (r.get("headline", ""), r.get("datetime", ""))
            for r in self._load_all()
        }
        new_items = [
            i for i in items
            if (i.get("headline", ""), i.get("datetime", "")) not in existing
        ]
        if not new_items:
            return 0
        saved_at = datetime.utcnow().isoformat()
        with open(self._path, "a", encoding="utf-8") as f:
            for item in new_items:
                record = {**item, "saved_at": saved_at}
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.debug(f"NewsStore: zapisano {len(new_items)} nowych artykułów")
        return len(new_items)

    # ── Read ──────────────────────────────────────────────────────────────

    def query(
        self,
        symbol: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """
        Filtruje newsy.
        symbol:    np. 'AAPL' lub None (wszystkie)
        date_from: 'YYYY-MM-DD' (włącznie)
        date_to:   'YYYY-MM-DD' (włącznie)
        Zwraca posortowane od najnowszego.
        """
        items = self._load_all()

        if symbol:
            sym_up = symbol.upper()
            items = [
                i for i in items
                if sym_up in (i.get("symbol") or "").upper()
                or sym_up == "MARKET"
            ]

        if date_from:
            items = [i for i in items if i.get("datetime", "") >= date_from]
        if date_to:
            # date_to is YYYY-MM-DD, datetime field is 'YYYY-MM-DD HH:MM'
            items = [i for i in items if i.get("datetime", "")[:10] <= date_to]

        items.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return items[:limit]

    def symbols(self) -> list[str]:
        """Zwraca unikalne symbole zapisane w bazie newsów."""
        syms = set()
        for item in self._load_all():
            s = (item.get("symbol") or "").strip()
            if s and s != "MARKET":
                syms.add(s)
        return sorted(syms)

    # ── Internal ──────────────────────────────────────────────────────────

    def _load_all(self) -> list[dict]:
        if not self._path.exists():
            return []
        items: list[dict] = []
        try:
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            items.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except Exception as exc:
            logger.warning(f"NewsStore: błąd odczytu — {exc}")
        return items
