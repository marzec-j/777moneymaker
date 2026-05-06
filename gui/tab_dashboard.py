from __future__ import annotations

import csv
import time
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from .styles import COLOR_GREEN, COLOR_RED, COLOR_MUTED, COLOR_BG, COLOR_PANEL, COLOR_BORDER, COLOR_GOLD, COLOR_FG, make_page_header
from . import log_action


def _card(parent=None) -> QFrame:
    f = QFrame(parent)
    f.setObjectName("card")
    f.setFrameShape(QFrame.StyledPanel)
    return f


def _stat_card(title: str, value: str = "—", color: str = "#e2e8f0"):
    card = _card()
    lay = QVBoxLayout(card)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(6)
    lbl_title = QLabel(title.upper())
    lbl_title.setStyleSheet(
        f"color: {COLOR_MUTED}; font-size: 10px; font-weight: 600; letter-spacing: 0.8px;"
    )
    lbl_val = QLabel(value)
    lbl_val.setStyleSheet(
        f"font-size: 24px; font-weight: 700; color: {color};"
        " font-family: 'JetBrains Mono', 'Consolas', monospace;"
    )
    lay.addWidget(lbl_title)
    lay.addWidget(lbl_val)
    return card, lbl_val


class DashboardTab(QWidget):
    refresh_requested = Signal()

    def __init__(self, worker, config: dict, scanner=None, parent=None):
        super().__init__(parent)
        self._worker  = worker
        self._scanner = scanner
        self._config  = config

        self._start_equity: float | None = None
        self._equity_times:  list[float] = []
        self._equity_values: list[float] = []
        self._session_start: float = time.time()

        _data_cfg = config.get("data", {})
        self._trades_path = (
            Path(_data_cfg.get("data_dir", "data")).resolve()
            / _data_cfg.get("trades_file", "trades.csv")
        )
        self._setup_ui()
        self._connect_signals()

    # ── UI ────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        inner = QWidget()
        scroll.setWidget(inner)

        root = QVBoxLayout(inner)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # ── 0. Page header ────────────────────────────────────────────────
        root.addWidget(make_page_header("Dashboard", "Przegląd systemu handlowego"))

        # ── 1. Stat cards ─────────────────────────────────────────────────
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)

        self._card_cash,   self._lbl_cash   = _stat_card("Available Cash",   "—")
        self._card_stocks, self._lbl_stocks = _stat_card("Portfolio Value", "—")
        self._card_pos,    self._lbl_pos    = _stat_card("Open Positions", "0")
        self._card_pnl,    self._lbl_pnl    = _stat_card("Daily P&L",       "$0.00")

        for card in (self._card_cash, self._card_stocks, self._card_pos, self._card_pnl):
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            cards_row.addWidget(card)

        root.addLayout(cards_row)

        # ── 2. TradeBot status ────────────────────────────────────────────
        tb_card = _card()
        tb_lay  = QHBoxLayout(tb_card)
        tb_lay.setContentsMargins(16, 12, 16, 12)

        lbl_tb = QLabel("TRADEBOT")
        lbl_tb.setStyleSheet(
            f"color: {COLOR_MUTED}; font-size: 10px; font-weight: 600; letter-spacing: 0.8px;"
        )

        self._lbl_status = QLabel("Stopped")
        self._lbl_status.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {COLOR_MUTED};"
            " font-family: 'JetBrains Mono', 'Consolas', monospace;"
        )

        self._lbl_mode = QLabel(self._mode_label())
        self._lbl_mode.setStyleSheet(f"font-size: 11px; color: {COLOR_MUTED};")

        self._btn_refresh = QPushButton("↻")
        self._btn_refresh.setFixedSize(36, 36)
        self._btn_refresh.setToolTip("Refresh data from Alpaca")
        self._btn_refresh.clicked.connect(self._on_refresh_clicked)

        self._btn_start = QPushButton("▶  Start")
        self._btn_start.setObjectName("btn_start")
        self._btn_start.setFixedWidth(110)

        self._btn_stop = QPushButton("■  Stop")
        self._btn_stop.setObjectName("btn_stop")
        self._btn_stop.setFixedWidth(110)
        self._btn_stop.setEnabled(False)

        self._btn_start.clicked.connect(self._start_bot)
        self._btn_stop.clicked.connect(self._stop_bot)

        tb_lay.addWidget(lbl_tb)
        tb_lay.addWidget(self._lbl_status)
        tb_lay.addSpacing(12)
        tb_lay.addWidget(self._lbl_mode)
        tb_lay.addStretch()
        tb_lay.addWidget(self._btn_refresh)
        tb_lay.addSpacing(6)
        tb_lay.addWidget(self._btn_start)
        tb_lay.addWidget(self._btn_stop)

        root.addWidget(tb_card)

        # ── 3. BrainBot status ────────────────────────────────────────────
        brain_card = _card()
        brain_lay  = QHBoxLayout(brain_card)
        brain_lay.setContentsMargins(16, 12, 16, 12)

        lbl_bb = QLabel("BRAINBOT")
        lbl_bb.setStyleSheet(
            f"color: {COLOR_MUTED}; font-size: 10px; font-weight: 600; letter-spacing: 0.8px;"
        )

        self._lbl_brain_status = QLabel("Stopped")
        self._lbl_brain_status.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {COLOR_MUTED};"
            " font-family: 'JetBrains Mono', 'Consolas', monospace;"
        )

        self._lbl_brain_info = QLabel("—")
        self._lbl_brain_info.setStyleSheet(f"font-size: 11px; color: {COLOR_MUTED};")

        self._btn_brain_start = QPushButton("▶  Start")
        self._btn_brain_start.setObjectName("btn_start")
        self._btn_brain_start.setFixedWidth(110)

        self._btn_brain_stop = QPushButton("■  Stop")
        self._btn_brain_stop.setObjectName("btn_stop")
        self._btn_brain_stop.setFixedWidth(110)
        self._btn_brain_stop.setEnabled(False)

        self._btn_brain_start.clicked.connect(self._start_brain)
        self._btn_brain_stop.clicked.connect(self._stop_brain)

        brain_lay.addWidget(lbl_bb)
        brain_lay.addWidget(self._lbl_brain_status)
        brain_lay.addSpacing(12)
        brain_lay.addWidget(self._lbl_brain_info)
        brain_lay.addStretch()
        brain_lay.addWidget(self._btn_brain_start)
        brain_lay.addWidget(self._btn_brain_stop)

        root.addWidget(brain_card)

        # ── 4. Equity chart ───────────────────────────────────────────────
        chart_card = _card()
        chart_lay  = QVBoxLayout(chart_card)
        chart_lay.setContentsMargins(16, 12, 16, 12)
        chart_lay.setSpacing(6)

        chart_hdr = QHBoxLayout()
        lbl_chart = QLabel("SESSION EQUITY")
        lbl_chart.setStyleSheet(
            f"color: {COLOR_MUTED}; font-size: 10px; font-weight: 600; letter-spacing: 0.8px;"
        )
        self._lbl_equity_hdr = QLabel("—")
        self._lbl_equity_hdr.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {COLOR_FG};"
            " font-family: 'JetBrains Mono', 'Consolas', monospace;"
        )
        chart_hdr.addWidget(lbl_chart)
        chart_hdr.addStretch()
        chart_hdr.addWidget(self._lbl_equity_hdr)
        chart_lay.addLayout(chart_hdr)

        self._equity_plot = pg.PlotWidget(background="#0c1421")
        self._equity_plot.setFixedHeight(190)
        self._equity_plot.showGrid(x=False, y=True, alpha=0.12)
        self._equity_plot.getPlotItem().hideAxis("bottom")
        self._equity_plot.getPlotItem().getAxis("left").setStyle(tickTextOffset=4)
        self._equity_plot.setMouseEnabled(x=False, y=False)
        self._equity_plot.setMenuEnabled(False)

        # zero baseline
        self._equity_plot.addItem(
            pg.InfiniteLine(
                angle=0, movable=False,
                pen=pg.mkPen(COLOR_MUTED, width=1, style=Qt.DashLine),
            )
        )

        # equity line (filled to 0)
        self._equity_curve = self._equity_plot.plot(
            [], [],
            pen=pg.mkPen(COLOR_GREEN, width=2),
            fillLevel=0.0,
            brush=pg.mkBrush(QColor(81, 207, 102, 20)),
        )

        chart_lay.addWidget(self._equity_plot)
        root.addWidget(chart_card)

        # ── 5. Recent trades ──────────────────────────────────────────────
        trades_card = _card()
        trades_lay  = QVBoxLayout(trades_card)
        trades_lay.setContentsMargins(16, 12, 16, 12)
        trades_lay.setSpacing(8)

        lbl_trades = QLabel("RECENT TRADES")
        lbl_trades.setStyleSheet(
            f"color: {COLOR_MUTED}; font-size: 10px; font-weight: 600; letter-spacing: 0.8px;"
        )
        trades_lay.addWidget(lbl_trades)

        cols = ["Czas", "Symbol", "Akcja", "Qty", "Cena", "SL", "TP", "Pewność"]
        self._trades_table = QTableWidget(0, len(cols))
        self._trades_table.setHorizontalHeaderLabels(cols)
        self._trades_table.verticalHeader().setVisible(False)
        self._trades_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._trades_table.horizontalHeader().setStretchLastSection(True)
        self._trades_table.setFixedHeight(220)
        trades_lay.addWidget(self._trades_table)

        root.addWidget(trades_card)

        # ── 6. Last AI signal ─────────────────────────────────────────────
        signal_card = _card()
        signal_lay  = QVBoxLayout(signal_card)
        signal_lay.setContentsMargins(16, 12, 16, 12)
        signal_lay.setSpacing(6)

        lbl_sig = QLabel("OSTATNI SYGNAŁ AI")
        lbl_sig.setStyleSheet(
            f"color: {COLOR_MUTED}; font-size: 10px; font-weight: 600; letter-spacing: 0.8px;"
        )

        self._lbl_last_signal = QLabel("Brak sygnałów")
        self._lbl_last_signal.setStyleSheet(
            f"font-size: 12px; color: {COLOR_FG};"
            " font-family: 'JetBrains Mono', 'Consolas', monospace;"
        )
        self._lbl_last_signal.setWordWrap(True)

        signal_lay.addWidget(lbl_sig)
        signal_lay.addWidget(self._lbl_last_signal)

        root.addWidget(signal_card)
        root.addStretch()

    # ── Signals ───────────────────────────────────────────────────────────

    def _connect_signals(self):
        self._worker.account_updated.connect(self._on_account)
        self._worker.positions_updated.connect(self._on_positions)
        self._worker.status_changed.connect(self._on_status)
        self._worker.log_emitted.connect(self._on_log)
        self._worker.cycle_done.connect(self._reload_trades)

        if self._scanner is not None:
            self._scanner.status_updated.connect(self._on_brain_info)
            self._scanner.started.connect(self._on_brain_started)
            self._scanner.finished.connect(self._on_brain_finished)

        self._reload_trades()

    # ── Helpers ───────────────────────────────────────────────────────────

    def _mode_label(self) -> str:
        mode = self._config.get("alpaca_mode", "paper")
        return "Tryb: PAPER (Alpaca)" if mode == "paper" else "Tryb: LIVE (Alpaca)"

    def _reload_trades(self):
        rows = []
        try:
            if self._trades_path.exists():
                with open(self._trades_path, newline="", encoding="utf-8") as f:
                    rows = list(csv.DictReader(f))
        except Exception:
            pass

        self._trades_table.setRowCount(0)
        for row in reversed(rows[-20:]):
            r = self._trades_table.rowCount()
            self._trades_table.insertRow(r)

            action = row.get("action", "")
            col = (COLOR_GREEN if action in ("BUY", "COVER", "TP_EXIT")
                   else COLOR_RED if action in ("SELL", "SHORT", "SL_EXIT")
                   else COLOR_FG)

            def _item(text, align=Qt.AlignRight, fg=None):
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(align | Qt.AlignVCenter)
                if fg:
                    it.setForeground(QColor(fg))
                return it

            ts = row.get("timestamp", "")[:16].replace("T", " ")
            try:
                conf_str = f"{float(row.get('confidence', 0)):.0%}"
            except (ValueError, TypeError):
                conf_str = row.get("confidence", "")

            def _price(key):
                try:
                    return f"${float(row[key]):,.2f}" if row.get(key) else "—"
                except (ValueError, TypeError):
                    return "—"

            self._trades_table.setItem(r, 0, _item(ts, Qt.AlignLeft))
            self._trades_table.setItem(r, 1, _item(row.get("symbol", ""), Qt.AlignCenter))
            self._trades_table.setItem(r, 2, _item(action, Qt.AlignCenter, col))
            self._trades_table.setItem(r, 3, _item(row.get("qty", "")))
            self._trades_table.setItem(r, 4, _item(_price("price")))
            self._trades_table.setItem(r, 5, _item(_price("stop_loss")))
            self._trades_table.setItem(r, 6, _item(_price("take_profit")))
            self._trades_table.setItem(r, 7, _item(conf_str, Qt.AlignCenter))

    def _update_equity_chart(self):
        if len(self._equity_values) < 2:
            return

        baseline = self._equity_values[0]
        xs = self._equity_times
        ys  = [v - baseline for v in self._equity_values]
        pnl = ys[-1]

        color = COLOR_GREEN if pnl >= 0 else COLOR_RED
        brush = (QColor(81, 207, 102, 20) if pnl >= 0 else QColor(240, 62, 62, 20))

        self._equity_curve.setPen(pg.mkPen(color, width=2))
        self._equity_curve.setBrush(pg.mkBrush(brush))
        self._equity_curve.setData(xs, ys)

        pct  = (pnl / baseline * 100) if baseline else 0.0
        sign = "+" if pnl >= 0 else ""
        self._lbl_equity_hdr.setText(
            f"${self._equity_values[-1]:,.2f}   {sign}${pnl:,.2f} ({sign}{pct:.2f}%)"
        )
        self._lbl_equity_hdr.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {color};"
        )

    # ── Slots ─────────────────────────────────────────────────────────────

    def _on_account(self, acc: dict):
        equity = acc.get("equity", 0.0)
        cash   = acc.get("cash", 0.0)
        stocks = acc.get("portfolio_value", 0.0)

        _mono = "font-size: 24px; font-weight: 700; font-family: 'JetBrains Mono', 'Consolas', monospace;"
        self._lbl_cash.setText(f"${cash:,.2f}")
        self._lbl_cash.setStyleSheet(f"{_mono} color: {COLOR_FG};")
        self._lbl_stocks.setText(f"${stocks:,.2f}")
        self._lbl_stocks.setStyleSheet(f"{_mono} color: {COLOR_FG};")

        if self._start_equity is None:
            self._start_equity = equity
        daily_pnl = equity - self._start_equity
        color = COLOR_GREEN if daily_pnl >= 0 else COLOR_RED
        self._lbl_pnl.setText(f"${daily_pnl:+,.2f}")
        self._lbl_pnl.setStyleSheet(
            f"font-size: 24px; font-weight: 700; color: {color};"
            " font-family: 'JetBrains Mono', 'Consolas', monospace;"
        )

        t = time.time() - self._session_start
        self._equity_times.append(t)
        self._equity_values.append(float(equity))
        if len(self._equity_times) > 500:
            self._equity_times  = self._equity_times[-500:]
            self._equity_values = self._equity_values[-500:]
        self._update_equity_chart()

    def _on_positions(self, positions: list):
        self._lbl_pos.setText(str(len(positions)))

    def _on_status(self, status: str):
        _base = "font-size: 14px; font-weight: 700; font-family: 'JetBrains Mono', 'Consolas', monospace;"
        labels = {
            "Running":   ("Działa",      COLOR_GREEN),
            "Stopped":   ("Zatrzymany",  COLOR_MUTED),
            "Stopping…": ("Zatrzymuję…", COLOR_MUTED),
            "Error":     ("Błąd",        COLOR_RED),
            "Starting…": ("Startuje…",   COLOR_GOLD),
        }
        text, color = labels.get(status, (status, COLOR_FG))
        self._lbl_status.setText(text)
        self._lbl_status.setStyleSheet(f"{_base} color: {color};")
        running = status == "Running"
        self._btn_start.setEnabled(not running)
        self._btn_stop.setEnabled(running)
        if status == "Stopped":
            self._start_equity = None

    def _on_log(self, level: str, message: str):
        if "LLM →" in message or "TRADE" in message:
            self._lbl_last_signal.setText(message)

    def _on_refresh_clicked(self):
        log_action("Odświeżono dane konta")
        self.refresh_requested.emit()

    def _start_bot(self):
        if not self._worker.isRunning():
            log_action("Uruchomiono bota")
            self._lbl_mode.setText(self._mode_label())
            self._worker.start()

    def _stop_bot(self):
        log_action("Zatrzymano bota")
        self._worker.stop()

    def _start_brain(self):
        if self._scanner and not self._scanner.isRunning():
            log_action("Uruchomiono BrainBota")
            self._scanner.start()

    def _stop_brain(self):
        if self._scanner:
            log_action("Zatrzymano BrainBota")
            self._scanner.stop()

    def _on_brain_info(self, status: str):
        self._lbl_brain_info.setText(status[:80])

    def _on_brain_started(self):
        _base = "font-size: 14px; font-weight: 700; font-family: 'JetBrains Mono', 'Consolas', monospace;"
        self._lbl_brain_status.setText("Działa")
        self._lbl_brain_status.setStyleSheet(f"{_base} color: {COLOR_GOLD};")
        self._btn_brain_start.setEnabled(False)
        self._btn_brain_stop.setEnabled(True)

    def _on_brain_finished(self):
        _base = "font-size: 14px; font-weight: 700; font-family: 'JetBrains Mono', 'Consolas', monospace;"
        self._lbl_brain_status.setText("Zatrzymany")
        self._lbl_brain_status.setStyleSheet(f"{_base} color: {COLOR_MUTED};")
        self._btn_brain_start.setEnabled(True)
        self._btn_brain_stop.setEnabled(False)
        self._lbl_brain_info.setText("—")