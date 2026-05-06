"""
Symbol Brain — persistent scoring and watchlist management.

Aggregates signals from multiple sources (news mentions, LLM decisions,
price momentum, trade history, and the lightweight brain scanner) into a
per-symbol interest score.
Persists between runs so the bot accumulates knowledge without re-analyzing
every symbol from scratch each cycle.

Score formula (0–1, time-decayed):
  25 % news activity     — genuinely new articles raise interest
  15 % price momentum    — any strong movement is tradeable
  10 % volume spike      — unusual volume flags activity
  20 % LLM (engine)      — full BUY/SELL decisions from trading engine
  20 % scanner           — lightweight BrainScanner signal (separate decay)
  10 % trade-history     — win-rate + avg-return from SymbolLearner

Brain file: data/symbol_brain.json  (atomic write via .tmp → rename)
Thread-safe: all public methods protected by a threading.Lock.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("777moneymaker")

_DEFAULT_WATCHLIST_SIZE = 30
_DEFAULT_DECAY_HOURS    = 48
_DEFAULT_MIN_SCORE      = 0.05


class SymbolBrain:

    def __init__(self, config: dict):
        brain_cfg = config.get("brain", {})
        data_dir  = Path(config.get("data", {}).get("data_dir", "data"))
        data_dir.mkdir(parents=True, exist_ok=True)

        self._path           = data_dir / "symbol_brain.json"
        self._watchlist_size = brain_cfg.get("watchlist_size", _DEFAULT_WATCHLIST_SIZE)
        self._min_score      = brain_cfg.get("min_score",      _DEFAULT_MIN_SCORE)
        self._decay_hours    = brain_cfg.get("score_decay_hours", _DEFAULT_DECAY_HOURS)
        self._always_analyze = set(brain_cfg.get("always_analyze", []))
        self._seed_universe  = set(brain_cfg.get("seed_universe",  []))
        self._config_symbols = set(config.get("symbols", []))
        self._lock           = threading.Lock()

        self._data: dict[str, dict] = {}
        self._load()

        for sym in self._seed_universe | self._config_symbols | self._always_analyze:
            self._ensure(sym)

    # ── Public API ──────────────────────────────────────────────────────────

    def update_from_news(self, news: list[dict]) -> int:
        """
        Extract company tickers from a news batch and update their news_hits.
        Only articles with a timestamp newer than the symbol's last recorded
        news_last_ts are counted — repeated fetches of old articles are ignored.
        Returns the number of NEW symbols discovered this call.
        """
        from collections import Counter
        new_hits: Counter         = Counter()
        latest_ts: dict[str, int] = {}

        with self._lock:
            for item in news:
                sym = item.get("symbol", "")
                if not sym or sym == "MARKET":
                    continue
                ts = item.get("timestamp", 0)
                known_ts = self._data.get(sym, {}).get("news_last_ts", 0)
                if ts > known_ts:
                    new_hits[sym] += 1
                    if ts > latest_ts.get(sym, 0):
                        latest_ts[sym] = ts

            new_symbols = 0
            now_iso = _now_iso()
            for sym, count in new_hits.items():
                is_new = sym not in self._data
                entry  = self._ensure(sym)
                if is_new:
                    new_symbols += 1
                # Accumulate hits (capped at 20); time-decay in _compute_score handles fading
                entry["news_hits"]    = min(entry.get("news_hits", 0.0) + count, 20.0)
                entry["news_last_ts"] = max(latest_ts.get(sym, 0), entry.get("news_last_ts", 0))
                entry["last_activity"] = now_iso

            if new_hits:
                self._recompute_scores()
                self._save()

        return new_symbols

    def update_from_snapshot(self, symbol: str, snapshot: dict):
        """Records momentum and volume_ratio from a freshly fetched market snapshot."""
        with self._lock:
            entry = self._ensure(symbol)
            try:
                entry["momentum_pct"] = snapshot["price"].get("change_pct", 0.0)
                vr = snapshot.get("indicators", {}).get("volume_ratio")
                if vr is not None:
                    entry["volume_ratio"] = float(vr)
            except Exception:
                pass
            entry["last_activity"] = _now_iso()
            self._recompute_score(symbol)

    def update_from_snapshot_fast(self, symbol: str, snapshot: dict):
        """Like update_from_snapshot but without disk save — use save() afterwards for bulk ops."""
        with self._lock:
            entry = self._ensure(symbol)
            try:
                entry["momentum_pct"] = snapshot["price"].get("change_pct", 0.0)
                ind = snapshot.get("indicators", {})
                vr = ind.get("volume_ratio")
                if vr is not None:
                    entry["volume_ratio"] = float(vr)
                # Zapamiętaj vol_sma20 z pełnego skanu — użyjemy w hourly refresh
                vsma = ind.get("vol_sma20")
                if vsma is not None:
                    entry["vol_sma20"] = float(vsma)
            except Exception:
                pass
            entry["last_activity"] = _now_iso()
            if entry.get("first_scan_ts") is None:
                entry["first_scan_ts"] = _now_iso()
            self._recompute_score(symbol)

    def update_from_ticker_fast(self, symbol: str, change_pct: float, volume: int):
        """
        Lekka aktualizacja co godzinę: tylko momentum i volume_ratio z batch snapshot.
        Używa zapamiętanego vol_sma20 z ostatniego pełnego skanu. Bez zapisu na dysk.
        Pomija symbole nieznane brainowi (nie dodaje nowych).
        """
        with self._lock:
            entry = self._data.get(symbol)
            if entry is None:
                return
            entry["momentum_pct"] = float(change_pct)
            vol_sma20 = entry.get("vol_sma20")
            if vol_sma20 and float(vol_sma20) > 0:
                entry["volume_ratio"] = round(float(volume) / float(vol_sma20), 2)
            entry["last_activity"] = _now_iso()
            self._recompute_score(symbol)

    def save(self):
        """Public save — call after bulk update_from_snapshot_fast calls.
        Copies data under lock, then writes outside lock to avoid blocking readers."""
        with self._lock:
            data_snapshot = {k: dict(v) for k, v in self._data.items()}
        try:
            tmp = self._path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data_snapshot, f, ensure_ascii=False, separators=(',', ':'))
            tmp.replace(self._path)
        except Exception as exc:
            logger.debug(f"SymbolBrain save failed: {exc}")

    def mark_analyzed(
        self,
        symbol: str,
        decision: dict,
        learner_profile: Optional[dict] = None,
    ):
        """Records the outcome of a full LLM analysis cycle."""
        with self._lock:
            entry = self._ensure(symbol)
            action = decision.get("action", "HOLD")
            conf   = float(decision.get("confidence", 0.0) or 0.0)

            entry["llm_action"]     = action
            entry["llm_confidence"] = conf
            entry["llm_ts"]         = _now_iso()
            entry["last_activity"]  = _now_iso()
            entry["analyze_count"]  = entry.get("analyze_count", 0) + 1

            if learner_profile:
                wr = learner_profile.get("win_rate")
                n  = learner_profile.get("closed_trades", 0)
                ar = learner_profile.get("avg_return_pct")
                if wr is not None and n >= 3:
                    wr_bonus = max(0.0, (wr - 0.40) / 0.60)
                    ar_bonus = min(max(0.0, (ar or 0.0) / 3.0), 1.0)
                    entry["learner_bonus"] = round(wr_bonus * 0.6 + ar_bonus * 0.4, 4)

            self._recompute_score(symbol)
            self._save()

    def get_watchlist(self, open_symbols: Optional[set[str]] = None) -> list[str]:
        """
        Returns the ordered symbol list for the current cycle.

        Priority:
          1. Open positions   — must always be managed for exits / SL-TP
          2. Config symbols + always_analyze — user-defined universe (always included)
          3. Brain-scored candidates filling remaining slots (score >= min_score, desc)
        """
        with self._lock:
            always = set()
            if open_symbols:
                always |= open_symbols
            always |= self._config_symbols
            always |= self._always_analyze

            for sym in always:
                self._ensure(sym)

            remaining = max(0, self._watchlist_size - len(always))
            candidates = sorted(
                [
                    (sym, entry.get("score", 0.0))
                    for sym, entry in self._data.items()
                    if sym not in always and entry.get("score", 0.0) >= self._min_score
                ],
                key=lambda x: x[1],
                reverse=True,
            )
            scored_extra = [sym for sym, _ in candidates[:remaining]]

            open_list   = sorted(open_symbols or [])
            config_list = sorted((self._config_symbols | self._always_analyze) - set(open_list))
            result: list[str] = []
            for sym in open_list + config_list + scored_extra:
                if sym not in result:
                    result.append(sym)

            return result

    def reload(self):
        """Re-read brain file from disk (safe to call from any thread)."""
        with self._lock:
            self._load()
            self._recompute_scores()

    def top_scored(self, n: int = 20) -> list[tuple[str, float]]:
        """Top N (symbol, score) pairs — useful for logging."""
        with self._lock:
            pairs = sorted(
                self._data.items(),
                key=lambda x: x[1].get("score", 0.0),
                reverse=True,
            )
            return [(sym, entry.get("score", 0.0)) for sym, entry in pairs[:n]]

    def mark_first_scanned(self, symbol: str):
        """Sets first_scan_ts the first time BrainScanner processes this symbol."""
        with self._lock:
            entry = self._ensure(symbol)
            if entry.get("first_scan_ts") is None:
                entry["first_scan_ts"] = _now_iso()
                self._save()

    def has_been_scanned(self, symbol: str) -> bool:
        """Returns True if the symbol has been scanned by BrainScanner at least once."""
        with self._lock:
            return self._data.get(symbol, {}).get("first_scan_ts") is not None

    def update_from_scanner(self, symbol: str, decision: dict):
        """
        Records a lightweight BrainScanner decision.
        Uses separate scanner_* fields so the trading engine's full LLM
        decisions are never overwritten by the scanner.
        """
        with self._lock:
            entry = self._ensure(symbol)
            action = str(decision.get("action", "HOLD")).upper()
            conf   = float(decision.get("confidence", 0.0) or 0.0)

            entry["scanner_action"]     = action
            entry["scanner_confidence"] = conf
            entry["scanner_ts"]         = _now_iso()
            entry["last_activity"]      = _now_iso()

            self._recompute_score(symbol)
            self._save()

    def all_symbols(self) -> list[str]:
        """Returns list of all symbols currently tracked in the brain (thread-safe)."""
        with self._lock:
            return list(self._data.keys())

    def prune(self, keep_symbols: set, max_size: int) -> int:
        """Removes low-scoring symbols to keep memory and file size bounded.
        Always keeps symbols in keep_symbols (static universe + open positions).
        Returns count of removed symbols."""
        with self._lock:
            if len(self._data) <= max_size:
                return 0
            sorted_syms = sorted(
                self._data.keys(),
                key=lambda s: self._data[s].get("score", 0.0),
                reverse=True,
            )
            to_keep: set[str] = set()
            for sym in sorted_syms:
                if sym in keep_symbols or len(to_keep) < max_size:
                    to_keep.add(sym)
            to_remove = set(self._data.keys()) - to_keep
            for sym in to_remove:
                del self._data[sym]
            if to_remove:
                self._save()
                logger.info(
                    f"SymbolBrain pruned: removed {len(to_remove)}, "
                    f"kept {len(self._data)}"
                )
            return len(to_remove)

    def get_entry(self, symbol: str) -> Optional[dict]:
        with self._lock:
            return self._data.get(symbol)

    def symbol_count(self) -> int:
        with self._lock:
            return len(self._data)

    # ── Score computation ─────────────────────────────────────────────────────

    def _recompute_score(self, symbol: str):
        entry = self._data.get(symbol)
        if entry is not None:
            entry["score"] = self._compute_score(entry)

    def _recompute_scores(self):
        for sym in self._data:
            self._recompute_score(sym)

    def _compute_score(self, entry: dict) -> float:
        news_score     = min(float(entry.get("news_hits", 0.0)) / 5.0, 1.0)
        momentum_score = min(abs(float(entry.get("momentum_pct", 0.0))) / 5.0, 1.0)
        vr             = float(entry.get("volume_ratio", 1.0) or 1.0)
        volume_score   = min(max(vr - 1.0, 0.0) / 2.0, 1.0)

        # Trading engine full-analysis signal
        action    = entry.get("llm_action") or "HOLD"
        conf      = float(entry.get("llm_confidence", 0.0) or 0.0)
        llm_score = conf if action in ("BUY", "SELL") else conf * 0.2

        # BrainScanner lightweight signal — decays independently from its own timestamp
        sc_action = entry.get("scanner_action") or "HOLD"
        sc_conf   = float(entry.get("scanner_confidence", 0.0) or 0.0)
        sc_raw    = sc_conf if sc_action in ("BUY", "SELL") else sc_conf * 0.2
        sc_ts     = entry.get("scanner_ts")
        if sc_ts:
            try:
                sc_dt       = datetime.fromisoformat(sc_ts)
                sc_hours    = (datetime.utcnow() - sc_dt).total_seconds() / 3600.0
                sc_decay    = max(0.0, 1.0 - sc_hours / (self._decay_hours * 2))
            except Exception:
                sc_decay = 0.3
        else:
            sc_decay = 0.0
        scanner_score = sc_raw * sc_decay

        learner_bonus = float(entry.get("learner_bonus", 0.0) or 0.0)

        # Global time-decay (based on last_activity)
        last_activity = entry.get("last_activity")
        if last_activity:
            try:
                last_dt     = datetime.fromisoformat(last_activity)
                hours_since = (datetime.utcnow() - last_dt).total_seconds() / 3600.0
                decay       = max(0.0, 1.0 - hours_since / self._decay_hours)
            except Exception:
                decay = 0.5
        else:
            decay = 0.5

        raw = (
            news_score     * 0.25 +
            momentum_score * 0.15 +
            volume_score   * 0.10 +
            llm_score      * 0.20 +
            scanner_score  * 0.20 +
            learner_bonus  * 0.10
        )
        return round(raw * decay, 4)

    # ── Entry management ──────────────────────────────────────────────────────

    def _ensure(self, symbol: str) -> dict:
        if symbol not in self._data:
            self._data[symbol] = {
                "score":              0.0,
                "news_hits":          0.0,
                "news_last_ts":       0,
                "momentum_pct":       0.0,
                "volume_ratio":       1.0,
                "vol_sma20":          None,  # zapamiętana z pełnego skanu, używana w hourly refresh
                "llm_action":         None,
                "llm_confidence":     0.0,
                "llm_ts":             None,
                "scanner_action":     None,
                "scanner_confidence": 0.0,
                "scanner_ts":         None,
                "learner_bonus":      0.0,
                "first_scan_ts":      None,
                "first_seen":         _now_iso(),
                "last_activity":      _now_iso(),
                "analyze_count":      0,
            }
        return self._data[symbol]

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self):
        try:
            tmp = self._path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, separators=(',', ':'))
            tmp.replace(self._path)
        except Exception as exc:
            logger.debug(f"SymbolBrain save failed: {exc}")

    def _load(self):
        if not self._path.exists():
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self._data = raw
                logger.info(
                    f"SymbolBrain loaded: {len(self._data)} symbols tracked "
                    f"({self._path.name})"
                )
        except Exception as exc:
            logger.warning(f"SymbolBrain load failed, starting fresh: {exc}")
            self._data = {}


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")
