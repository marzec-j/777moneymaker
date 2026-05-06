"""
Background QThread that runs the trading engine.
Emits Qt signals so the GUI can react without polling.
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

if TYPE_CHECKING:
    from modules.symbol_brain import SymbolBrain


class QtLogHandler(logging.Handler):
    """Forwards Python log records to a Qt signal."""

    def __init__(self, signal: Signal):
        super().__init__()
        self._signal = signal
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        ))

    def emit(self, record: logging.LogRecord):
        try:
            self._signal.emit(record.levelname, self.format(record))
        except Exception:
            pass


class TradingWorker(QThread):
    # ── Signals ───────────────────────────────────────────────────────────────
    account_updated   = Signal(dict)
    positions_updated = Signal(list)
    log_emitted       = Signal(str, str)   # level, formatted message
    status_changed    = Signal(str)
    cycle_done        = Signal()
    error_occurred    = Signal(str)
    trade_closed      = Signal(dict)       # {"symbol", "action", "pnl", "was_recommended"}

    def __init__(
        self,
        config: dict,
        brain: Optional["SymbolBrain"] = None,
        journal=None,
        parent=None,
    ):
        super().__init__(parent)
        self._config  = config
        self._brain   = brain
        self._journal = journal
        self._running = False
        self._broker  = None

    # ── Public API ────────────────────────────────────────────────────────────

    def stop(self):
        self._running = False
        self.status_changed.emit("Stopping…")

    def get_broker(self):
        return self._broker

    # ── Thread entry point ────────────────────────────────────────────────────

    def run(self):
        self._running = True
        self.status_changed.emit("Starting…")

        logger = logging.getLogger("777moneymaker")
        logger.setLevel(logging.INFO)
        qt_handler = QtLogHandler(self.log_emitted)
        logger.addHandler(qt_handler)

        try:
            self._run_inner(logger)
        except Exception as exc:
            logger.error(f"Fatal worker error: {exc}", exc_info=True)
            self.error_occurred.emit(str(exc))
            self.status_changed.emit("Error")
        finally:
            logger.removeHandler(qt_handler)
            self.status_changed.emit("Stopped")

    def _run_inner(self, logger):
        import os
        from modules.brokers.alpaca_broker import AlpacaBroker
        from modules.market_data import MarketDataFetcher
        from modules.llm_analyzer import LLMAnalyzer
        from modules.risk_manager import RiskManager
        from modules.trading_engine import TradingEngine
        from modules.trade_logger import TradeLogger

        mode = self._config.get("alpaca_mode", "paper")
        self._broker = AlpacaBroker(mode=mode)

        if not self._broker.connect():
            self.error_occurred.emit(
                "Nie można połączyć z Alpaca — sprawdź klucze API w Ustawieniach"
            )
            self.status_changed.emit("Error")
            return

        self.account_updated.emit(self._broker.get_account())
        self.positions_updated.emit(self._broker.get_positions())

        # ── Build engine components ───────────────────────────────────────────
        llm       = LLMAnalyzer(self._config)
        data      = MarketDataFetcher(self._config, self._broker)
        risk      = RiskManager(self._config)
        trade_log = TradeLogger(self._config)

        if not llm.is_available():
            logger.warning(
                "Ollama niedostępna — decyzje LLM wyłączone. "
                "Uruchom: ollama serve"
            )

        finnhub = None
        try:
            if os.getenv("FINNHUB_API_KEY", ""):
                from modules.finnhub_client import FinnhubClient
                finnhub = FinnhubClient()
                if finnhub.is_available():
                    logger.info("Finnhub połączony — newsy będą używane przez AI")
                else:
                    logger.warning("Finnhub: nieprawidłowy klucz API — newsy wyłączone")
                    finnhub = None
        except Exception as exc:
            logger.warning(f"Finnhub init error: {exc}")

        if self._brain:
            logger.info(
                f"SymbolBrain aktywny — {self._brain.symbol_count()} symboli "
                f"w pamięci, watchlist_size={self._brain._watchlist_size}"
            )

        def _on_trade_closed(info: dict):
            self.trade_closed.emit(info)

        engine = TradingEngine(
            self._config, self._broker, data, llm, risk, trade_log,
            finnhub=finnhub,
            brain=self._brain,
            journal=self._journal,
            on_trade_closed=_on_trade_closed,
        )

        # ── Main loop ─────────────────────────────────────────────────────────
        self.status_changed.emit("Running")
        interval   = self._config.get("loop_interval", 60)
        mode_label = "PAPER (Alpaca)" if mode == "paper" else "LIVE (Alpaca)"
        brain_info = (
            f"Brain: {self._brain.symbol_count()} symbols"
            if self._brain else "Brain: disabled"
        )
        logger.info(
            f"Bot started | Mode: {mode_label} | "
            f"Model: {self._config['llm']['model']} | {brain_info}"
        )

        while self._running:
            try:
                engine.run_cycle()
            except Exception as exc:
                logger.error(f"Cycle error: {exc}", exc_info=True)
                self.error_occurred.emit(str(exc))

            try:
                self.account_updated.emit(self._broker.get_account())
                self.positions_updated.emit(self._broker.get_positions())
            except Exception as exc:
                logger.warning(f"Post-cycle data refresh failed: {exc}")
            self.cycle_done.emit()

            logger.info(f"Next cycle in {interval}s…")
            for _ in range(interval):
                if not self._running:
                    break
                self.msleep(1000)

        logger.info("Bot stopped.")
