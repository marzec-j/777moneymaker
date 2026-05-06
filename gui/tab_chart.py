from __future__ import annotations

import math
import numpy as np
from datetime import datetime

import pyqtgraph as pg
from PySide6.QtCore import Qt, QThread, Signal, QObject, QEvent
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPicture, QPen, QBrush, QCursor
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMenu, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from .styles import (
    COLOR_BG, COLOR_PANEL, COLOR_CARD, COLOR_BORDER,
    COLOR_GREEN, COLOR_RED, COLOR_MUTED, make_page_header,
)
from . import log_action

pg.setConfigOption("background", COLOR_BG)
pg.setConfigOption("foreground", "#e2e8f0")
pg.setConfigOption("antialias", True)

# columns per layout button value
GRID_COLS = {1: 1, 4: 2, 6: 3, 8: 4}
# max panels shown in multi-chart mode
GRID_MAX  = {1: 1, 4: 4, 6: 6, 8: 8}
_CROSSHAIR_PEN = pg.mkPen("#606060", width=1, style=Qt.DashLine)


# ── Candlestick item ──────────────────────────────────────────────────────────

class CandlestickItem(pg.GraphicsObject):
    def __init__(self):
        super().__init__()
        self._picture = QPicture()
        self._data: list[tuple] = []

    def set_data(self, data: list[tuple]):
        self._data = data
        self._generate()
        self.prepareGeometryChange()
        self.update()

    def _generate(self):
        self._picture = QPicture()
        p = QPainter(self._picture)
        p.setRenderHint(QPainter.Antialiasing, False)
        w = 0.35
        bull_pen = QPen(QColor(COLOR_GREEN)); bull_pen.setWidthF(0)
        bull_brush = QBrush(QColor(COLOR_GREEN))
        bear_pen = QPen(QColor(COLOR_RED)); bear_pen.setWidthF(0)
        bear_brush = QBrush(QColor(COLOR_RED))
        for x, o, h, l, c in self._data:
            if c >= o:
                p.setPen(bull_pen); p.setBrush(bull_brush)
            else:
                p.setPen(bear_pen); p.setBrush(bear_brush)
            p.drawLine(QPointF(x, l), QPointF(x, h))
            body_h = abs(c - o) or 0.001
            p.drawRect(QRectF(x - w, min(o, c), w * 2, body_h))
        p.end()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self._picture)

    def boundingRect(self):
        return QRectF(self._picture.boundingRect())


# ── Mouse-leave detector ──────────────────────────────────────────────────────

class _LeaveFilter(QObject):
    def __init__(self, callback):
        super().__init__()
        self._cb = callback

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Leave:
            self._cb()
        return False


# ── Background loader ─────────────────────────────────────────────────────────

class ChartLoader(QThread):
    data_ready = Signal(str, object)

    def __init__(self, config: dict, symbol: str, broker=None):
        super().__init__()
        self._config = config
        self._symbol = symbol
        self._broker = broker

    def run(self):
        try:
            from modules.market_data import MarketDataFetcher
            fetcher = MarketDataFetcher(self._config, self._broker)
            df = fetcher.fetch_ohlcv_with_indicators(self._symbol)
            if df is not None and not df.empty:
                self.data_ready.emit(self._symbol, df)
                return
        except Exception as exc:
            import logging
            logging.getLogger("777moneymaker").warning(
                f"ChartLoader {self._symbol}: {exc}", exc_info=True)
        self.data_ready.emit(self._symbol, None)


# ── Single chart panel ────────────────────────────────────────────────────────

class ChartPanel(QFrame):
    """Candles + EMA20/50 + crosshair + hover tooltip + SL/TP/entry markers."""

    symbol_clicked = Signal(str)   # emitted when symbol button is clicked

    def __init__(self, symbol: str, compact: bool = False, parent=None):
        super().__init__(parent)
        self.symbol = symbol
        self._compact = compact
        self._df = None
        self._updating_range = False
        self.setObjectName("card")
        self.setFrameShape(QFrame.StyledPanel)
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 2)
        lay.setSpacing(2)

        # ── Header ────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setContentsMargins(4, 2, 4, 0)

        # Symbol name → clickable QPushButton styled as label
        self._lbl_symbol = QPushButton(self.symbol)
        self._lbl_symbol.setFlat(True)
        self._lbl_symbol.setCursor(Qt.PointingHandCursor)
        self._lbl_symbol.setFixedWidth(72)
        self._lbl_symbol.setStyleSheet(
            "QPushButton { font-size: 13px; font-weight: bold; color: #d4d4d4;"
            " background: transparent; border: none; text-align: left; padding: 0; }"
            "QPushButton:hover { color: #74c0fc; }"
        )
        self._lbl_symbol.clicked.connect(lambda: self.symbol_clicked.emit(self.symbol))

        self._lbl_price = QLabel("—")
        self._lbl_price.setStyleSheet(f"font-size: 12px; color: {COLOR_MUTED};")

        self._lbl_pnl = QLabel("")
        self._lbl_pnl.setStyleSheet("font-size: 11px;")

        self._lbl_hover = QLabel("")
        self._lbl_hover.setStyleSheet("font-size: 11px;")

        self._lbl_markers = QLabel("")
        self._lbl_markers.setStyleSheet(f"font-size: 10px; color: {COLOR_MUTED};")

        hdr.addWidget(self._lbl_symbol)
        hdr.addSpacing(6)
        hdr.addWidget(self._lbl_price)
        hdr.addSpacing(6)
        hdr.addWidget(self._lbl_pnl)
        hdr.addSpacing(10)
        hdr.addWidget(self._lbl_hover, 1)
        hdr.addWidget(self._lbl_markers)
        lay.addLayout(hdr)

        # ── Price plot ────────────────────────────────────────────────────
        self._plot = pg.PlotWidget()
        self._plot.showGrid(x=True, y=True, alpha=0.13)
        self._plot.getAxis("left").setWidth(62)
        self._plot.getAxis("bottom").setStyle(showValues=not self._compact)
        self._plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self._plot, 1)

        self._candles = CandlestickItem()
        self._plot.addItem(self._candles)
        self._ema20 = self._plot.plot(pen=pg.mkPen("#74c0fc", width=1.2), name="EMA20")
        self._ema50 = self._plot.plot(pen=pg.mkPen("#eab308", width=1.2), name="EMA50")

        self._entry_scatter = pg.ScatterPlotItem(
            symbol="t1", size=16,
            brush=pg.mkBrush(COLOR_GREEN),
            pen=pg.mkPen("#ffffff", width=1),
        )
        self._plot.addItem(self._entry_scatter)

        self._sl_line = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen(COLOR_RED, width=1.5, style=Qt.DashLine),
            label="SL", labelOpts={"color": COLOR_RED, "position": 0.02},
        )
        self._tp_line = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen(COLOR_GREEN, width=1.5, style=Qt.DashLine),
            label="TP", labelOpts={"color": COLOR_GREEN, "position": 0.02},
        )
        self._sl_line.setVisible(False)
        self._tp_line.setVisible(False)
        self._plot.addItem(self._sl_line)
        self._plot.addItem(self._tp_line)

        # Crosshair
        self._vline = pg.InfiniteLine(angle=90, movable=False, pen=_CROSSHAIR_PEN)
        self._hline = pg.InfiniteLine(angle=0,  movable=False, pen=_CROSSHAIR_PEN)
        self._vline.setVisible(False)
        self._hline.setVisible(False)
        self._plot.addItem(self._vline, ignoreBounds=True)
        self._plot.addItem(self._hline, ignoreBounds=True)

        # ── Sub-plots (full / single-column mode) ─────────────────────────
        if not self._compact:
            self._vol_plot = pg.PlotWidget()
            self._vol_plot.showGrid(x=True, y=True, alpha=0.1)
            self._vol_plot.setMaximumHeight(80)
            self._vol_plot.getAxis("left").setWidth(62)
            self._vol_bars = pg.BarGraphItem(x=[], height=[], width=0.7,
                                              brush=pg.mkBrush("#555555"))
            self._vol_plot.addItem(self._vol_bars)
            self._vol_plot.setXLink(self._plot)
            lay.addWidget(self._vol_plot)

            self._vline_vol = pg.InfiniteLine(angle=90, movable=False, pen=_CROSSHAIR_PEN)
            self._vline_vol.setVisible(False)
            self._vol_plot.addItem(self._vline_vol, ignoreBounds=True)

            self._rsi_plot = pg.PlotWidget()
            self._rsi_plot.showGrid(x=True, y=True, alpha=0.1)
            self._rsi_plot.setMaximumHeight(90)
            self._rsi_plot.setYRange(0, 100)
            self._rsi_plot.getAxis("left").setWidth(62)
            for lvl, col in [(70, COLOR_RED), (30, COLOR_GREEN)]:
                self._rsi_plot.addItem(
                    pg.InfiniteLine(pos=lvl, angle=0,
                                    pen=pg.mkPen(col, width=1, style=Qt.DashLine))
                )
            self._rsi_line = self._rsi_plot.plot(
                pen=pg.mkPen("#cc99ff", width=1.5), name="RSI(14)")
            self._rsi_plot.setXLink(self._plot)
            lay.addWidget(self._rsi_plot)

            self._vline_rsi = pg.InfiniteLine(angle=90, movable=False, pen=_CROSSHAIR_PEN)
            self._vline_rsi.setVisible(False)
            self._rsi_plot.addItem(self._vline_rsi, ignoreBounds=True)

        # ── Mouse tracking ────────────────────────────────────────────────
        self._proxies: list[pg.SignalProxy] = []
        self._leave_filters: list[_LeaveFilter] = []
        plots = [self._plot]
        is_price = [True]
        if not self._compact:
            plots += [self._vol_plot, self._rsi_plot]
            is_price += [False, False]
        for pw, ip in zip(plots, is_price):
            proxy = pg.SignalProxy(
                pw.scene().sigMouseMoved, rateLimit=60,
                slot=self._make_handler(pw, ip),
            )
            self._proxies.append(proxy)
            lf = _LeaveFilter(self._clear_crosshair)
            self._leave_filters.append(lf)
            pw.viewport().installEventFilter(lf)

        self._plot.getPlotItem().vb.sigXRangeChanged.connect(self._on_x_range_changed)

    def _make_handler(self, plot_w: pg.PlotWidget, is_price: bool):
        def handler(evt):
            pos = evt[0]
            if not plot_w.sceneBoundingRect().contains(pos):
                self._clear_crosshair()
                return
            mp = plot_w.getPlotItem().vb.mapSceneToView(pos)
            xi = int(round(mp.x()))
            if self._df is None or not (0 <= xi < len(self._df)):
                self._clear_crosshair()
                return
            self._vline.setPos(xi); self._vline.setVisible(True)
            if is_price:
                self._hline.setPos(mp.y()); self._hline.setVisible(True)
            else:
                self._hline.setVisible(False)
            if not self._compact:
                self._vline_vol.setPos(xi); self._vline_vol.setVisible(True)
                self._vline_rsi.setPos(xi); self._vline_rsi.setVisible(True)
            self._update_hover_label(xi)
        return handler

    # ── Hover label ───────────────────────────────────────────────────────

    def _update_hover_label(self, xi: int):
        if self._df is None or not (0 <= xi < len(self._df)):
            return
        row = self._df.iloc[xi]
        try:
            date_str = str(self._df.index[xi].date())
        except Exception:
            date_str = str(self._df.index[xi])

        o = float(row["Open"]); h = float(row["High"])
        l = float(row["Low"]);  c = float(row["Close"])
        v = int(row["Volume"])
        chg = c - o
        chg_pct = chg / o * 100 if o != 0 else 0
        c_col = COLOR_GREEN if chg >= 0 else COLOR_RED
        vol_str = f"{v/1_000_000:.2f}M" if v >= 1_000_000 else f"{v/1_000:.0f}K"

        parts = [
            f"<b>{date_str}</b>",
            f"O:<b>{o:,.2f}</b>",
            f"H:<b>{h:,.2f}</b>",
            f"L:<b>{l:,.2f}</b>",
            f"C:<b style='color:{c_col}'>{c:,.2f}</b>",
            f"<span style='color:{c_col}'>({chg:+.2f} {chg_pct:+.1f}%)</span>",
            f"Vol:<b>{vol_str}</b>",
        ]
        if not self._compact and "rsi" in self._df.columns:
            rsi = float(row["rsi"])
            if not np.isnan(rsi):
                rc = COLOR_RED if rsi > 70 else (COLOR_GREEN if rsi < 30 else COLOR_MUTED)
                parts.append(f"RSI:<b style='color:{rc}'>{rsi:.1f}</b>")

        self._lbl_hover.setText("  ".join(parts))

    def _clear_crosshair(self):
        self._vline.setVisible(False)
        self._hline.setVisible(False)
        if not self._compact:
            self._vline_vol.setVisible(False)
            self._vline_rsi.setVisible(False)
        self._lbl_hover.setText("")

    # ── Zoom / ticks ──────────────────────────────────────────────────────

    def _on_x_range_changed(self):
        if self._updating_range or self._df is None:
            return
        self._update_date_ticks()
        if not self._compact:
            self._auto_fit_y()

    def _update_date_ticks(self):
        if self._df is None:
            return
        n = len(self._df)
        x_min, x_max = self._plot.getPlotItem().vb.viewRange()[0]
        visible = max(1, int(x_max - x_min))
        if visible <= 10:   step = 1
        elif visible <= 30: step = 2
        elif visible <= 60: step = 5
        elif visible <= 120: step = 10
        elif visible <= 250: step = 20
        else: step = max(1, visible // 10)

        dates = [str(self._df.index[i].date()) for i in range(n)]
        ticks = [(i, dates[i]) for i in range(0, n, step) if 0 <= i < n]
        plots = [self._plot]
        if not self._compact:
            plots += [self._vol_plot, self._rsi_plot]
        for pl in plots:
            pl.getAxis("bottom").setTicks([ticks])

    def _auto_fit_y(self):
        if self._df is None:
            return
        self._updating_range = True
        try:
            x_min, x_max = self._plot.getPlotItem().vb.viewRange()[0]
            n = len(self._df)
            xi0 = max(0, int(x_min))
            xi1 = min(n, int(x_max) + 2)
            if xi0 >= xi1:
                return
            highs = self._df["High"].iloc[xi0:xi1].values
            lows  = self._df["Low"].iloc[xi0:xi1].values
            pad = (highs.max() - lows.min()) * 0.05
            self._plot.setYRange(float(lows.min() - pad),
                                  float(highs.max() + pad), padding=0)
        finally:
            self._updating_range = False

    # ── Public API ────────────────────────────────────────────────────────

    def set_symbol_style(self, has_position: bool):
        """Highlight symbol label when an open position exists."""
        if has_position:
            self._lbl_symbol.setStyleSheet(
                f"QPushButton {{ font-size: 13px; font-weight: bold; color: {COLOR_GREEN};"
                " background: transparent; border: none; text-align: left; padding: 0; }"
                f"QPushButton:hover {{ color: #a3e6b0; }}"
            )
        else:
            self._lbl_symbol.setStyleSheet(
                "QPushButton { font-size: 13px; font-weight: bold; color: #d4d4d4;"
                " background: transparent; border: none; text-align: left; padding: 0; }"
                "QPushButton:hover { color: #74c0fc; }"
            )

    def set_data(self, df, position: dict | None = None):
        self._df = df
        n = len(df)
        xs = np.arange(n, dtype=float)

        candle_data = [
            (i, float(df["Open"].iloc[i]), float(df["High"].iloc[i]),
             float(df["Low"].iloc[i]),  float(df["Close"].iloc[i]))
            for i in range(n)
        ]
        self._candles.set_data(candle_data)

        ema20 = df["Close"].ewm(span=20, adjust=False).mean().values
        ema50 = df["Close"].ewm(span=50, adjust=False).mean().values
        self._ema20.setData(xs, ema20)
        self._ema50.setData(xs, ema50)

        last = float(df["Close"].iloc[-1])
        self._lbl_price.setText(f"${last:,.2f}")

        if not self._compact:
            closes = df["Close"].values
            opens  = df["Open"].values
            brushes = [pg.mkBrush(COLOR_GREEN if c >= o else COLOR_RED)
                       for c, o in zip(closes, opens)]
            self._vol_bars.setOpts(x=xs, height=df["Volume"].values.astype(float),
                                    width=0.7, brushes=brushes)
            rsi_vals = df["rsi"].values if "rsi" in df.columns else np.full(n, np.nan)
            valid = ~np.isnan(rsi_vals)
            self._rsi_line.setData(xs[valid], rsi_vals[valid])

        self._update_date_ticks()
        self._apply_position(df, n, position)
        self._plot.autoRange()

    def update_position(self, position: dict | None):
        if self._df is not None:
            self._apply_position(self._df, len(self._df), position)
        self.set_symbol_style(position is not None)

    # ── Private helpers ───────────────────────────────────────────────────

    def _apply_position(self, df, n: int, position: dict | None):
        self.set_symbol_style(position is not None)
        if not position:
            self._entry_scatter.setData([], [])
            self._sl_line.setVisible(False)
            self._tp_line.setVisible(False)
            self._lbl_pnl.setText("")
            self._lbl_markers.setText("")
            return

        entry = position.get("avg_entry_price")
        sl    = position.get("stop_loss")
        tp    = position.get("take_profit")
        pnl   = position.get("unrealized_pl", 0.0)
        pnlpc = position.get("unrealized_plpc", 0.0)
        opened_at = position.get("opened_at", "")

        if entry is not None:
            ex = self._date_to_x(df, n, opened_at)
            self._entry_scatter.setData(pos=[(ex, entry)])
        else:
            self._entry_scatter.setData([], [])

        if sl is not None:
            self._sl_line.setValue(sl); self._sl_line.setVisible(True)
        else:
            self._sl_line.setVisible(False)

        if tp is not None:
            self._tp_line.setValue(tp); self._tp_line.setVisible(True)
        else:
            self._tp_line.setVisible(False)

        color = COLOR_GREEN if pnl >= 0 else COLOR_RED
        self._lbl_pnl.setText(f"{pnl:+,.2f}$ ({pnlpc:+.1%})")
        self._lbl_pnl.setStyleSheet(f"font-size: 11px; color: {color};")

        parts = []
        if entry: parts.append(f"▲ ${entry:,.2f}")
        if sl:    parts.append(f"SL ${sl:,.2f}")
        if tp:    parts.append(f"TP ${tp:,.2f}")
        self._lbl_markers.setText("  ".join(parts))

    @staticmethod
    def _date_to_x(df, n: int, opened_at: str) -> float:
        if not opened_at:
            return float(n - 1)
        try:
            target = datetime.fromisoformat(opened_at).date()
            for i in range(n - 1, max(n - 60, -1), -1):
                if df.index[i].date() <= target:
                    return float(i)
        except Exception:
            pass
        return float(n - 1)


# ── Symbol manager dialog ─────────────────────────────────────────────────────

class _SymbolManagerDialog(QDialog):
    """
    Panel that shows:
    - Open positions (green, no ×, clickable to switch chart)
    - Pinned/manually-added symbols (with × to remove, clickable to switch)
    - Input to add a new symbol
    """
    symbol_selected = Signal(str)
    symbol_added    = Signal(str)
    symbol_removed  = Signal(str)

    def __init__(self, positions: dict, pinned: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Symbole")
        self.setFixedWidth(300)
        self.setMinimumHeight(300)
        self._positions = positions
        self._pinned    = pinned   # shared list — mutations visible in ChartTab
        self._build()

    def _build(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(12, 12, 12, 12)
        vl.setSpacing(8)

        # ── Add input ─────────────────────────────────────────────────────
        add_row = QHBoxLayout()
        self._add_input = QLineEdit()
        self._add_input.setPlaceholderText("Dodaj symbol, np. AAPL")
        self._add_input.returnPressed.connect(self._on_add)
        add_row.addWidget(self._add_input)
        btn_add = QPushButton("＋")
        btn_add.setFixedSize(30, 26)
        btn_add.setStyleSheet(
            "QPushButton { background:#2a5a2a; color:#51cf66; font-size:14px;"
            " border:1px solid #3d7a3d; border-radius:4px; padding:0; }"
            "QPushButton:hover { background:#336633; }"
        )
        btn_add.clicked.connect(self._on_add)
        add_row.addWidget(btn_add)
        vl.addLayout(add_row)

        # ── Symbol list ───────────────────────────────────────────────────
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setSpacing(2)
        self._list_layout.setContentsMargins(0, 4, 0, 0)

        scroll = QScrollArea()
        scroll.setWidget(self._list_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setMinimumHeight(200)
        vl.addWidget(scroll, 1)

        self._rebuild_list()

    def _rebuild_list(self):
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # ── Otwarte pozycje ───────────────────────────────────────────────
        pos_syms = list(self._positions.keys())
        if pos_syms:
            lbl = QLabel("OTWARTE POZYCJE")
            lbl.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 10px;"
                               " font-weight: bold; padding: 2px 0 2px 2px;")
            self._list_layout.addWidget(lbl)
            for sym in pos_syms:
                pos = self._positions[sym]
                pnl = pos.get("unrealized_plpc", 0.0)
                row = QWidget()
                hl  = QHBoxLayout(row)
                hl.setContentsMargins(2, 1, 2, 1)
                btn = QPushButton(f"▲ {sym}   {pnl:+.1%}")
                btn.setFlat(True)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setStyleSheet(
                    f"QPushButton {{ color: {COLOR_GREEN}; background: transparent;"
                    " border: none; text-align: left; font-size: 12px; font-weight: bold; }"
                    f"QPushButton:hover {{ color: #a3e6b0; }}"
                )
                btn.clicked.connect(lambda _, s=sym: (self.symbol_selected.emit(s), self.accept()))
                hl.addWidget(btn)
                self._list_layout.addWidget(row)

        # ── Obserwowane (pinned) ──────────────────────────────────────────
        pinned_non_pos = [s for s in self._pinned if s not in self._positions]
        if pinned_non_pos:
            lbl2 = QLabel("OBSERWOWANE")
            lbl2.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 10px;"
                                " font-weight: bold; padding: 6px 0 2px 2px;")
            self._list_layout.addWidget(lbl2)
            for sym in pinned_non_pos:
                row = QWidget()
                hl  = QHBoxLayout(row)
                hl.setContentsMargins(2, 1, 2, 1)
                btn = QPushButton(sym)
                btn.setFlat(True)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setStyleSheet(
                    "QPushButton { color: #c8c8c8; background: transparent;"
                    " border: none; text-align: left; font-size: 12px; }"
                    "QPushButton:hover { color: #74c0fc; }"
                )
                btn.clicked.connect(lambda _, s=sym: (self.symbol_selected.emit(s), self.accept()))
                hl.addWidget(btn, 1)
                btn_x = QPushButton("×")
                btn_x.setFixedSize(20, 20)
                btn_x.setCursor(Qt.PointingHandCursor)
                btn_x.setStyleSheet(
                    "QPushButton { color: #666; background: transparent; border: none;"
                    " font-size: 14px; padding: 0; }"
                    "QPushButton:hover { color: #f03e3e; }"
                )
                btn_x.clicked.connect(lambda _, s=sym: self._remove(s))
                hl.addWidget(btn_x)
                self._list_layout.addWidget(row)

        if not pos_syms and not pinned_non_pos:
            lbl_empty = QLabel("Brak symboli. Użyj ＋ aby dodać.")
            lbl_empty.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px; padding: 8px;")
            self._list_layout.addWidget(lbl_empty)

        self._list_layout.addStretch()

    def _on_add(self):
        sym = self._add_input.text().strip().upper()
        if not sym:
            return
        self._add_input.clear()
        self.symbol_added.emit(sym)
        self._rebuild_list()

    def _remove(self, sym: str):
        self.symbol_removed.emit(sym)
        self._rebuild_list()

    def refresh(self, positions: dict, pinned: list):
        """Called externally to update data without reopening dialog."""
        self._positions = positions
        self._pinned    = pinned
        self._rebuild_list()


# ── Chart tab ─────────────────────────────────────────────────────────────────

class ChartTab(QWidget):
    symbols_changed = Signal(list)   # active symbol list changed → Market tab syncs

    def __init__(self, config: dict, worker=None, poller=None, parent=None):
        super().__init__(parent)
        self._config      = config
        self._worker      = worker
        self._poller      = poller
        self._positions:  dict[str, dict] = {}
        self._pinned:     list[str]       = []   # manually added, stable order
        self._current_sym: str | None     = None  # active symbol in layout-1 mode
        self._panels:     list[ChartPanel] = []
        self._loaders:    list[ChartLoader] = []
        self._layout_n    = 1
        self._auto_loaded = False
        self._manager_dlg: _SymbolManagerDialog | None = None
        self._build_ui()

        if worker is not None:
            worker.positions_updated.connect(self._on_positions_updated)

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        root.addWidget(make_page_header("Chart", "Wykresy świecowe z wskaźnikami"))

        # ── Toolbar ───────────────────────────────────────────────────────
        tb = QHBoxLayout()
        tb.setSpacing(8)

        lbl = QLabel("Layout:")
        lbl.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        tb.addWidget(lbl)

        self._layout_btn_group = QButtonGroup(self)
        self._layout_btn_group.setExclusive(True)
        for n in [1, 4, 6, 8]:
            btn = QPushButton(str(n))
            btn.setCheckable(True)
            btn.setFixedWidth(36)
            btn.setFixedHeight(26)
            btn.clicked.connect(lambda _, x=n: self._set_layout(x))
            self._layout_btn_group.addButton(btn)
            tb.addWidget(btn)
            if n == 1:
                btn.setChecked(True)

        tb.addSpacing(8)
        btn_refresh = QPushButton("↻ Refresh")
        btn_refresh.setFixedHeight(26)
        btn_refresh.setFixedWidth(84)
        btn_refresh.clicked.connect(self._refresh_all_user)
        tb.addWidget(btn_refresh)

        tb.addStretch()

        btn_add = QPushButton("＋  Symbole")
        btn_add.setFixedHeight(26)
        btn_add.setToolTip("Zarządzaj obserwowanymi symbolami")
        btn_add.setStyleSheet(
            "QPushButton { background:#2a5a2a; color:#51cf66; font-size: 11px;"
            " border:1px solid #3d7a3d; border-radius:4px; padding: 0 8px; }"
            "QPushButton:hover { background:#336633; }"
        )
        btn_add.clicked.connect(self._show_symbol_manager)
        tb.addWidget(btn_add)

        root.addLayout(tb)

        # ── Chart grid in scroll area ─────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )

        self._grid_container = QWidget()
        self._grid_container.setStyleSheet("background: transparent;")
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setSpacing(6)
        self._scroll.setWidget(self._grid_container)
        root.addWidget(self._scroll, 1)

        self._rebuild_grid(load=False)

    # ── Active symbol management ──────────────────────────────────────────

    def _active_symbols(self) -> list[str]:
        """Positions first, then pinned-only extras (stable order)."""
        result: list[str] = []
        seen:   set[str]  = set()
        for s in self._positions:
            result.append(s); seen.add(s)
        for s in self._pinned:
            if s not in seen:
                result.append(s); seen.add(s)
        return result

    def _add_pinned(self, sym: str):
        sym = sym.strip().upper()
        if sym and sym not in self._pinned:
            self._pinned.append(sym)
            log_action(f"Dodano symbol do obserwowanych: {sym}")
        if self._current_sym is None:
            self._current_sym = sym
        self._rebuild_grid()
        self.symbols_changed.emit(self._active_symbols())

    def _remove_pinned(self, sym: str):
        if sym in self._pinned:
            self._pinned.remove(sym)
            log_action(f"Usunięto symbol z obserwowanych: {sym}")
        if self._current_sym == sym:
            active = self._active_symbols()
            self._current_sym = active[0] if active else None
        self._rebuild_grid()
        self.symbols_changed.emit(self._active_symbols())

    # ── Symbol manager dialog ─────────────────────────────────────────────

    def _show_symbol_manager(self):
        dlg = _SymbolManagerDialog(self._positions, self._pinned, parent=self)
        dlg.symbol_added.connect(self._add_pinned)
        dlg.symbol_removed.connect(self._remove_pinned)
        dlg.symbol_selected.connect(self._switch_to)
        dlg.exec()

    # ── Symbol switcher (layout 1: clicking symbol name) ─────────────────

    def _on_symbol_label_clicked(self, sym: str):
        """Called when a ChartPanel's symbol button is clicked."""
        if self._layout_n != 1:
            return
        active = self._active_symbols()
        if len(active) <= 1:
            return
        menu = QMenu(self)
        # Positions section
        pos_syms = [s for s in active if s in self._positions]
        if pos_syms:
            menu.addSection("Otwarte pozycje")
            for s in pos_syms:
                act = menu.addAction(s)
                act.setCheckable(True)
                act.setChecked(s == self._current_sym)
        # Pinned section
        pin_syms = [s for s in active if s not in self._positions]
        if pin_syms:
            menu.addSection("Obserwowane")
            for s in pin_syms:
                act = menu.addAction(s)
                act.setCheckable(True)
                act.setChecked(s == self._current_sym)

        chosen = menu.exec(QCursor.pos())
        if chosen:
            self._switch_to(chosen.text().strip())

    def _switch_to(self, sym: str):
        """Switch the current symbol (layout 1) or add to pinned and switch."""
        sym = sym.strip().upper()
        if not sym:
            return
        if sym not in self._active_symbols():
            self._add_pinned(sym)
        self._current_sym = sym
        self._layout_n = 1
        log_action(f"Przełączono wykres na: {sym}")
        for btn in self._layout_btn_group.buttons():
            btn.setChecked(btn.text() == "1")
        self._rebuild_grid()

    # ── Grid management ───────────────────────────────────────────────────

    def _set_layout(self, n: int):
        self._layout_n = n
        log_action(f"Zmieniono układ wykresu: {n}")
        self._rebuild_grid()

    def _rebuild_grid(self, load: bool = True):
        for loader in self._loaders:
            loader.quit()
            if not loader.isFinished():
                loader.finished.connect(loader.deleteLater)
        self._loaders.clear()

        for panel in self._panels:
            self._grid_layout.removeWidget(panel)
            panel.deleteLater()
        self._panels.clear()

        active = self._active_symbols()

        if self._layout_n == 1:
            # Single-chart mode: show exactly one panel
            if not active:
                self._grid_container.setMinimumHeight(400)
                return
            if self._current_sym not in active:
                self._current_sym = active[0]
            syms_to_show = [self._current_sym]
            cols = 1
            compact = False
        else:
            # Multi-chart grid: show up to GRID_MAX[layout_n] panels
            max_panels = GRID_MAX.get(self._layout_n, self._layout_n)
            syms_to_show = active[:max_panels]
            cols    = GRID_COLS.get(self._layout_n, 2)
            compact = True

        for idx, sym in enumerate(syms_to_show):
            panel = ChartPanel(sym, compact=compact)
            panel.set_symbol_style(sym in self._positions)
            panel.symbol_clicked.connect(self._on_symbol_label_clicked)
            r, c = divmod(idx, cols)
            self._grid_layout.addWidget(panel, r, c)
            self._panels.append(panel)

        rows  = max(1, math.ceil(len(syms_to_show) / cols)) if syms_to_show else 1
        row_h = 520 if not compact else 240
        self._grid_container.setMinimumHeight(rows * row_h)

        if load:
            self._load_all_panels()

    def _get_broker(self):
        return self._poller.get_broker() if self._poller else None

    def _load_all_panels(self):
        broker = self._get_broker()
        for panel in self._panels:
            loader = ChartLoader(self._config, panel.symbol, broker=broker)
            loader.data_ready.connect(self._on_data_ready)
            loader.finished.connect(lambda l=loader: self._loaders.remove(l) if l in self._loaders else None)
            loader.start()
            self._loaders.append(loader)

    # ── Slots ─────────────────────────────────────────────────────────────

    def _on_data_ready(self, symbol: str, df):
        if df is None or df.empty:
            return
        for panel in self._panels:
            if panel.symbol == symbol:
                panel.set_data(df, self._positions.get(symbol))

    def _on_positions_updated(self, positions: list):
        old_syms = set(self._positions.keys())
        self._positions = {p["symbol"]: p for p in positions}
        new_syms = set(self._positions.keys())

        if old_syms != new_syms:
            if not self._current_sym and self._positions:
                self._current_sym = next(iter(self._positions))
            self._rebuild_grid()
            self.symbols_changed.emit(self._active_symbols())
        else:
            for panel in self._panels:
                panel.update_position(self._positions.get(panel.symbol))

    def on_poller_ready(self):
        """Called by main_window once the poller connects — triggers first load."""
        if not self._auto_loaded:
            self._auto_loaded = True
            self._refresh_all()

    def _refresh_all_user(self):
        log_action("Odświeżono wykresy")
        self._rebuild_grid()

    def _refresh_all(self):
        self._rebuild_grid()

    # ── Public API ────────────────────────────────────────────────────────

    def load_symbol(self, symbol: str):
        """Switch to single-chart view for this symbol (called from Market tab)."""
        self._switch_to(symbol)
