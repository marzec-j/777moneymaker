from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMainWindow,
    QSizePolicy, QStackedWidget, QStatusBar, QVBoxLayout, QWidget,
)

from .styles import (
    DARK_THEME,
    COLOR_GREEN, COLOR_RED, COLOR_GOLD, COLOR_MUTED, COLOR_FG,
)
from .alpaca_poller import AlpacaPoller
from .trading_worker import TradingWorker
from .tab_dashboard import DashboardTab
from .tab_market import MarketTab
from .tab_chart import ChartTab
from .tab_news import NewsTab
from .tab_settings import SettingsTab
from .tab_brainbot import BrainBotTab
from .tab_tradebot import TradeBotTab
from modules.news_poller import NewsPoller
from modules.symbol_brain import SymbolBrain
from modules.brain_scanner import BrainScannerWorker
from modules.brain_journal import BrainJournal
from . import _register_log_callback, _unregister_log_callback


# ── Navigation items definition ───────────────────────────────────────────────

_NAV = [
    ("📊", "Dashboard", 0),
    ("📈", "Market",    1),
    ("🕯",  "Chart",    2),
    ("🧠", "BrainBot",  3),
    ("🤖", "TradeBot",  4),
    ("📰", "News",      5),
    ("⚙",  "Settings", 6),
]

_MONO = "font-family: 'JetBrains Mono','Consolas',monospace;"
_SANS = "font-family: 'Inter','Segoe UI',sans-serif;"


# ── Single sidebar nav item ───────────────────────────────────────────────────

class _NavItem(QWidget):

    def __init__(self, icon: str, label: str, index: int, on_click, parent=None):
        super().__init__(parent)
        self._index    = index
        self._active   = False
        self._on_click = on_click

        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)

        self._icon = QLabel(icon)
        self._icon.setFixedWidth(22)
        self._icon.setAlignment(Qt.AlignCenter)
        self._icon.setAttribute(Qt.WA_TransparentForMouseEvents)

        self._text = QLabel(label)
        self._text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._text.setAttribute(Qt.WA_TransparentForMouseEvents)

        self._dot = QLabel("●")
        self._dot.setFixedWidth(10)
        self._dot.setAlignment(Qt.AlignCenter)
        self._dot.setVisible(False)
        self._dot.setAttribute(Qt.WA_TransparentForMouseEvents)

        lay.addWidget(self._icon)
        lay.addWidget(self._text)
        lay.addStretch()
        lay.addWidget(self._dot)

        self._paint(hover=False)

    def set_active(self, active: bool):
        self._active = active
        self._dot.setVisible(active)
        self._paint(hover=False)

    def _paint(self, hover: bool):
        _no_border = "background: transparent; border: none;"

        if self._active:
            self.setStyleSheet(
                "QWidget { background: rgba(34,197,94,0.08);"
                " border: 1px solid rgba(34,197,94,0.2); border-radius: 8px; }"
            )
            c, w = COLOR_GREEN, "600"
        elif hover:
            self.setStyleSheet(
                "QWidget { background: #182537;"
                " border: 1px solid transparent; border-radius: 8px; }"
            )
            c, w = COLOR_FG, "500"
        else:
            self.setStyleSheet(
                "QWidget { background: transparent;"
                " border: 1px solid transparent; border-radius: 8px; }"
            )
            c, w = COLOR_MUTED, "500"

        self._icon.setStyleSheet(f"font-size: 16px; color: {c}; {_no_border}")
        self._text.setStyleSheet(
            f"font-size: 13px; font-weight: {w}; color: {c}; {_SANS} {_no_border}"
        )
        self._dot.setStyleSheet(f"font-size: 8px; color: {COLOR_GREEN}; {_no_border}")

    def enterEvent(self, event):
        if not self._active:
            self._paint(hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._active:
            self._paint(hover=False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._on_click(self._index)
        super().mousePressEvent(event)


# ── Sidebar widget ────────────────────────────────────────────────────────────

class _Sidebar(QFrame):

    def __init__(self, on_nav, parent=None):
        super().__init__(parent)
        self._on_nav = on_nav
        self._items: list[_NavItem] = []

        self.setFixedWidth(220)
        self.setObjectName("sidebar")
        self.setStyleSheet(
            "QFrame#sidebar { background-color: #0c1421;"
            " border-right: 1px solid #1e2d3f; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Logo ──────────────────────────────────────────────────────
        logo_frame = QFrame()
        logo_frame.setFixedHeight(56)
        logo_frame.setStyleSheet(
            "QFrame { background-color: #0c1421; border-bottom: 1px solid #1e2d3f; }"
        )
        ll = QHBoxLayout(logo_frame)
        ll.setContentsMargins(16, 0, 16, 0)
        ll.setSpacing(10)

        badge = QLabel("7")
        badge.setFixedSize(32, 32)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #22c55e,stop:1 #eab308); border-radius: 8px;"
            "font-size: 15px; font-weight: 800; color: #080e1a; border: none;"
        )

        names = QWidget()
        names.setStyleSheet("background: transparent;")
        nl = QVBoxLayout(names)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(0)

        n1 = QLabel("777money")
        n1.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #e2e8f0; background: transparent; border: none;"
        )
        n2 = QLabel("maker")
        n2.setStyleSheet(
            f"font-size: 10px; color: {COLOR_GOLD}; {_MONO}"
            " background: transparent; border: none;"
        )
        nl.addWidget(n1)
        nl.addWidget(n2)

        ll.addWidget(badge)
        ll.addWidget(names)
        ll.addStretch()
        root.addWidget(logo_frame)

        # ── Nav items ─────────────────────────────────────────────────
        nav = QWidget()
        nav.setStyleSheet("background: transparent;")
        nav_lay = QVBoxLayout(nav)
        nav_lay.setContentsMargins(8, 8, 8, 8)
        nav_lay.setSpacing(2)
        nav_lay.setAlignment(Qt.AlignTop)

        for icon, label, idx in _NAV:
            item = _NavItem(icon, label, idx, self._on_click)
            self._items.append(item)
            nav_lay.addWidget(item)

        nav_lay.addStretch()
        root.addWidget(nav, 1)

        # ── Version ───────────────────────────────────────────────────
        ver_frame = QFrame()
        ver_frame.setFixedHeight(32)
        ver_frame.setStyleSheet(
            "QFrame { border-top: 1px solid #1e2d3f; background: transparent; }"
        )
        vl = QHBoxLayout(ver_frame)
        vl.setContentsMargins(0, 0, 0, 0)
        lv = QLabel("v2.1.0")
        lv.setAlignment(Qt.AlignCenter)
        lv.setStyleSheet(
            f"color: {COLOR_MUTED}; font-size: 10px; {_MONO}"
            " background: transparent; border: none;"
        )
        vl.addWidget(lv)
        root.addWidget(ver_frame)

        self._items[0].set_active(True)

    def _on_click(self, index: int):
        for item in self._items:
            item.set_active(item._index == index)
        self._on_nav(index)

    def set_index(self, index: int):
        for item in self._items:
            item.set_active(item._index == index)


# ── Main Window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self, config: dict, config_path: str = "config.yaml"):
        super().__init__()
        self._config      = config
        self._config_path = config_path

        self.setWindowTitle("777moneymaker — AI Trading System")
        self.resize(1440, 880)
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(DARK_THEME)

        self._brain         = SymbolBrain(config)
        self._journal       = BrainJournal(config)
        self._brain_scanner = BrainScannerWorker(config, brain=self._brain, journal=self._journal)
        self._worker        = TradingWorker(config, brain=self._brain, journal=self._journal)
        self._poller        = AlpacaPoller(config)
        self._news_poller   = NewsPoller(config, brain=self._brain, journal=self._journal)

        self._build_ui()
        self._build_statusbar()
        self._connect_signals()
        _register_log_callback(self._tab_tradebot.log_append)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_status)
        self._timer.start(1000)

        self._poller.start()
        self._news_poller.start()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sidebar
        self._sidebar = _Sidebar(self._on_nav)
        layout.addWidget(self._sidebar)

        # Separator line (already handled by sidebar border-right)

        # Page stack
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("QStackedWidget { background: #080e1a; }")
        layout.addWidget(self._stack)

        # Create pages — order must match _NAV indices
        self._tab_dashboard = DashboardTab(self._worker, self._config, scanner=self._brain_scanner)
        self._tab_market    = MarketTab(self._config, self._worker, self._poller)
        self._tab_chart     = ChartTab(self._config, self._worker, self._poller)
        self._tab_brainbot  = BrainBotTab(
            self._config, brain=self._brain, worker=self._worker,
            scanner=self._brain_scanner, journal=self._journal,
        )
        self._tab_tradebot = TradeBotTab(self._config, self._worker, self._poller)
        self._tab_news     = NewsTab(self._config, self._worker)
        self._tab_settings = SettingsTab(self._config, self._config_path)

        for page in (
            self._tab_dashboard,   # 0
            self._tab_market,      # 1
            self._tab_chart,       # 2
            self._tab_brainbot,    # 3
            self._tab_tradebot,    # 4
            self._tab_news,        # 5
            self._tab_settings,    # 6
        ):
            self._stack.addWidget(page)

    def _on_nav(self, index: int):
        self._stack.setCurrentIndex(index)

    def _build_statusbar(self):
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        _s = f"{_MONO} font-size: 11px;"
        _muted = f"color: {COLOR_MUTED}; {_s}"

        # TradeBot indicator
        self._dot_bot = QLabel("●")
        self._dot_bot.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 9px;")
        lbl_bot = QLabel("TradeBot:")
        lbl_bot.setStyleSheet(_muted)
        self._lbl_bot_status = QLabel("stopped")
        self._lbl_bot_status.setStyleSheet(_muted)

        # BrainBot indicator
        self._dot_brain = QLabel("●")
        self._dot_brain.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 9px;")
        lbl_brain = QLabel("BrainBot:")
        lbl_brain.setStyleSheet(_muted)
        self._lbl_brain_status = QLabel("initializing…")
        self._lbl_brain_status.setStyleSheet(_muted)

        for w in (self._dot_bot, lbl_bot, self._lbl_bot_status,
                  QLabel("  "),
                  self._dot_brain, lbl_brain, self._lbl_brain_status):
            w.setStyleSheet(w.styleSheet() or _muted)
            self._statusbar.addWidget(w)

        self._lbl_alpaca_status = QLabel("Alpaca: connecting…")
        self._lbl_alpaca_status.setStyleSheet(_muted)
        self._statusbar.addPermanentWidget(self._lbl_alpaca_status)

    def _connect_signals(self):
        # Market → open chart on double-click
        self._tab_market.symbol_selected.connect(self._open_chart_for_symbol)

        # TradeBot worker
        self._worker.status_changed.connect(self._on_bot_status)
        self._worker.error_occurred.connect(
            lambda e: self._lbl_bot_status.setText(f"error — {e[:40]}")
        )
        self._worker.trade_closed.connect(self._on_trade_closed)

        # Alpaca poller → multiple consumers
        self._poller.account_updated.connect(self._tab_dashboard._on_account)
        self._poller.positions_updated.connect(self._tab_dashboard._on_positions)
        self._poller.positions_updated.connect(self._tab_chart._on_positions_updated)
        self._poller.positions_updated.connect(self._tab_market.update_positions)
        self._poller.positions_updated.connect(self._tab_tradebot.update_positions)
        self._poller.status_changed.connect(self._on_alpaca_status)

        # Worker → dashboard / chart / market / tradebot
        self._worker.account_updated.connect(self._tab_dashboard._on_account)
        self._worker.positions_updated.connect(self._tab_dashboard._on_positions)
        self._worker.positions_updated.connect(self._tab_tradebot.update_positions)
        self._worker.positions_updated.connect(self._tab_chart._on_positions_updated)
        self._worker.positions_updated.connect(self._tab_market.update_positions)

        # Refresh requests
        self._tab_dashboard.refresh_requested.connect(self._poller.force_refresh)
        self._tab_tradebot.refresh_requested.connect(self._poller.force_refresh)

        # Settings
        self._tab_settings.settings_saved.connect(self._poller.reconnect)

        # News poller
        self._news_poller.news_updated.connect(self._tab_news.on_news_updated)

        # BrainBot scanner
        self._brain_scanner.status_updated.connect(self._on_brain_scanner_status)
        self._brain_scanner.scan_completed.connect(self._tab_brainbot.on_scan_completed)
        self._brain_scanner.journal_updated.connect(self._on_journal_updated)

        # Chart ↔ market watchlist sync
        self._tab_chart.symbols_changed.connect(self._tab_market.update_watchlist)

        # First poller data → chart ready
        self._poller.account_updated.connect(self._on_first_poller_data)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_first_poller_data(self, acc: dict):
        self._poller.account_updated.disconnect(self._on_first_poller_data)
        self._tab_chart.on_poller_ready()

    def _on_bot_status(self, status: str):
        _s = f"{_MONO} font-size: 11px;"
        label_map = {
            "Running":   ("running",   COLOR_GREEN),
            "Stopped":   ("stopped",   COLOR_MUTED),
            "Stopping…": ("stopping…", COLOR_MUTED),
            "Error":     ("error",     COLOR_RED),
            "Starting…": ("starting…", COLOR_GOLD),
        }
        text, color = label_map.get(status, (status.lower(), COLOR_MUTED))
        self._lbl_bot_status.setText(text)
        self._lbl_bot_status.setStyleSheet(f"color: {color}; {_s}")
        self._dot_bot.setStyleSheet(f"color: {color}; font-size: 9px;")

    def _on_alpaca_status(self, status: str):
        _s = f"{_MONO} font-size: 11px;"
        if "LIVE" in status:
            color = COLOR_RED
        elif "PAPER" in status or "connected" in status.lower():
            color = COLOR_GOLD
        else:
            color = COLOR_MUTED
        self._lbl_alpaca_status.setText(f"Alpaca: {status}")
        self._lbl_alpaca_status.setStyleSheet(f"color: {color}; {_s}")

    def _on_brain_scanner_status(self, status: str):
        _s = f"{_MONO} font-size: 11px;"
        running = any(k in status.lower() for k in ("scan", "llm", "running", "analiz"))
        color   = COLOR_GOLD if running else COLOR_MUTED
        self._lbl_brain_status.setText(status[:60])
        self._lbl_brain_status.setStyleSheet(f"color: {color}; {_s}")
        self._dot_brain.setStyleSheet(f"color: {color}; font-size: 9px;")
        self._tab_brainbot.on_scanner_status(status)

    def _on_journal_updated(self):
        dziennik = self._tab_brainbot._dziennik
        if hasattr(dziennik, "refresh"):
            dziennik.refresh()

    def _on_trade_closed(self, info: dict):
        pnl            = info.get("pnl", 0.0)
        was_recommended = info.get("was_recommended", False)
        symbol         = info.get("symbol", "")
        action         = info.get("action", "")
        if pnl < 0 and was_recommended and symbol:
            self._journal.add_learning_note(
                symbol=symbol,
                predicted=action,
                result=f"LOSS: ${pnl:.2f}",
                lesson=(
                    f"TradeBot closed {action} position for {symbol} at loss ${pnl:.2f}. "
                    "Recommendation was incorrect — technical analysis correction needed."
                ),
            )

    def _open_chart_for_symbol(self, symbol: str):
        self._stack.setCurrentIndex(2)   # Chart page
        self._sidebar.set_index(2)
        self._tab_chart.load_symbol(symbol)

    def _tick_status(self):
        if self._worker.isRunning():
            _s = f"{_MONO} font-size: 11px;"
            now = datetime.now().strftime("%H:%M:%S")
            self._lbl_bot_status.setText(f"running  •  {now}")
            self._lbl_bot_status.setStyleSheet(f"color: {COLOR_GREEN}; {_s}")

    def closeEvent(self, event):
        _unregister_log_callback(self._tab_tradebot.log_append)
        for worker in (self._worker, self._poller, self._news_poller, self._brain_scanner):
            if hasattr(worker, "stop"):
                worker.stop()
            if not worker.wait(5000):
                worker.terminate()
                worker.wait(2000)
        event.accept()
