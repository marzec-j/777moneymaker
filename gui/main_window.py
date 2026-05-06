from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QMainWindow, QTabWidget, QStatusBar, QLabel, QHBoxLayout, QWidget

from .styles import DARK_THEME, COLOR_GREEN, COLOR_RED, COLOR_GOLD, COLOR_MUTED
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


class MainWindow(QMainWindow):
    def __init__(self, config: dict, config_path: str = "config.yaml"):
        super().__init__()
        self._config = config
        self._config_path = config_path

        self.setWindowTitle("777moneymaker — AI Trading System")
        self.resize(1280, 820)
        self.setStyleSheet(DARK_THEME)

        # Współdzielony Brain — thread-safe, używany przez silnik i pollery
        self._brain = SymbolBrain(config)

        # Journal BrainBota — dziennik rekomendacji
        self._journal = BrainJournal(config)

        # BrainBot — ciągły bot AI skanujący cały rynek
        self._brain_scanner = BrainScannerWorker(
            config, brain=self._brain, journal=self._journal
        )

        # TradeBot — bot tradingowy (działa na symbolach z journala)
        self._worker = TradingWorker(config, brain=self._brain, journal=self._journal)

        # Alpaca poller (lekki wątek — tylko account + positions)
        self._poller = AlpacaPoller(config)

        # News poller (co 60s pobiera newsy z Finnhub)
        self._news_poller = NewsPoller(config, brain=self._brain, journal=self._journal)

        # Build UI
        self._build_tabs()
        self._build_statusbar()
        self._connect_signals()
        _register_log_callback(self._tab_tradebot.log_append)

        # Status bar tick
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_status)
        self._timer.start(1000)

        # Uruchom pollery automatycznie; BrainBot i TradeBot startują manualnie
        self._poller.start()
        self._news_poller.start()

    def _build_tabs(self):
        tabs = QTabWidget()
        tabs.setDocumentMode(True)

        self._tab_dashboard = DashboardTab(self._worker, self._config, scanner=self._brain_scanner)
        self._tab_market    = MarketTab(self._config, self._worker, self._poller)
        self._tab_chart     = ChartTab(self._config, self._worker, self._poller)
        self._tab_news      = NewsTab(self._config, self._worker)
        self._tab_settings  = SettingsTab(self._config, self._config_path)

        # BrainBot — podzakładki: Logi, Dziennik, Czat
        self._tab_brainbot = BrainBotTab(
            self._config,
            brain=self._brain,
            worker=self._worker,
            scanner=self._brain_scanner,
            journal=self._journal,
        )

        # TradeBot — podzakładki: Pozycje, Logi, Decyzje
        self._tab_tradebot = TradeBotTab(self._config, self._worker, self._poller)

        tabs.addTab(self._tab_dashboard, "📊  Dashboard")
        tabs.addTab(self._tab_market,    "📈  Market")
        tabs.addTab(self._tab_chart,     "🕯  Chart")
        tabs.addTab(self._tab_brainbot,  "🧠  BrainBot")
        tabs.addTab(self._tab_tradebot,  "🤖  TradeBot")
        tabs.addTab(self._tab_news,      "📰  News")
        tabs.addTab(self._tab_settings,  "⚙️  Settings")

        self.setCentralWidget(tabs)
        self._tabs = tabs

    def _build_statusbar(self):
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        _mono = "font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 11px;"
        _muted = f"color: {COLOR_MUTED}; {_mono}"

        # TradeBot indicator
        self._dot_bot = QLabel("●")
        self._dot_bot.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 9px;")
        self._lbl_bot_label = QLabel("TradeBot:")
        self._lbl_bot_label.setStyleSheet(_muted)
        self._lbl_bot_status = QLabel("stopped")
        self._lbl_bot_status.setStyleSheet(_muted)

        # BrainBot indicator
        self._dot_brain = QLabel("●")
        self._dot_brain.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 9px;")
        self._lbl_brain_label = QLabel("BrainBot:")
        self._lbl_brain_label.setStyleSheet(_muted)
        self._lbl_brain_status = QLabel("initializing…")
        self._lbl_brain_status.setStyleSheet(_muted)

        self._statusbar.addWidget(self._dot_bot)
        self._statusbar.addWidget(self._lbl_bot_label)
        self._statusbar.addWidget(self._lbl_bot_status)
        self._statusbar.addWidget(QLabel("  "))   # spacer
        self._statusbar.addWidget(self._dot_brain)
        self._statusbar.addWidget(self._lbl_brain_label)
        self._statusbar.addWidget(self._lbl_brain_status)

        # Alpaca (right side)
        self._lbl_alpaca_status = QLabel("Alpaca: connecting…")
        self._lbl_alpaca_status.setStyleSheet(_muted)
        self._statusbar.addPermanentWidget(self._lbl_alpaca_status)

    def _connect_signals(self):
        # ── Market tab: double-click → chart ─────────────────────────────
        self._tab_market.symbol_selected.connect(self._open_chart_for_symbol)

        # ── TradeBot (worker) signals ─────────────────────────────────────
        self._worker.status_changed.connect(self._on_bot_status)
        self._worker.error_occurred.connect(
            lambda e: self._lbl_bot_status.setText(f"TradeBot: Error — {e}")
        )
        # Uczenie BrainBota na zamkniętych transakcjach TradeBota
        self._worker.trade_closed.connect(self._on_trade_closed)

        # ── Alpaca poller ─────────────────────────────────────────────────
        self._poller.account_updated.connect(self._tab_dashboard._on_account)
        self._poller.positions_updated.connect(self._tab_dashboard._on_positions)
        self._poller.positions_updated.connect(self._tab_chart._on_positions_updated)
        self._poller.positions_updated.connect(self._tab_market.update_positions)
        self._poller.status_changed.connect(self._on_alpaca_status)

        # ── Poller → pozycje w TradeBot tab ──────────────────────────────
        self._poller.positions_updated.connect(self._tab_tradebot.update_positions)

        # ── Worker → dashboard / chart / market / tradebot ────────────────
        self._worker.account_updated.connect(self._tab_dashboard._on_account)
        self._worker.positions_updated.connect(self._tab_dashboard._on_positions)
        self._worker.positions_updated.connect(self._tab_tradebot.update_positions)
        self._worker.positions_updated.connect(self._tab_chart._on_positions_updated)
        self._worker.positions_updated.connect(self._tab_market.update_positions)

        # ── Refresh buttons ───────────────────────────────────────────────
        self._tab_dashboard.refresh_requested.connect(self._poller.force_refresh)
        self._tab_tradebot.refresh_requested.connect(self._poller.force_refresh)

        # ── Settings saved → poller reconnect ────────────────────────────
        self._tab_settings.settings_saved.connect(self._poller.reconnect)

        # ── News poller ───────────────────────────────────────────────────
        self._news_poller.news_updated.connect(self._tab_news.on_news_updated)

        # ── BrainBot scanner → BrainBotTab ───────────────────────────────
        self._brain_scanner.status_updated.connect(self._on_brain_scanner_status)
        self._brain_scanner.scan_completed.connect(self._tab_brainbot.on_scan_completed)
        self._brain_scanner.journal_updated.connect(self._on_journal_updated)

        # ── Chart ─────────────────────────────────────────────────────────
        self._tab_chart.symbols_changed.connect(self._tab_market.update_watchlist)
        self._poller.account_updated.connect(self._on_first_poller_data)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_first_poller_data(self, acc: dict):
        self._poller.account_updated.disconnect(self._on_first_poller_data)
        self._tab_chart.on_poller_ready()

    def _on_bot_status(self, status: str):
        _mono = "font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 11px;"
        label_map = {
            "Running":   ("running",     COLOR_GREEN),
            "Stopped":   ("stopped",     COLOR_MUTED),
            "Stopping…": ("stopping…",   COLOR_MUTED),
            "Error":     ("error",       COLOR_RED),
            "Starting…": ("starting…",   COLOR_GOLD),
        }
        text, color = label_map.get(status, (status.lower(), COLOR_MUTED))
        self._lbl_bot_status.setText(text)
        self._lbl_bot_status.setStyleSheet(f"color: {color}; {_mono}")
        self._dot_bot.setStyleSheet(
            f"color: {color}; font-size: 9px;"
            + (" qproperty-text: '●';" if status == "Running" else "")
        )

    def _on_alpaca_status(self, status: str):
        _mono = "font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 11px;"
        if "LIVE" in status:
            color = COLOR_RED
        elif "PAPER" in status or "connected" in status.lower():
            color = COLOR_GOLD
        else:
            color = COLOR_MUTED
        self._lbl_alpaca_status.setText(f"Alpaca: {status}")
        self._lbl_alpaca_status.setStyleSheet(f"color: {color}; {_mono}")

    def _on_brain_scanner_status(self, status: str):
        _mono = "font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 11px;"
        short = status[:60]
        running = any(k in status.lower() for k in ("scan", "llm", "running", "analiz"))
        color = COLOR_GOLD if running else COLOR_MUTED
        self._lbl_brain_status.setText(short)
        self._lbl_brain_status.setStyleSheet(f"color: {color}; {_mono}")
        self._dot_brain.setStyleSheet(f"color: {color}; font-size: 9px;")
        self._tab_brainbot.on_scanner_status(status)

    def _on_journal_updated(self):
        """Odświeżenie zakładki Dziennik po każdym cyklu skanowania BrainBota."""
        # JournalWidget ma własny timer, ale możemy wymusić odświeżenie
        dziennik = self._tab_brainbot._dziennik
        if hasattr(dziennik, "refresh"):
            dziennik.refresh()

    def _on_trade_closed(self, info: dict):
        """Uczenie BrainBota: zapis notatki gdy TradeBot zamknął stratną pozycję."""
        pnl            = info.get("pnl", 0.0)
        was_recommended = info.get("was_recommended", False)
        symbol         = info.get("symbol", "")
        action         = info.get("action", "")

        if pnl < 0 and was_recommended and symbol:
            lesson = (
                f"TradeBot closed {action} position for {symbol} at loss ${pnl:.2f}. "
                f"Recommendation was incorrect — technical analysis correction needed."
            )
            self._journal.add_learning_note(
                symbol=symbol,
                predicted=action,
                result=f"LOSS: ${pnl:.2f}",
                lesson=lesson,
            )

    def _open_chart_for_symbol(self, symbol: str):
        self._tabs.setCurrentWidget(self._tab_chart)
        self._tab_chart.load_symbol(symbol)

    def _tick_status(self):
        if self._worker.isRunning():
            from datetime import datetime
            now = datetime.now().strftime("%H:%M:%S")
            self._lbl_bot_status.setText(f"TradeBot: running  •  {now}")

    def closeEvent(self, event):
        _unregister_log_callback(self._tab_tradebot.log_append)
        if self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(5000)
            if self._worker.isRunning():
                self._worker.terminate()
                self._worker.wait(2000)
        self._poller.stop()
        if not self._poller.wait(5000):
            self._poller.terminate()
            self._poller.wait(2000)
        self._news_poller.stop()
        if not self._news_poller.wait(5000):
            self._news_poller.terminate()
            self._news_poller.wait(2000)
        self._brain_scanner.stop()
        if not self._brain_scanner.wait(5000):
            self._brain_scanner.terminate()
            self._brain_scanner.wait(2000)
        event.accept()
