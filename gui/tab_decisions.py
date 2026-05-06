from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import Qt, QSortFilterProxyModel, QDate
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QSplitter, QTableView,
    QVBoxLayout, QWidget,
)

from .styles import COLOR_GREEN, COLOR_RED, COLOR_GOLD, COLOR_MUTED, COLOR_BG, COLOR_PANEL, COLOR_BORDER, COLOR_FG, COLOR_CARD
from . import log_action


_ACTION_COLOR = {"BUY": COLOR_GREEN, "SELL": COLOR_RED, "HOLD": COLOR_GOLD}

# Column indices in the model
_C_TIME   = 0
_C_SYM    = 1
_C_ACTION = 2
_C_CONF   = 3
_C_PRICE  = 4
_C_ENTRY  = 5
_C_SL     = 6
_C_TP     = 7
_C_RSI    = 8
_C_REASON = 9  # hidden — used for text search


def _fmt_float(val, prefix="$") -> str:
    if val is None:
        return "—"
    try:
        return f"{prefix}{float(val):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _load_decisions(path: Path) -> list[dict]:
    records = []
    if not path.exists():
        return records
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


# ── Filter proxy that matches across multiple columns ─────────────────────────

class DecisionProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._date_from: date | None = None
        self._date_to:   date | None = None
        self._symbol: str = ""
        self._action: str = "ALL"
        self._text: str = ""

    def set_filters(self, date_from, date_to, symbol, action, text):
        self._date_from = date_from
        self._date_to   = date_to
        self._symbol    = symbol.strip().upper()
        self._action    = action
        self._text      = text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent):
        m = self.sourceModel()
        def cell(col) -> str:
            item = m.item(source_row, col)
            return item.text() if item else ""

        # Date filter
        ts_str = cell(_C_TIME)
        if (self._date_from or self._date_to) and ts_str:
            try:
                row_date = datetime.fromisoformat(ts_str).date()
                if self._date_from and row_date < self._date_from:
                    return False
                if self._date_to and row_date > self._date_to:
                    return False
            except ValueError:
                pass

        # Symbol filter
        if self._symbol and self._symbol not in cell(_C_SYM).upper():
            return False

        # Action filter
        if self._action != "ALL" and cell(_C_ACTION) != self._action:
            return False

        # Text search (symbol + reasoning)
        if self._text:
            combined = (cell(_C_SYM) + " " + cell(_C_REASON)).lower()
            for word in self._text.split():
                if word not in combined:
                    return False

        return True


# ── Detail panel (right side) ─────────────────────────────────────────────────

class DecisionDetail(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(f"background: {COLOR_PANEL}; border-radius: 8px;")

        container = QWidget()
        self._lay = QVBoxLayout(container)
        self._lay.setContentsMargins(14, 14, 14, 14)
        self._lay.setSpacing(10)
        self._lay.setAlignment(Qt.AlignTop)

        self._lbl_empty = QLabel("← Kliknij wiersz aby zobaczyć szczegóły")
        self._lbl_empty.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 12px;")
        self._lbl_empty.setAlignment(Qt.AlignCenter)
        self._lay.addWidget(self._lbl_empty)

        self.setWidget(container)
        self._container = container

    def show_record(self, rec: dict):
        # Clear
        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        dec   = rec.get("decision", {})
        snap  = rec.get("market_snapshot", {})
        price = snap.get("price", {})
        ind   = snap.get("indicators", {})
        ts    = rec.get("timestamp", "")
        sym   = rec.get("symbol", "")
        action = dec.get("action", "")
        conf   = dec.get("confidence", 0)

        # ── Header badge ──────────────────────────────────────────────────
        hdr = QHBoxLayout()
        lbl_sym = QLabel(sym)
        lbl_sym.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {COLOR_FG};")

        action_color = _ACTION_COLOR.get(action, "#d4d4d4")
        lbl_action = QLabel(action)
        lbl_action.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {action_color};"
            f"border: 1px solid {action_color}; border-radius: 4px; padding: 2px 10px;")

        lbl_conf = QLabel(f"{conf:.0%}")
        lbl_conf.setStyleSheet(f"font-size: 14px; color: {COLOR_MUTED};")

        hdr.addWidget(lbl_sym)
        hdr.addSpacing(10)
        hdr.addWidget(lbl_action)
        hdr.addSpacing(10)
        hdr.addWidget(lbl_conf)
        hdr.addStretch()
        self._lay.addLayout(hdr)

        # Timestamp
        lbl_ts = QLabel(ts.replace("T", "  ").split(".")[0])
        lbl_ts.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        self._lay.addWidget(lbl_ts)

        self._add_separator()

        # ── Levels ────────────────────────────────────────────────────────
        levels_lay = QHBoxLayout()
        for title, val in [
            ("Entry",       _fmt_float(dec.get("entry_price"))),
            ("Stop Loss",   _fmt_float(dec.get("stop_loss"))),
            ("Take Profit", _fmt_float(dec.get("take_profit"))),
        ]:
            card = self._small_card(title, val)
            levels_lay.addWidget(card)
        self._lay.addLayout(levels_lay)

        # ── Market snapshot ───────────────────────────────────────────────
        self._add_section_label("SNAPSHOT RYNKOWY")
        market_lay = QHBoxLayout()
        current = price.get("current")
        change  = price.get("change_pct")
        for title, val in [
            ("Cena",    _fmt_float(current)),
            ("Zmiana",  f"{change:+.2f}%" if change is not None else "—"),
            ("RSI(14)", f"{ind.get('rsi', 0):.1f}" if ind.get('rsi') else "—"),
            ("Vol ratio", f"{ind.get('volume_ratio', 0):.2f}x" if ind.get('volume_ratio') else "—"),
        ]:
            market_lay.addWidget(self._small_card(title, val))
        self._lay.addLayout(market_lay)

        # MACD row
        macd_lay = QHBoxLayout()
        for title, key in [
            ("MACD",      "macd"),
            ("Signal",    "macd_signal"),
            ("Histogram", "macd_hist"),
        ]:
            v = ind.get(key)
            val = f"{v:.4f}" if v is not None else "—"
            macd_lay.addWidget(self._small_card(title, val))
        self._lay.addLayout(macd_lay)

        self._add_separator()

        # ── Reasoning ─────────────────────────────────────────────────────
        self._add_section_label("ROZUMOWANIE AI")
        lbl_reason = QLabel(dec.get("reasoning", "brak"))
        lbl_reason.setWordWrap(True)
        lbl_reason.setStyleSheet(f"font-size: 12px; color: {COLOR_FG}; line-height: 1.5;")
        self._lay.addWidget(lbl_reason)

        # ── Key signals ───────────────────────────────────────────────────
        signals = dec.get("key_signals", [])
        if signals:
            self._add_separator()
            self._add_section_label("SYGNAŁY KLUCZOWE")
            for sig in signals:
                lbl_sig = QLabel(f"  ▸  {sig}")
                lbl_sig.setStyleSheet(f"font-size: 11px; color: {COLOR_MUTED};")
                self._lay.addWidget(lbl_sig)

        self._lay.addStretch()

    # ── Helpers ───────────────────────────────────────────────────────────

    def _add_separator(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {COLOR_BORDER};")
        self._lay.addWidget(line)

    def _add_section_label(self, text: str):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 10px; font-weight: bold;")
        self._lay.addWidget(lbl)

    def _small_card(self, title: str, value: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"background: {COLOR_CARD}; border: 1px solid {COLOR_BORDER}; border-radius: 6px; padding: 2px;")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(2)
        lbl_t = QLabel(title.upper())
        lbl_t.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 9px; font-weight: bold;")
        lbl_v = QLabel(value)
        lbl_v.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {COLOR_FG}; font-family: 'JetBrains Mono', 'Consolas', monospace;")
        lay.addWidget(lbl_t)
        lay.addWidget(lbl_v)
        return card


# ── Main Decisions tab ────────────────────────────────────────────────────────

class DecisionsTab(QWidget):
    def __init__(self, config: dict, worker=None, parent=None):
        super().__init__(parent)
        self._config = config
        self._all_records: list[dict] = []
        self._decisions_path = self._resolve_path()
        self._build_ui()
        self._load()

        if worker is not None:
            worker.cycle_done.connect(self._load)

    def _resolve_path(self) -> Path:
        data_cfg = self._config.get("data", {})
        data_dir = Path(data_cfg.get("data_dir", "data")).resolve()
        fname    = data_cfg.get("decisions_file", "ai_decisions.jsonl")
        return data_dir / fname

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── Toolbar ───────────────────────────────────────────────────────
        tb = QHBoxLayout()
        tb.setSpacing(8)

        # Date from
        lbl_from = QLabel("Od:")
        lbl_from.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDate(QDate(2020, 1, 1))
        self._date_from.setFixedWidth(110)
        self._date_from.dateChanged.connect(self._apply_filters)

        # Date to
        lbl_to = QLabel("Do:")
        lbl_to.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDate(QDate.currentDate())
        self._date_to.setFixedWidth(110)
        self._date_to.dateChanged.connect(self._apply_filters)

        # Symbol filter
        lbl_sym = QLabel("Symbol:")
        lbl_sym.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        self._sym_combo = QComboBox()
        self._sym_combo.setFixedWidth(90)
        self._sym_combo.currentTextChanged.connect(self._apply_filters)

        # Action filter
        lbl_act = QLabel("Decyzja:")
        lbl_act.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        self._action_combo = QComboBox()
        self._action_combo.addItems(["ALL", "BUY", "SELL", "HOLD"])
        self._action_combo.setFixedWidth(80)
        self._action_combo.currentTextChanged.connect(self._apply_filters)

        # Text search
        lbl_search = QLabel("Szukaj:")
        lbl_search.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("symbol, tekst z rozumowania…")
        self._search_edit.setFixedWidth(200)
        self._search_edit.textChanged.connect(self._apply_filters)

        # Refresh
        btn_refresh = QPushButton("↻ Odśwież")
        btn_refresh.setFixedHeight(26)
        btn_refresh.setFixedWidth(90)
        btn_refresh.clicked.connect(self._load_manual)

        # Count label
        self._lbl_count = QLabel("")
        self._lbl_count.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")

        tb.addWidget(lbl_from);  tb.addWidget(self._date_from)
        tb.addWidget(lbl_to);    tb.addWidget(self._date_to)
        tb.addSpacing(6)
        tb.addWidget(lbl_sym);   tb.addWidget(self._sym_combo)
        tb.addWidget(lbl_act);   tb.addWidget(self._action_combo)
        tb.addWidget(lbl_search);tb.addWidget(self._search_edit)
        tb.addSpacing(6)
        tb.addWidget(btn_refresh)
        tb.addStretch()
        tb.addWidget(self._lbl_count)
        root.addLayout(tb)

        # ── Splitter: table | detail ──────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)

        # Table
        self._model = QStandardItemModel(0, 10)
        self._model.setHorizontalHeaderLabels([
            "Czas", "Symbol", "Decyzja", "Pewność",
            "Cena", "Entry", "SL", "TP", "RSI", "reasoning_hidden",
        ])

        self._proxy = DecisionProxy()
        self._proxy.setSourceModel(self._model)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QTableView.SelectRows)
        self._table.setSelectionMode(QTableView.SingleSelection)
        self._table.setEditTriggers(QTableView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.setColumnHidden(_C_REASON, True)
        self._table.setColumnWidth(_C_TIME,   145)
        self._table.setColumnWidth(_C_SYM,     65)
        self._table.setColumnWidth(_C_ACTION,  70)
        self._table.setColumnWidth(_C_CONF,    70)
        self._table.setColumnWidth(_C_PRICE,   85)
        self._table.setColumnWidth(_C_ENTRY,   85)
        self._table.setColumnWidth(_C_SL,      85)
        self._table.setColumnWidth(_C_TP,      85)
        self._table.setColumnWidth(_C_RSI,     60)
        self._table.selectionModel().currentRowChanged.connect(self._on_row_selected)
        self._table.setAlternatingRowColors(True)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Detail panel
        self._detail = DecisionDetail()

        splitter.addWidget(self._table)
        splitter.addWidget(self._detail)
        splitter.setSizes([680, 380])
        root.addWidget(splitter, 1)

    # ── Data loading ──────────────────────────────────────────────────────

    def _load_manual(self):
        log_action("Odświeżono decyzje AI")
        self._load()

    def _load(self):
        records = _load_decisions(self._decisions_path)
        self._all_records = list(reversed(records))  # newest first
        self._rebuild_model()
        self._refresh_symbol_combo()

    def _rebuild_model(self):
        self._model.removeRows(0, self._model.rowCount())

        for rec in self._all_records:
            dec   = rec.get("decision", {})
            snap  = rec.get("market_snapshot", {})
            ind   = snap.get("price", {})
            indic = snap.get("indicators", {})

            action = dec.get("action", "")
            conf   = dec.get("confidence", 0)
            color  = QColor(_ACTION_COLOR.get(action, "#d4d4d4"))

            def _item(text: str, align=Qt.AlignLeft) -> QStandardItem:
                it = QStandardItem(str(text))
                it.setTextAlignment(align | Qt.AlignVCenter)
                it.setEditable(False)
                return it

            def _colored(text: str) -> QStandardItem:
                it = _item(text, Qt.AlignCenter)
                it.setForeground(color)
                it.setFont(it.font())
                return it

            row = [
                _item(rec.get("timestamp", "").replace("T", " ").split(".")[0]),
                _item(rec.get("symbol", ""), Qt.AlignCenter),
                _colored(action),
                _item(f"{conf:.0%}", Qt.AlignCenter),
                _item(_fmt_float(ind.get("current")), Qt.AlignRight),
                _item(_fmt_float(dec.get("entry_price")), Qt.AlignRight),
                _item(_fmt_float(dec.get("stop_loss")), Qt.AlignRight),
                _item(_fmt_float(dec.get("take_profit")), Qt.AlignRight),
                _item(f"{indic.get('rsi', 0):.1f}" if indic.get("rsi") else "—", Qt.AlignCenter),
                _item(dec.get("reasoning", "")),  # hidden search column
            ]
            self._model.appendRow(row)

        self._lbl_count.setText(f"{self._model.rowCount()} decyzji")

    def _refresh_symbol_combo(self):
        syms = sorted({r.get("symbol", "") for r in self._all_records if r.get("symbol")})
        current = self._sym_combo.currentText()
        self._sym_combo.blockSignals(True)
        self._sym_combo.clear()
        self._sym_combo.addItem("ALL")
        self._sym_combo.addItems(syms)
        idx = self._sym_combo.findText(current)
        self._sym_combo.setCurrentIndex(max(0, idx))
        self._sym_combo.blockSignals(False)
        self._apply_filters()

    # ── Filtering ─────────────────────────────────────────────────────────

    def _apply_filters(self):
        qd_from = self._date_from.date()
        qd_to   = self._date_to.date()
        d_from  = date(qd_from.year(), qd_from.month(), qd_from.day())
        d_to    = date(qd_to.year(),   qd_to.month(),   qd_to.day())

        sym_raw = self._sym_combo.currentText()
        sym     = "" if sym_raw == "ALL" else sym_raw

        self._proxy.set_filters(
            date_from = d_from,
            date_to   = d_to,
            symbol    = sym,
            action    = self._action_combo.currentText(),
            text      = self._search_edit.text(),
        )
        visible = self._proxy.rowCount()
        total   = self._model.rowCount()
        self._lbl_count.setText(f"{visible} / {total} decyzji")

    # ── Row selection → detail panel ──────────────────────────────────────

    def _on_row_selected(self, current, _previous):
        if not current.isValid():
            return
        source_row = self._proxy.mapToSource(current).row()
        if 0 <= source_row < len(self._all_records):
            self._detail.show_record(self._all_records[source_row])
