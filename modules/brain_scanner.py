"""
BrainScannerWorker — BrainBot: ciągły bot AI skanujący cały rynek.

Odpowiedzialności:
  - Pełny skan (szybki, bez LLM) wszystkich symboli — raz dziennie o północy,
    wyłania top N (domyślnie 1000) najlepiej ocenionych do regularnych skanów
  - Regularny skan (z LLM) co godzinę — tylko top 1000, szczegółowy
  - Zapisuje sygnały do SymbolBrain (scanner_action / confidence)
  - Prowadzi Dziennik (BrainJournal): rekomendacje dla TradeBota, obserwuj później
  - Uwzględnia otwarte pozycje — nie usuwa ich z rekomendacji niezależnie od score
  - Uczy się na błędach (po informacji o złej predykcji zapisuje notatkę)
  - Obsługuje czat z użytkownikiem (przez kolejkę wiadomości → LLM → odpowiedź)
"""

from __future__ import annotations

import json
import logging
import queue
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import requests
from PySide6.QtCore import QThread, Signal

from modules.brain_journal import BrainJournal

if TYPE_CHECKING:
    from modules.symbol_brain import SymbolBrain

logger = logging.getLogger("brainbot")

# Liczba równoległych wątków do pobierania danych podczas pełnego skanu
_FULL_SCAN_WORKERS = 8

# ── Prompts — skan ────────────────────────────────────────────────────────────

_SCAN_SYSTEM = """You are a rapid stock screener AI. Given brief market data, output a BUY/SELL/HOLD signal.
Output ONLY valid JSON — no text before or after:
{"action": "BUY"|"SELL"|"HOLD", "confidence": 0.0-1.0, "reasoning": "one sentence", "key_signals": ["s1","s2"], "news_impact": "bullish"|"bearish"|"neutral"}

Rules:
- BUY: strong uptrend + volume + positive momentum + bullish news
- SELL: strong downtrend + high volume + negative momentum + bearish news
- HOLD: mixed or unclear signals; when in doubt output HOLD with low confidence
- confidence < 0.5 → lean toward HOLD"""

_SCAN_USER = """Rapid scan: {symbol}
Price: ${price:.2f}  ({change_pct:+.2f}% today)
RSI(14): {rsi}  |  MACD: {macd_trend}  |  Volume: {vol_ratio:.1f}x avg
Trend: {trend}  |  BB: {bb_pos}
SMA20/50/200: {above_smas}
News headlines: {news_summary}

Output JSON only."""


class BrainScannerWorker(QThread):
    status_updated      = Signal(str)        # krótki status dla UI
    scan_completed      = Signal(int, int)   # (scanned, total)
    journal_updated     = Signal()           # po każdym odświeżeniu journala
    chat_response_ready = Signal(str)        # odpowiedź BrainBota na czat
    scan_log_entry      = Signal(str)        # pojedynczy wpis logu skanera

    def __init__(
        self,
        config: dict,
        brain: "SymbolBrain",
        journal: Optional[BrainJournal] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("BrainScannerWorker")

        self._config  = config
        self._brain   = brain
        self._journal = journal or BrainJournal(config)
        self._running = False
        self._chat_queue: queue.Queue = queue.Queue()

        data_dir = Path(config.get("data", {}).get("data_dir", "data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        self._full_checkpoint_path = data_dir / "scan_checkpoint.json"

        scanner_cfg = config.get("brain_scanner", {})
        self._enabled            = scanner_cfg.get("enabled", True)
        self._full_market_scan   = scanner_cfg.get("full_market_scan", False)
        self._recommend_min_conf = scanner_cfg.get("recommend_min_confidence", 0.55)
        self._top_universe_size  = scanner_cfg.get("top_universe_size", 1000)

        # Parametry pełnego skanu (tylko przy pierwszym uruchomieniu bez danych)
        self._full_batch_size  = scanner_cfg.get("full_scan_batch_size", 100)
        self._full_batch_delay = scanner_cfg.get("full_scan_batch_delay", 0.1)

        # Parametry regularnego skanu (LLM, co godzinę, tylko top N)
        self._batch_size        = scanner_cfg.get("batch_size", 8)
        self._batch_delay       = scanner_cfg.get("batch_delay_seconds", 4)
        self._regular_interval  = scanner_cfg.get("regular_scan_interval_hours", 1) * 3600
        self._top_llm_scan_size = scanner_cfg.get("top_llm_scan_size", 100)

        llm_cfg = config.get("llm", {})
        self._base_url = llm_cfg.get("base_url", "http://localhost:11434").rstrip("/")
        self._model    = llm_cfg.get("model", "mistral")
        self._timeout  = min(llm_cfg.get("timeout", 120), 60)

        brain_cfg = config.get("brain", {})
        base = (
            set(config.get("symbols", []))
            | set(brain_cfg.get("seed_universe", []))
            | set(scanner_cfg.get("universe", []))
        )

        universe_file = scanner_cfg.get("universe_file", "")
        if universe_file:
            try:
                path = Path(universe_file)
                if path.exists():
                    with open(path, encoding="utf-8") as f:
                        for line in f:
                            sym = line.strip().upper()
                            if sym and not sym.startswith("#"):
                                base.add(sym)
                    logger.info(f"BrainScanner: loaded universe file {path} ({len(base)} symbols)")
            except Exception as exc:
                logger.warning(f"BrainScanner: could not read universe_file: {exc}")

        self._static_universe: list[str] = sorted(base)
        self._top_universe: list[str] = []  # wypełniany po pierwszym pełnym skanie
        self._market_data = None
        self._broker = None
        self._finnhub = None

    def get_journal(self) -> BrainJournal:
        return self._journal

    # ── Publiczne API ─────────────────────────────────────────────────────────

    def stop(self):
        self._running = False

    def send_chat_message(self, message: str):
        """Kolejkuje wiadomość użytkownika do przetworzenia przez BrainBota."""
        self._chat_queue.put(message)

    # ── Lifecycle QThread ─────────────────────────────────────────────────────

    def run(self):
        if not self._enabled:
            logger.info("BrainScanner: disabled in config (brain_scanner.enabled=false)")
            return

        try:
            from modules.brokers.alpaca_broker import AlpacaBroker
            from modules.market_data import MarketDataFetcher
            mode = self._config.get("alpaca_mode", "paper")
            self._broker = AlpacaBroker(mode=mode)
            if not self._broker.connect():
                logger.error("BrainScanner: nie można połączyć z Alpaca")
                self.status_updated.emit("Scanner: błąd połączenia Alpaca")
                return
            self._market_data = MarketDataFetcher(self._config, self._broker)
        except Exception as exc:
            logger.error(f"BrainScanner: błąd inicjalizacji: {exc}")
            return

        if self._full_market_scan:
            try:
                all_assets = self._broker.get_all_assets()
                if all_assets:
                    merged = sorted(set(self._static_universe) | set(all_assets))
                    self._static_universe = merged
                    logger.info(f"BrainScanner: full_market_scan — {len(self._static_universe)} symboli")
            except Exception as exc:
                logger.warning(f"BrainScanner: full_market_scan assets error: {exc}")

        try:
            import os
            if os.getenv("FINNHUB_API_KEY", ""):
                from modules.finnhub_client import FinnhubClient
                self._finnhub = FinnhubClient(self._config)
        except Exception:
            pass

        self._running = True

        # Załaduj zapisany top_universe z poprzedniej sesji
        self._top_universe = self._journal.get_top_universe()

        total_syms = len(self._static_universe)
        logger.info(
            f"BrainBot uruchomiony — {total_syms} symboli w universum | "
            f"top_universe: {len(self._top_universe)} | batch regularny: {self._batch_size}"
        )
        self.status_updated.emit(f"BrainBot gotowy — {total_syms} symboli")

        # Pierwsze uruchomienie bez żadnych danych w brain — pełny skan jednorazowo
        # aby zasilić vol_sma20 (potrzebne do volume_ratio w hourly refresh)
        if not self._top_universe and self._brain.symbol_count() == 0:
            logger.info(f"BrainBot: pierwsze uruchomienie — jednorazowy skan ({total_syms} symboli)")
            self.status_updated.emit(f"Inicjalizacja: {total_syms} symboli…")
            self._run_full_scan()

        # Główna pętla: co godzinę hourly refresh → aktualizacja top_universe → LLM top 100
        while self._running:
            try:
                self._refresh_all_scores()
                self._rebuild_top_universe()
                total_scanned = self._regular_scan_cycle()
                self._update_journal(total_scanned)
                self.journal_updated.emit()
            except Exception as exc:
                logger.error(f"BrainScanner cycle error: {exc}", exc_info=True)
                self.status_updated.emit(f"Scanner błąd: {exc}")

            self._wait_interval(self._regular_interval)

        logger.info("BrainBot zatrzymany")

    # ── Pełny skan (szybki, bez LLM) ─────────────────────────────────────────

    def _run_full_scan(self):
        """
        Szybki skan całego universum — tylko pobieranie danych rynkowych, bez LLM.
        Po zakończeniu wyłania top N symboli do regularnych skanów.
        """
        all_syms = sorted(set(self._static_universe) | set(self._brain.all_symbols()))
        total = len(all_syms)

        checkpoint_scanned = self._load_checkpoint(self._full_checkpoint_path)
        remaining = [s for s in all_syms if s not in checkpoint_scanned]
        total_scanned = len(checkpoint_scanned)

        if checkpoint_scanned:
            logger.info(
                f"BrainScanner pełny: wznawianie — {total_scanned} już gotowych, "
                f"{len(remaining)} pozostało z {total}"
            )
            self.status_updated.emit(f"Wznawianie pełnego skanu: {total_scanned}/{total}…")
        else:
            logger.info(f"BrainScanner pełny: start — {total} symboli, {_FULL_SCAN_WORKERS} wątki równoległe")

        scanned_this_run: set[str] = set()
        # Save brain and checkpoint every N symbols to reduce lock contention
        _SAVE_EVERY = 1000

        for i in range(0, len(remaining), self._full_batch_size):
            if not self._running:
                break
            batch = remaining[i: i + self._full_batch_size]
            done = self._fetch_batch_parallel_no_save(batch)
            scanned_this_run.update(done)
            total_scanned += len(done)

            # Aktualizuj status co 200 symboli
            if total_scanned % 200 < self._full_batch_size or total_scanned >= total:
                pct = total_scanned / max(total, 1) * 100
                self.status_updated.emit(f"Pełny skan: {total_scanned}/{total} ({pct:.0f}%)…")
                self.scan_completed.emit(total_scanned, total)

            if total_scanned % _SAVE_EVERY < self._full_batch_size or total_scanned >= total:
                self._brain.save()
                self._save_checkpoint(self._full_checkpoint_path, checkpoint_scanned | scanned_this_run)

            if i + self._full_batch_size < len(remaining):
                time.sleep(self._full_batch_delay)

        # Wyłoń top N symboli według score
        all_entries = [
            (sym, self._brain.get_entry(sym) or {})
            for sym in self._brain.all_symbols()
        ]
        all_entries.sort(key=lambda x: x[1].get("score", 0.0), reverse=True)
        self._top_universe = [sym for sym, _ in all_entries[:self._top_universe_size]]

        # Przytnij brain do top N + static universe — uwalnia pamięć po 12K skanowaniu
        self._brain.prune(set(self._static_universe), self._top_universe_size)

        today_str = datetime.now().date().isoformat()
        self._journal.set_top_universe(self._top_universe)
        self._journal.set_last_full_scan_date(today_str)

        self._clear_checkpoint(self._full_checkpoint_path)

        self._update_journal(total_scanned)
        self.journal_updated.emit()

        logger.info(
            f"BrainBot pełny skan ukończony: {total_scanned}/{total} symboli, "
            f"top {len(self._top_universe)} wybranych do regularnych skanów"
        )
        top_preview = ", ".join(self._top_universe[:10])
        self.status_updated.emit(
            f"Pełny skan gotowy — top {len(self._top_universe)}: {top_preview}…"
        )
        self.scan_log_entry.emit(
            f"[{datetime.now().strftime('%H:%M:%S')}] Pełny skan: {total_scanned} symboli, "
            f"top {len(self._top_universe)} wyłonionych"
        )

    def _fetch_batch_parallel_no_save(self, batch: list[str]) -> list[str]:
        """Pobiera snapshoty równolegle (fast: tylko dzienny, bez weekly), aktualizuje brain.
        Nie zapisuje na dysk — caller odpowiada za wywołanie brain.save() co N batchy."""
        done: list[str] = []

        def fetch_one(symbol: str) -> str:
            try:
                snapshot = self._market_data.get_snapshot_fast(symbol)
                if snapshot:
                    self._brain.update_from_snapshot_fast(symbol, snapshot)
            except Exception:
                pass
            return symbol

        with ThreadPoolExecutor(max_workers=_FULL_SCAN_WORKERS) as executor:
            futures = {executor.submit(fetch_one, sym): sym for sym in batch}
            for future in as_completed(futures):
                try:
                    done.append(future.result())
                except Exception:
                    pass

        return done

    # ── Hourly refresh (batch API, wszystkie symbole) ─────────────────────────

    def _refresh_all_scores(self):
        """
        Odświeża momentum i volume_ratio dla WSZYSTKICH ~12K symboli przez batch snapshot API.
        ~13 callów API dla 12K symboli (1000 symboli/request). Bez LLM.
        Aktualizuje score → podstawa do wyboru top 100 dla LLM.
        """
        all_syms = self._brain.all_symbols()
        if not all_syms or self._broker is None:
            return

        total = len(all_syms)
        logger.info(f"BrainScanner hourly refresh: {total} symboli (batch snapshots)…")
        self.status_updated.emit(f"Odświeżanie score: {total} symboli…")

        refreshed = 0
        chunk_size = 1000

        for i in range(0, len(all_syms), chunk_size):
            if not self._running:
                break
            chunk = all_syms[i: i + chunk_size]
            try:
                tickers = self._broker.get_snapshots_batch(chunk, chunk_size=chunk_size)
                for sym, data in tickers.items():
                    self._brain.update_from_ticker_fast(
                        sym, data["change_pct"], data["volume"]
                    )
                refreshed += len(tickers)
            except Exception as exc:
                logger.debug(f"BrainScanner refresh chunk {i}: {exc}")
            if i + chunk_size < len(all_syms):
                time.sleep(0.3)

        self._brain.save()

        logger.info(f"BrainScanner hourly refresh: {refreshed}/{total} odświeżonych")
        self.status_updated.emit(f"Odświeżono {refreshed}/{total} — wybieram top {self._top_llm_scan_size}…")
        self.scan_completed.emit(refreshed, total)

    def _rebuild_top_universe(self):
        """Aktualizuje top_universe na podstawie aktualnych score po hourly refresh.
        Zastępuje dobowy pełny skan — działa bez dodatkowych wywołań API."""
        all_entries = [
            (sym, self._brain.get_entry(sym) or {})
            for sym in self._brain.all_symbols()
        ]
        all_entries.sort(key=lambda x: x[1].get("score", 0.0), reverse=True)
        self._top_universe = [sym for sym, _ in all_entries[:self._top_universe_size]]
        self._journal.set_top_universe(self._top_universe)
        logger.info(
            f"BrainBot top_universe: {len(self._top_universe)} symboli "
            f"(z {len(all_entries)} w brain)"
        )
        # Przytnij brain — usuwa symbole dodane przez news jeśli przekroczą limit
        open_syms: set[str] = set()
        try:
            if self._broker:
                positions = self._broker.get_positions()
                open_syms = {p["symbol"] for p in positions}
        except Exception:
            pass
        self._brain.prune(set(self._static_universe) | open_syms, self._top_universe_size)

    # ── LLM skan (szczegółowy, co godzinę, top N po refresh) ─────────────────

    def _regular_scan_cycle(self) -> int:
        """
        LLM skan tylko top N symboli wybranych PO hourly refresh score.
        Domyślnie top 100 — minimalne obciążenie LLM, maksymalna precyzja.
        """
        top_pairs = self._brain.top_scored(n=self._top_llm_scan_size)
        universe  = [sym for sym, _ in top_pairs]
        total     = len(universe)

        logger.info(
            f"BrainScanner LLM: start — top {total} z {self._brain.symbol_count()} symboli "
            f"(po hourly refresh)"
        )
        self.status_updated.emit(f"LLM skan top-{total}…")

        total_scanned = 0

        for i in range(0, len(universe), self._batch_size):
            if not self._running:
                break
            batch = universe[i: i + self._batch_size]
            for symbol in batch:
                if not self._running:
                    break
                try:
                    decision = self._scan_symbol(symbol)
                    if decision:
                        action = decision["action"]
                        conf   = decision["confidence"]
                        log_entry = (
                            f"[{datetime.now().strftime('%H:%M:%S')}] "
                            f"{symbol}: {action} {conf:.0%} — {decision.get('reasoning','')[:60]}"
                        )
                        self.scan_log_entry.emit(log_entry)
                    total_scanned += 1
                except Exception as exc:
                    logger.debug(f"BrainScanner LLM: {symbol} error: {exc}")
                time.sleep(0.5)

            self.status_updated.emit(f"LLM skan: {total_scanned}/{total}…")
            if i + self._batch_size < len(universe):
                time.sleep(self._batch_delay)

        self.scan_completed.emit(total_scanned, total)
        logger.info(f"BrainScanner LLM: ukończony — {total_scanned}/{total}")
        self.status_updated.emit(f"LLM skan ukończony: {total_scanned}/{total}")
        return total_scanned

    def _scan_symbol(self, symbol: str) -> Optional[dict]:
        if self._market_data is None:
            return None
        snapshot = self._market_data.get_snapshot(symbol)
        if snapshot is None:
            return None

        self._brain.update_from_snapshot(symbol, snapshot)

        if not self._is_interesting(snapshot):
            return None

        news_summary = self._get_news_summary(symbol)
        decision = self._quick_llm(symbol, snapshot, news_summary)
        if decision:
            self._brain.update_from_scanner(symbol, decision)
            logger.debug(
                f"BrainScanner: {symbol} → {decision['action']} "
                f"conf={decision['confidence']:.0%}"
            )
        return decision

    @staticmethod
    def _is_interesting(snapshot: dict) -> bool:
        p   = snapshot.get("price", {})
        ind = snapshot.get("indicators", {})

        change_pct   = abs(float(p.get("change_pct", 0.0) or 0.0))
        volume_ratio = float(ind.get("volume_ratio", 1.0) or 1.0)
        rsi          = ind.get("rsi")

        if change_pct >= 1.5:
            return True
        if volume_ratio >= 1.5:
            return True
        if rsi is not None and (float(rsi) <= 35.0 or float(rsi) >= 65.0):
            return True
        return False

    def _get_news_summary(self, symbol: str) -> str:
        try:
            from modules.news_store import NewsStore
            store = NewsStore(self._config)
            recent = store.query(symbol=symbol, limit=3)
            if recent:
                headlines = [n.get("headline", "") for n in recent[:3] if n.get("headline")]
                return " | ".join(h[:80] for h in headlines)
        except Exception:
            pass

        if self._finnhub is None:
            return "brak danych news"
        try:
            news = self._finnhub.get_company_news(symbol, count=3)
            if not news:
                return "brak ostatnich newsów"
            headlines = [n.get("headline", "") for n in news[:3] if n.get("headline")]
            return " | ".join(h[:80] for h in headlines)
        except Exception:
            return "błąd pobierania newsów"

    # ── Aktualizacja Dziennika ────────────────────────────────────────────────

    def _update_journal(self, total_scanned: int):
        """
        Po każdym cyklu wyznacza recommended_now i watch_later.
        Uwzględnia otwarte pozycje — symbole z pozycją pozostają w rekomendacjach
        niezależnie od score.
        """
        # Pobierz otwarte pozycje z brokera
        open_position_symbols: set[str] = set()
        try:
            if self._broker:
                positions = self._broker.get_positions()
                open_position_symbols = {p["symbol"] for p in positions}
        except Exception:
            pass

        all_entries = [
            (sym, self._brain.get_entry(sym) or {})
            for sym in self._brain.all_symbols()
        ]
        all_entries.sort(key=lambda x: x[1].get("score", 0.0), reverse=True)

        # Newsy dla top 100 kandydatów — jedno wywołanie dla wydajności
        news_by_sym: dict[str, list[str]] = {}
        try:
            from modules.news_store import NewsStore
            store = NewsStore(self._config)
            candidate_syms = [sym for sym, _ in all_entries[:100]]
            for sym in candidate_syms:
                recent = store.query(symbol=sym, limit=3)
                if recent:
                    news_by_sym[sym] = [
                        n.get("headline", "")
                        for n in recent[:3]
                        if n.get("headline")
                    ]
        except Exception as exc:
            logger.debug(f"BrainBot journal: błąd odczytu newsów: {exc}")

        recommended: list[dict] = []
        watch_later: list[dict] = []
        prev_recommended = set(self._journal.get_recommended_symbols())
        recommended_syms: set[str] = set()

        for sym, entry in all_entries:
            score = entry.get("score", 0.0)
            sc_action = (
                entry.get("scanner_action")
                or entry.get("llm_action")
                or "HOLD"
            )
            sc_conf = max(
                float(entry.get("scanner_confidence", 0.0) or 0.0),
                float(entry.get("llm_confidence", 0.0) or 0.0),
            )

            # Symbolom z otwartą pozycją zawsze przyznaj status rekomendowany
            has_open_position = sym in open_position_symbols

            if has_open_position or (
                sc_action in ("BUY", "SELL")
                and sc_conf >= self._recommend_min_conf
                and score >= 0.05
            ):
                rec_entry: dict = {
                    "symbol":         sym,
                    "action":         sc_action,
                    "confidence":     round(sc_conf, 3),
                    "score":          round(score, 4),
                    "ts":             _now_iso(),
                    "open_position":  has_open_position,
                }
                if sym in news_by_sym:
                    rec_entry["recent_news"] = news_by_sym[sym]
                recommended.append(rec_entry)
                recommended_syms.add(sym)
            elif score >= 0.03:
                wl_entry: dict = {
                    "symbol": sym,
                    "score":  round(score, 4),
                    "ts":     _now_iso(),
                }
                if sym in news_by_sym:
                    wl_entry["recent_news"] = news_by_sym[sym]
                watch_later.append(wl_entry)

        # Uczenie: symbole bez pozycji, które wypadły z rekomendacji z powodu odwrotu
        current_rec_syms = recommended_syms
        for sym, entry in all_entries:
            if sym not in prev_recommended or sym in current_rec_syms:
                continue
            if sym in open_position_symbols:
                continue  # pozycje zawsze zostają, nie wymagają notatki
            sc_action = entry.get("scanner_action") or "HOLD"
            sc_conf   = float(entry.get("scanner_confidence", 0.0) or 0.0)
            old_entry = next(
                (r for r in self._journal.get_recommended_now() if r["symbol"] == sym), None
            )
            if old_entry and sc_action != old_entry.get("action", "HOLD") and sc_conf >= 0.6:
                lesson = (
                    f"Rekomendowałem {old_entry['action']} dla {sym} "
                    f"(conf {old_entry['confidence']:.0%}), teraz sygnał to {sc_action} "
                    f"(conf {sc_conf:.0%}). Sygnał się odwrócił — ocena była przedwczesna."
                )
                self._journal.add_learning_note(
                    symbol=sym,
                    predicted=old_entry["action"],
                    result=f"Sygnał odwrócony → {sc_action}",
                    lesson=lesson,
                )
                logger.info(f"BrainBot learning: {sym} signal reversed — note added")
            elif old_entry:
                score = entry.get("score", 0.0)
                if score < 0.03:
                    logger.debug(f"BrainBot: {sym} usunięty z rekomendacji (score={score:.4f})")

        self._journal.update_recommendations(recommended, watch_later, total_scanned)
        logger.info(
            f"BrainBot journal: {len(recommended)} rekomendowanych "
            f"({len(open_position_symbols)} z otwartą pozycją), "
            f"{len(watch_later)} w obserwacji"
        )

        # Emituj do logu które symbole zostały zastąpione (słabe bez pozycji → nowe)
        added_syms   = recommended_syms - prev_recommended
        dropped_syms = prev_recommended - recommended_syms - open_position_symbols
        if dropped_syms or added_syms:
            ts = datetime.now().strftime("%H:%M:%S")
            parts = []
            if dropped_syms:
                drop_list = ", ".join(sorted(dropped_syms)[:5])
                suffix = f"…+{len(dropped_syms)-5}" if len(dropped_syms) > 5 else ""
                parts.append(f"usunięto {len(dropped_syms)}: {drop_list}{suffix}")
            if added_syms:
                add_list = ", ".join(sorted(added_syms)[:5])
                suffix = f"…+{len(added_syms)-5}" if len(added_syms) > 5 else ""
                parts.append(f"dodano {len(added_syms)}: {add_list}{suffix}")
            self.scan_log_entry.emit(f"[{ts}] Dziennik zaktualizowany — {' | '.join(parts)}")

    # ── Czat z użytkownikiem ──────────────────────────────────────────────────

    def _process_chat(self, message: str):
        self._journal.add_chat_message("user", message)
        logger.info(f"BrainBot chat: user → {message[:60]}")

        recommended = self._journal.get_recommended_now()[:10]
        notes       = self._journal.get_learning_notes()[-5:]
        guidance    = self._journal.get_user_guidance()
        stats       = self._journal.get_stats()

        rec_str = ", ".join(
            f"{r['symbol']} ({r['action']} {r['confidence']:.0%})"
            for r in recommended
        ) or "brak rekomendacji"

        notes_str = (
            " | ".join(f"{n['symbol']}: {n['lesson'][:60]}" for n in notes)
            if notes else "brak notatek"
        )

        news_ctx = ""
        try:
            from modules.news_store import NewsStore
            store = NewsStore(self._config)
            news_lines = []
            for r in recommended[:5]:
                sym = r["symbol"]
                items = store.query(symbol=sym, limit=2)
                for item in items[:2]:
                    h = item.get("headline", "")
                    if h:
                        news_lines.append(f"  {sym}: {h[:100]}")
            if news_lines:
                news_ctx = "\n- Ostatnie newsy:\n" + "\n".join(news_lines)
        except Exception:
            pass

        top_preview = ", ".join(self._top_universe[:20]) if self._top_universe else "brak"

        system = f"""Jesteś BrainBotem — AI analitykiem rynku w systemie 777moneymaker.
Skanujesz cały rynek akcji w trzech etapach:
- Pełny skan (raz dziennie o północy): szybki przegląd wszystkich {self._brain.symbol_count()} symboli, wyłania top {self._top_universe_size}
- Hourly refresh (co godzinę): batch snapshot API dla wszystkich symboli — odświeża momentum i volume_ratio (~13 callów API)
- LLM skan (co godzinę, po refresh): pełna analiza AI tylko top {self._top_llm_scan_size} wg aktualnego score

Stan aktualny:
- Wszystkie symbole w brain: {self._brain.symbol_count()}
- Przeskanowane w ostatnim cyklu LLM: {stats.get('total_scanned', 0)}
- Top {self._top_universe_size} (z nocnego skanu): {top_preview[:200]}…
- Aktualnie rekomendowane: {rec_str}
- Notatki uczenia (ostatnie): {notes_str}
- Wytyczne użytkownika: {guidance or 'brak'}{news_ctx}

Odpowiadaj po polsku. Bądź zwięzły i konkretny.
Jeśli użytkownik chce zmienić Twoją strategię lub fokus — potwierdź co zmienisz.
Jeśli chce znać stan rynku lub rekomendacje — podaj je wprost."""

        response = self._call_ollama_chat(system, message)
        if not response:
            response = (
                "Przepraszam, LLM (Ollama) jest niedostępna. "
                "Uruchom: ollama serve — i spróbuj ponownie."
            )

        self._journal.add_chat_message("brain", response)
        logger.info(f"BrainBot chat: brain → {response[:80]}")

        guidance_keywords = [
            "skup", "unikaj", "ignoruj", "focus", "avoid",
            "concentrate", "zwróć uwagę", "pomijaj", "preferuj",
        ]
        if any(kw in message.lower() for kw in guidance_keywords):
            self._journal.append_user_guidance(message)

        self.chat_response_ready.emit(response)

    def _call_ollama_chat(self, system: str, user: str) -> Optional[str]:
        try:
            payload = {
                "model":   self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                "stream":  False,
                "options": {"temperature": 0.7, "num_predict": 512},
            }
            r = requests.post(
                f"{self._base_url}/api/chat", json=payload, timeout=60
            )
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
        except Exception as exc:
            logger.debug(f"BrainBot chat LLM error: {exc}")
            return None

    # ── LLM skan (lekki, JSON) ────────────────────────────────────────────────

    def _quick_llm(self, symbol: str, snapshot: dict, news_summary: str) -> Optional[dict]:
        p   = snapshot["price"]
        ind = snapshot.get("indicators", {})

        def v(k, default=0.0):
            val = ind.get(k)
            return val if val is not None else default

        macd_trend = "rising ↑" if v("macd_hist") > v("macd_hist_prev") else "falling ↓"

        spread = max(v("bb_upper") - v("bb_lower"), 0.001)
        bb_pct = (p["current"] - v("bb_lower")) / spread
        if bb_pct < 0.15:
            bb_pos = f"near lower band ({bb_pct:.0%}) — potential bounce"
        elif bb_pct > 0.85:
            bb_pos = f"near upper band ({bb_pct:.0%}) — potential reversal"
        else:
            bb_pos = f"mid-channel ({bb_pct:.0%})"

        above20  = ind.get("above_sma20",  False)
        above50  = ind.get("above_sma50",  False)
        above200 = ind.get("above_sma200", False)
        cnt      = sum([above20, above50, above200])
        trend    = "STRONG UPTREND" if cnt == 3 else ("STRONG DOWNTREND" if cnt == 0 else "MIXED")
        above_smas = (
            f"{'↑' if above20 else '↓'}SMA20 "
            f"{'↑' if above50 else '↓'}SMA50 "
            f"{'↑' if above200 else '↓'}SMA200"
        )

        rsi_val = ind.get("rsi")
        rsi_str = f"{rsi_val:.1f}" if rsi_val is not None else "N/A"

        prompt = _SCAN_USER.format(
            symbol=symbol,
            price=p["current"],
            change_pct=p.get("change_pct", 0.0),
            rsi=rsi_str,
            macd_trend=macd_trend,
            vol_ratio=v("volume_ratio", 1.0),
            trend=trend,
            bb_pos=bb_pos,
            above_smas=above_smas,
            news_summary=(news_summary or "brak")[:200],
        )

        raw = self._call_ollama_json(prompt)
        return self._parse_scan(raw) if raw else None

    def _call_ollama_json(self, user_prompt: str) -> Optional[str]:
        try:
            payload = {
                "model":    self._model,
                "messages": [
                    {"role": "system", "content": _SCAN_SYSTEM},
                    {"role": "user",   "content": user_prompt},
                ],
                "stream":  False,
                "format":  "json",
                "options": {"temperature": 0.0, "num_predict": 256},
            }
            r = requests.post(
                f"{self._base_url}/api/chat", json=payload, timeout=self._timeout
            )
            if r.status_code == 404:
                return self._call_ollama_generate(user_prompt)
            r.raise_for_status()
            return r.json()["message"]["content"]
        except requests.Timeout:
            logger.debug(f"BrainScanner: Ollama timeout ({self._timeout}s)")
        except requests.ConnectionError:
            logger.debug("BrainScanner: Ollama niedostępna")
        except Exception as exc:
            logger.debug(f"BrainScanner: Ollama error: {exc}")
        return None

    def _call_ollama_generate(self, user_prompt: str) -> Optional[str]:
        try:
            payload = {
                "model":   self._model,
                "system":  _SCAN_SYSTEM,
                "prompt":  user_prompt,
                "stream":  False,
                "format":  "json",
                "options": {"temperature": 0.0, "num_predict": 256},
            }
            r = requests.post(
                f"{self._base_url}/api/generate", json=payload, timeout=self._timeout
            )
            r.raise_for_status()
            return r.json()["response"]
        except Exception as exc:
            logger.debug(f"BrainScanner: generate error: {exc}")
        return None

    @staticmethod
    def _parse_scan(raw: str) -> Optional[dict]:
        raw = raw.strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            raw = m.group(0)
        try:
            data = json.loads(raw)
        except Exception:
            return None

        action = str(data.get("action", "HOLD")).upper().strip()
        if action not in ("BUY", "SELL", "HOLD"):
            action = "HOLD"
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))

        return {
            "action":      action,
            "confidence":  confidence,
            "reasoning":   str(data.get("reasoning", "scanner"))[:200],
            "key_signals": list(data.get("key_signals", []))[:5],
            "news_impact": str(data.get("news_impact", "neutral")).lower(),
        }

    # ── Czekanie z obsługą czatu i wykrywaniem północy ────────────────────────

    def _wait_interval(self, seconds: int):
        """Czeka `seconds`, obsługując czat i przerywając przy zmianie daty (północ)."""
        start_date = datetime.now().date()
        for _ in range(seconds):
            if not self._running:
                break
            if datetime.now().date() != start_date:
                # Północ — przerwij czekanie żeby uruchomić pełny skan
                logger.info("BrainBot: wykryto zmianę daty — przerywam czekanie dla pełnego skanu")
                break
            time.sleep(1)
            try:
                msg = self._chat_queue.get_nowait()
                self._process_chat(msg)
            except queue.Empty:
                pass

    # ── Checkpointy ───────────────────────────────────────────────────────────

    def _load_checkpoint(self, path: Path) -> set:
        try:
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                scanned = set(data.get("scanned", []))
                logger.info(f"BrainScanner: checkpoint {path.name} — {len(scanned)} symboli")
                return scanned
        except Exception as exc:
            logger.warning(f"BrainScanner: błąd odczytu checkpointu {path.name}: {exc}")
        return set()

    def _save_checkpoint(self, path: Path, scanned: set):
        try:
            tmp = path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"scanned": sorted(scanned), "ts": _now_iso()}, f)
            tmp.replace(path)
        except Exception as exc:
            logger.debug(f"BrainScanner: błąd zapisu checkpointu: {exc}")

    def _clear_checkpoint(self, path: Path):
        try:
            if path.exists():
                path.unlink()
        except Exception as exc:
            logger.debug(f"BrainScanner: błąd usuwania checkpointu: {exc}")


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")
