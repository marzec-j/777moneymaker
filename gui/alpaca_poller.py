"""
Lekki wątek który poll'uje Alpaca co POLL_INTERVAL sekund.
Działa niezależnie od bota — zakładki widzą dane bez uruchamiania pętli tradingowej.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger("777moneymaker")

POLL_INTERVAL = 30  # sekund między automatycznymi odświeżeniami


class AlpacaPoller(QThread):
    account_updated   = Signal(dict)
    positions_updated = Signal(list)
    status_changed    = Signal(str)   # np. "Alpaca PAPER", "Brak połączenia", "Błąd: ..."

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config  = config
        self._running = False
        self._broker  = None
        self._force   = False
        self._do_reconnect = False

    # ── Public API ────────────────────────────────────────────────────────

    def force_refresh(self):
        """Wymuś natychmiastowe pobranie danych."""
        self._force = True

    def reconnect(self):
        """Zresetuj brokera (np. po zmianie kluczy w ustawieniach)."""
        self._broker = None
        self._do_reconnect = True
        self._force = True

    def get_broker(self):
        """Returns the connected broker instance, or None if not connected."""
        return self._broker

    def get_all_assets(self) -> list[str]:
        """Returns all active tradable US equity symbols from Alpaca (cached 1h)."""
        if self._broker:
            return self._broker.get_all_assets()
        return []

    def stop(self):
        self._running = False

    # ── Thread ────────────────────────────────────────────────────────────

    def run(self):
        self._running = True
        self._connect()
        self._fetch()

        elapsed = 0
        while self._running:
            self.msleep(1000)
            elapsed += 1
            if self._do_reconnect:
                self._do_reconnect = False
                self._connect()
            if self._force or elapsed >= POLL_INTERVAL:
                self._force = False
                elapsed = 0
                self._fetch()

    # ── Internal ──────────────────────────────────────────────────────────

    def _connect(self):
        try:
            from dotenv import load_dotenv
            load_dotenv(override=True)
        except ImportError:
            pass

        try:
            from modules.brokers.alpaca_broker import AlpacaBroker
            mode = self._config.get("alpaca_mode", "paper")
            self._broker = AlpacaBroker(mode=mode)
            if self._broker.connect():
                self.status_changed.emit(f"Alpaca {mode.upper()}")
            else:
                self._broker = None
                self.status_changed.emit("Brak połączenia")
        except Exception as exc:
            self._broker = None
            self.status_changed.emit(f"Błąd: {exc}")

    def _fetch(self):
        if not self._broker:
            self._connect()
            if not self._broker:
                return
        try:
            acc = self._broker.get_account()
            self.account_updated.emit(acc)
            pos = self._broker.get_positions()
            self.positions_updated.emit(pos)
        except Exception as exc:
            logger.warning(f"AlpacaPoller: błąd pobierania — {exc}")
            self._broker = None
            self.status_changed.emit("Błąd pobierania danych")
