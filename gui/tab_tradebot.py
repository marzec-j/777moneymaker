"""
TradeBotTab — zakładka TradeBot z podzakładkami: Pozycje, Logi, Decyzje.
Wraps istniejące zakładki w jeden QTabWidget.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget
from .styles import make_page_header

from .tab_positions import PositionsTab
from .tab_logs import LogsTab
from .tab_decisions import DecisionsTab


class TradeBotTab(QWidget):

    def __init__(self, config: dict, worker, poller=None, parent=None):
        super().__init__(parent)

        self._inner = QTabWidget()
        self._inner.setDocumentMode(True)

        self._pozycje  = PositionsTab(worker)
        self._logi     = LogsTab(worker)
        self._decyzje  = DecisionsTab(config, worker)

        self._inner.addTab(self._logi,     "📋  Console")
        self._inner.addTab(self._pozycje,  "💼  Positions")
        self._inner.addTab(self._decyzje,  "🧠  Decisions")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(16)
        lay.addWidget(make_page_header("TradeBot", "Silnik handlowy AI"))
        lay.addWidget(self._inner)

    def update_positions(self, positions: list):
        """Przekazuje aktualizację pozycji z pollera do PositionsTab."""
        self._pozycje._update(positions)

    # ── Propsy dla MainWindow (dostęp do sygnałów wewnętrznych zakładek) ─────

    @property
    def log_append(self):
        """Callback '_append' z LogsTab — dla rejestracji log handlerów."""
        return self._logi._append

    @property
    def refresh_requested(self) -> Signal:
        """Signal PositionsTab — żądanie odświeżenia danych."""
        return self._pozycje.refresh_requested
