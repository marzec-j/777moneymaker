from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from .styles import COLOR_GREEN, COLOR_RED, COLOR_MUTED
from . import log_action


class MarketDataLoader(QThread):
    data_ready = Signal(list)  # list of row dicts

    def __init__(self, config: dict, symbols: list[str], broker=None):
        super().__init__()
        self._config  = config
        self._symbols = symbols
        self._broker  = broker

    def run(self):
        results = []
        try:
            from modules.market_data import MarketDataFetcher
            import logging
            log = logging.getLogger("777moneymaker")
            fetcher = MarketDataFetcher(self._config, self._broker)
            for sym in self._symbols:
                try:
                    snap = fetcher.get_snapshot(sym)
                    if snap:
                        p   = snap["price"]
                        ind = snap["indicators"]
                        rsi = ind.get("rsi")
                        results.append({
                            "symbol":       sym,
                            "price":        p["current"],
                            "change":       p["change_pct"],
                            "volume":       p["volume"],
                            "rsi":          round(rsi, 1) if rsi else None,
                            "signal":       self._signal_from_rsi(rsi),
                            "weekly_trend": (snap.get("weekly") or {}).get("trend", ""),
                        })
                except Exception as sym_exc:
                    log.warning(f"MarketTab: failed to load {sym} — {sym_exc}")
        except Exception as exc:
            import logging
            logging.getLogger("777moneymaker").error(f"MarketTab loader error: {exc}", exc_info=True)
        self.data_ready.emit(results)

    @staticmethod
    def _signal_from_rsi(rsi):
        if rsi is None: return "—"
        if rsi >= 70:   return "SELL"
        if rsi <= 30:   return "BUY"
        if rsi >= 60:   return "Bullish"
        if rsi <= 40:   return "Bearish"
        return "Neutral"


class MarketTab(QWidget):
    symbol_selected = Signal(str)   # double-click row → open chart

    def __init__(self, config: dict, worker=None, poller=None, parent=None):
        super().__init__(parent)
        self._config    = config
        self._poller    = poller
        self._loader:   MarketDataLoader | None = None
        self._extra_loaders: list[MarketDataLoader] = []
        self._positions: dict[str, dict] = {}
        self._watchlist: list[str] = []   # symbols from ChartTab (pinned + positions)
        self._setup_ui()
        if worker is not None:
            worker.cycle_done.connect(self._on_cycle_done)

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        # ── Toolbar ───────────────────────────────────────────────────────
        tb = QHBoxLayout()
        tb.setSpacing(8)

        title = QLabel("MARKET OVERVIEW")
        title.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px; font-weight: bold;")
        tb.addWidget(title)
        tb.addSpacing(12)

        lbl_search = QLabel("Symbol:")
        lbl_search.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        tb.addWidget(lbl_search)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("np. AAPL, TSLA…")
        self._search_input.setFixedWidth(140)
        self._search_input.setFixedHeight(26)
        self._search_input.returnPressed.connect(self._search_symbol)
        tb.addWidget(self._search_input)

        btn_search = QPushButton("⌕")
        btn_search.setFixedSize(28, 26)
        btn_search.setToolTip("Załaduj dane dla podanego symbolu")
        btn_search.clicked.connect(self._search_symbol)
        tb.addWidget(btn_search)

        tb.addStretch()

        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        tb.addWidget(self._lbl_status)

        self._btn_refresh = QPushButton("⟳  Odśwież")
        self._btn_refresh.setFixedWidth(110)
        self._btn_refresh.setFixedHeight(26)
        self._btn_refresh.clicked.connect(self._refresh)
        tb.addWidget(self._btn_refresh)

        lay.addLayout(tb)

        # ── Table ─────────────────────────────────────────────────────────
        cols = ["Symbol", "Cena", "Zmiana %", "Wolumen", "RSI(14)", "Sygnał", "Trend tygodniowy", "Pozycja"]
        self._table = QTableWidget(0, len(cols))
        self._table.setHorizontalHeaderLabels(cols)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.Stretch)
        hdr.setSectionResizeMode(7, QHeaderView.Fixed)
        self._table.setColumnWidth(7, 160)

        self._table.cellDoubleClicked.connect(self._on_row_clicked)
        lay.addWidget(self._table)

        hint = QLabel("Dwuklik → otwiera wykres  |  Wpisz ticker i Enter aby załadować dowolny symbol")
        hint.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 10px;")
        lay.addWidget(hint)

    # ── Symbol source: positions + chart watchlist ─────────────────────────

    def update_watchlist(self, symbols: list[str]):
        """Called by ChartTab.symbols_changed — updates which symbols to show."""
        self._watchlist = list(symbols)
        self._rebuild_symbol_set()

    def _all_tracked_symbols(self) -> list[str]:
        """Union of open positions + chart watchlist (stable order, deduped)."""
        result = []
        seen: set[str] = set()
        for s in self._positions:
            result.append(s); seen.add(s)
        for s in self._watchlist:
            if s not in seen:
                result.append(s); seen.add(s)
        return result

    def _rebuild_symbol_set(self):
        """Ensure all tracked symbols are in the table; load data for new ones."""
        tracked = self._all_tracked_symbols()
        existing = self._existing_symbols()
        new_syms = [s for s in tracked if s not in existing]
        if new_syms:
            broker = self._get_broker()
            loader = MarketDataLoader(self._config, new_syms, broker=broker)
            loader.data_ready.connect(self._append_rows)
            loader.start()
            self._loader = loader

    # ── Refresh ───────────────────────────────────────────────────────────

    def _get_broker(self):
        return self._poller.get_broker() if self._poller else None

    def _refresh(self):
        """Reload market data for ALL currently tracked symbols."""
        tracked = self._all_tracked_symbols()
        if not tracked:
            self._lbl_status.setText("Brak obserwowanych symboli")
            return
        self._table.setRowCount(0)
        self._btn_refresh.setEnabled(False)
        self._lbl_status.setText("Ładowanie…")
        log_action("Odświeżono dane rynkowe")
        broker = self._get_broker()
        self._loader = MarketDataLoader(self._config, tracked, broker=broker)
        self._loader.data_ready.connect(self._populate)
        self._loader.start()

    def _on_cycle_done(self):
        """Bot completed a cycle — refresh market data for tracked symbols."""
        self._refresh()

    def _search_symbol(self):
        raw = self._search_input.text().strip().upper()
        if not raw:
            return
        syms = [s.strip() for s in raw.replace(",", " ").split() if s.strip()]
        already = self._existing_symbols()
        to_load = [s for s in syms if s not in already]
        if not to_load:
            self._lbl_status.setText("Symbol już na liście")
            return
        log_action(f"Wyszukano symbol: {', '.join(to_load)}")
        broker = self._get_broker()
        self._lbl_status.setText(f"Szukam {', '.join(to_load)}…")
        loader = MarketDataLoader(self._config, to_load, broker=broker)
        loader.data_ready.connect(self._append_rows)
        loader.data_ready.connect(lambda _: self._extra_loaders.remove(loader) if loader in self._extra_loaders else None)
        loader.start()
        self._extra_loaders.append(loader)

    def _existing_symbols(self) -> set[str]:
        result = set()
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item:
                result.add(item.text())
        return result

    # ── Populate ──────────────────────────────────────────────────────────

    def _populate(self, rows: list):
        self._table.setRowCount(0)
        for row in rows:
            self._insert_row(row)
        self._btn_refresh.setEnabled(True)
        self._lbl_status.setText(f"Załadowano • {len(rows)} symboli")

    def _append_rows(self, rows: list):
        for row in rows:
            self._insert_row(row)
        self._lbl_status.setText(f"Załadowano • {self._table.rowCount()} symboli")

    def _insert_row(self, row: dict):
        r = self._table.rowCount()
        self._table.insertRow(r)
        change  = row["change"]
        c_color = QColor(COLOR_GREEN) if change >= 0 else QColor(COLOR_RED)
        sig     = row["signal"]
        s_color = (QColor(COLOR_GREEN) if "BUY" in sig or "Bull" in sig
                   else QColor(COLOR_RED) if "SELL" in sig or "Bear" in sig
                   else QColor("#e2e8f0"))

        def _item(text, color=None, align=Qt.AlignRight):
            it = QTableWidgetItem(str(text))
            it.setTextAlignment(align | Qt.AlignVCenter)
            if color:
                it.setForeground(color)
            return it

        vol = row["volume"]
        vol_str = f"{vol/1_000_000:.1f}M" if vol >= 1_000_000 else f"{vol/1_000:.0f}K"

        sym = row["symbol"]
        pos = self._positions.get(sym)
        if pos:
            side_raw  = str(pos.get("side", "")).lower()
            pos_text  = "▲ LONG" if side_raw in ("long", "buy") else "▼ SHORT"
            pos_color = QColor(COLOR_GREEN) if side_raw in ("long", "buy") else QColor(COLOR_RED)
            pnl       = pos.get("unrealized_pl", 0.0)
            pos_text += f"  {pnl:+,.0f}$"
        else:
            pos_text  = "—"
            pos_color = None

        self._table.setItem(r, 0, _item(sym, align=Qt.AlignLeft))
        self._table.setItem(r, 1, _item(f"${row['price']:,.2f}"))
        self._table.setItem(r, 2, _item(f"{change:+.2f}%", c_color))
        self._table.setItem(r, 3, _item(vol_str))
        self._table.setItem(r, 4, _item(str(row["rsi"]) if row["rsi"] else "—"))
        self._table.setItem(r, 5, _item(sig, s_color))
        self._table.setItem(r, 6, _item(row["weekly_trend"], align=Qt.AlignLeft))
        self._table.setItem(r, 7, _item(pos_text, pos_color, Qt.AlignLeft))

    # ── Position updates ──────────────────────────────────────────────────

    def update_positions(self, positions: list):
        """Called on positions_updated signal — updates Position column and syncs new position symbols."""
        old_syms = set(self._positions.keys())
        self._positions = {p["symbol"]: p for p in positions}
        new_syms = set(self._positions.keys())

        # Update position column for all existing rows
        for row in range(self._table.rowCount()):
            sym_item = self._table.item(row, 0)
            if not sym_item:
                continue
            sym = sym_item.text()
            pos = self._positions.get(sym)
            if pos:
                side_raw  = str(pos.get("side", "")).lower()
                pos_text  = "▲ LONG" if side_raw in ("long", "buy") else "▼ SHORT"
                pos_color = QColor(COLOR_GREEN) if side_raw in ("long", "buy") else QColor(COLOR_RED)
                pnl       = pos.get("unrealized_pl", 0.0)
                pos_text += f"  {pnl:+,.0f}$"
            else:
                pos_text  = "—"
                pos_color = QColor("#e2e8f0")
            it = QTableWidgetItem(pos_text)
            it.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            if pos_color:
                it.setForeground(pos_color)
            self._table.setItem(row, 7, it)

        # Load data for newly opened positions not yet in table
        added = new_syms - old_syms
        if added:
            broker = self._get_broker()
            existing = self._existing_symbols()
            to_load = [s for s in added if s not in existing]
            if to_load:
                loader = MarketDataLoader(self._config, to_load, broker=broker)
                loader.data_ready.connect(self._append_rows)
                loader.data_ready.connect(lambda _: self._extra_loaders.remove(loader) if loader in self._extra_loaders else None)
                loader.start()
                self._extra_loaders.append(loader)

    def _on_row_clicked(self, row: int, _col: int):
        item = self._table.item(row, 0)
        if item:
            sym = item.text()
            log_action(f"Otwarto wykres dla: {sym}")
            self.symbol_selected.emit(sym)
