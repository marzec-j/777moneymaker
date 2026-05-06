"""
SymbolBrain tab — shows the persistent symbol scoring state.
Reads data/symbol_brain.json and displays all tracked symbols
with their score components, LLM history, and last activity.
Auto-refreshes after each engine cycle.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSortFilterProxyModel, QTimer
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QTableView, QVBoxLayout, QWidget,
)

from .styles import (
    COLOR_BG, COLOR_BORDER, COLOR_CARD, COLOR_GREEN, COLOR_GOLD,
    COLOR_MUTED, COLOR_PANEL, COLOR_RED,
)

_ACTION_COLOR = {
    "BUY":  COLOR_GREEN,
    "SELL": COLOR_RED,
    "HOLD": COLOR_GOLD,
}

# Column indices
_C_SYM     = 0
_C_SCORE   = 1
_C_NEWS    = 2
_C_MOMT    = 3
_C_VOL     = 4
_C_ACTION  = 5
_C_CONF    = 6
_C_SCANNER = 7
_C_COUNT   = 8
_C_LAST    = 9


def _load_brain(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _hours_ago(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
        diff = (datetime.utcnow() - dt).total_seconds()
        if diff < 60:
            return f"{int(diff)}s temu"
        if diff < 3600:
            return f"{int(diff/60)}min temu"
        if diff < 86400:
            return f"{diff/3600:.1f}h temu"
        return f"{diff/86400:.1f}d temu"
    except Exception:
        return iso[:16]


def _score_color(score: float) -> str:
    if score >= 0.5:
        return COLOR_GREEN
    if score >= 0.2:
        return COLOR_GOLD
    if score >= 0.05:
        return "#74c0fc"
    return COLOR_MUTED


# ── Filter proxy ──────────────────────────────────────────────────────────────

class BrainProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._symbol = ""
        self._action = "ALL"
        self._min_score = 0.0

    def set_filters(self, symbol: str, action: str, min_score: float):
        self._symbol    = symbol.strip().upper()
        self._action    = action
        self._min_score = min_score
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent):
        m = self.sourceModel()
        def cell(col) -> str:
            item = m.item(source_row, col)
            return item.text() if item else ""

        if self._symbol and self._symbol not in cell(_C_SYM).upper():
            return False
        if self._action != "ALL":
            if cell(_C_ACTION) != self._action and not (
                self._action == "—" and cell(_C_ACTION) == ""
            ):
                return False
        try:
            score = float(cell(_C_SCORE))
            if score < self._min_score:
                return False
        except ValueError:
            pass
        return True


# ── Detail panel ──────────────────────────────────────────────────────────────

class BrainDetail(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(f"background: {COLOR_PANEL};")

        container = QWidget()
        self._lay = QVBoxLayout(container)
        self._lay.setContentsMargins(16, 16, 16, 16)
        self._lay.setSpacing(10)
        self._lay.setAlignment(Qt.AlignTop)

        hint = QLabel("← Kliknij symbol aby zobaczyć szczegóły")
        hint.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 12px;")
        hint.setAlignment(Qt.AlignCenter)
        self._lay.addWidget(hint)
        self.setWidget(container)
        self._container = container

    def show_entry(self, symbol: str, entry: dict):
        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        score  = entry.get("score", 0.0)
        action = entry.get("llm_action") or "—"
        conf   = entry.get("llm_confidence", 0.0)

        # ── Header ────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        lbl_sym = QLabel(symbol)
        lbl_sym.setStyleSheet("font-size: 22px; font-weight: bold; color: #e0e0e0;")

        score_color = _score_color(score)
        lbl_score = QLabel(f"{score:.4f}")
        lbl_score.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {score_color};"
            f"border: 1px solid {score_color}; border-radius: 4px; padding: 2px 10px;"
        )

        hdr.addWidget(lbl_sym)
        hdr.addSpacing(10)
        hdr.addWidget(lbl_score)
        hdr.addStretch()
        self._lay.addLayout(hdr)

        # First seen / last activity
        fs   = (entry.get("first_seen") or "")[:16].replace("T", " ")
        last = _hours_ago(entry.get("last_activity"))
        meta = QLabel(f"Pierwsze wykrycie: {fs}   •   Ostatnia aktywność: {last}")
        meta.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        self._lay.addWidget(meta)

        self._add_separator()

        # ── Score components ──────────────────────────────────────────────
        self._add_section("SKŁADNIKI SCORE")
        components_lay = QHBoxLayout()

        news_score  = min(float(entry.get("news_hits", 0.0)) / 5.0, 1.0)
        momt        = abs(float(entry.get("momentum_pct", 0.0)))
        momt_score  = min(momt / 5.0, 1.0)
        vr          = float(entry.get("volume_ratio", 1.0) or 1.0)
        vol_score   = min(max(vr - 1.0, 0.0) / 2.0, 1.0)
        llm_conf    = float(entry.get("llm_confidence", 0.0) or 0.0)
        llm_act     = entry.get("llm_action") or "HOLD"
        llm_score   = llm_conf if llm_act in ("BUY", "SELL") else llm_conf * 0.2
        sc_conf     = float(entry.get("scanner_confidence", 0.0) or 0.0)
        sc_act      = entry.get("scanner_action") or "HOLD"
        sc_score    = sc_conf if sc_act in ("BUY", "SELL") else sc_conf * 0.2
        learn       = float(entry.get("learner_bonus", 0.0) or 0.0)

        for title, val, weight in [
            ("News 25%",     news_score, 0.25),
            ("Momentum 15%", momt_score, 0.15),
            ("Volume 10%",   vol_score,  0.10),
            ("LLM 20%",      llm_score,  0.20),
            ("Scanner 20%",  sc_score,   0.20),
            ("Learner 10%",  learn,      0.10),
        ]:
            components_lay.addWidget(self._score_card(title, val, weight))
        self._lay.addLayout(components_lay)

        self._add_separator()

        # ── Raw signals ───────────────────────────────────────────────────
        self._add_section("SYGNAŁY RYNKOWE")
        signals_lay = QHBoxLayout()
        for title, val in [
            ("News hits",    f"{entry.get('news_hits', 0.0):.1f}"),
            ("Momentum",     f"{entry.get('momentum_pct', 0.0):+.2f}%"),
            ("Volume ratio", f"{entry.get('volume_ratio', 1.0):.2f}x"),
        ]:
            signals_lay.addWidget(self._card(title, val))
        self._lay.addLayout(signals_lay)

        self._add_separator()

        # ── LLM history ───────────────────────────────────────────────────
        self._add_section("OSTATNIA DECYZJA LLM")
        llm_lay = QHBoxLayout()
        action_color = _ACTION_COLOR.get(action, COLOR_MUTED)
        for title, val, color in [
            ("Decyzja",  action,       action_color),
            ("Pewność",  f"{conf:.0%}", "#e2e8f0"),
            ("Analizy",  str(entry.get("analyze_count", 0)), "#e2e8f0"),
        ]:
            c = self._card(title, val)
            # tint the value label
            val_lbl = c.findChild(QLabel, "val_lbl")
            if val_lbl:
                val_lbl.setStyleSheet(
                    f"font-size: 14px; font-weight: bold; color: {color};"
                )
            llm_lay.addWidget(c)
        self._lay.addLayout(llm_lay)

        llm_ts = entry.get("llm_ts")
        if llm_ts:
            ts_lbl = QLabel(f"Ostatnia analiza (engine): {_hours_ago(llm_ts)}")
            ts_lbl.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
            self._lay.addWidget(ts_lbl)

        # ── BrainScanner signal ───────────────────────────────────────────
        sc_action = entry.get("scanner_action") or "—"
        sc_conf   = float(entry.get("scanner_confidence", 0.0) or 0.0)
        sc_ts     = entry.get("scanner_ts")
        if sc_ts or sc_action != "—":
            self._add_separator()
            self._add_section("BRAIN SCANNER (lekka analiza AI)")
            sc_lay = QHBoxLayout()
            sc_color = _ACTION_COLOR.get(sc_action, COLOR_MUTED)
            for title, val, color in [
                ("Sygnał",    sc_action,           sc_color),
                ("Pewność",   f"{sc_conf:.0%}" if sc_conf > 0 else "—", "#e2e8f0"),
                ("Ostatni skan", _hours_ago(sc_ts) if sc_ts else "brak", COLOR_MUTED),
            ]:
                c = self._card(title, val)
                val_lbl = c.findChild(QLabel, "val_lbl")
                if val_lbl:
                    val_lbl.setStyleSheet(
                        f"font-size: 14px; font-weight: bold; color: {color};"
                    )
                sc_lay.addWidget(c)
            self._lay.addLayout(sc_lay)

        # ── Learner bonus ─────────────────────────────────────────────────
        lb = entry.get("learner_bonus", 0.0)
        if lb:
            self._add_separator()
            self._add_section("BONUS UCZENIA")
            lb_lbl = QLabel(f"{lb:.4f}  (win-rate + avg return z historii transakcji)")
            lb_lbl.setStyleSheet(f"color: {COLOR_GREEN}; font-size: 12px;")
            self._lay.addWidget(lb_lbl)

        self._lay.addStretch()

    # ── Helpers ───────────────────────────────────────────────────────────

    def _add_separator(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {COLOR_BORDER};")
        self._lay.addWidget(line)

    def _add_section(self, text: str):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {COLOR_MUTED}; font-size: 10px; font-weight: bold; "
            "letter-spacing: 0.5px;"
        )
        self._lay.addWidget(lbl)

    def _card(self, title: str, value: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"background: {COLOR_BG}; border-radius: 4px; padding: 2px;"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(2)
        lbl_t = QLabel(title.upper())
        lbl_t.setStyleSheet(
            f"color: {COLOR_MUTED}; font-size: 9px; font-weight: bold;"
        )
        lbl_v = QLabel(value)
        lbl_v.setObjectName("val_lbl")
        lbl_v.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #d4d4d4;"
        )
        lay.addWidget(lbl_t)
        lay.addWidget(lbl_v)
        return card

    def _score_card(self, title: str, component: float, weight: float) -> QFrame:
        contribution = component * weight
        color = _score_color(component)
        card = QFrame()
        card.setStyleSheet(
            f"background: {COLOR_BG}; border-radius: 4px; padding: 2px;"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(2)
        lbl_t = QLabel(title.upper())
        lbl_t.setStyleSheet(
            f"color: {COLOR_MUTED}; font-size: 9px; font-weight: bold;"
        )
        lbl_v = QLabel(f"{component:.2f}")
        lbl_v.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {color};"
        )
        lbl_c = QLabel(f"→ {contribution:.3f}")
        lbl_c.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 10px;")
        lay.addWidget(lbl_t)
        lay.addWidget(lbl_v)
        lay.addWidget(lbl_c)
        return card


# ── Stats bar ─────────────────────────────────────────────────────────────────

class StatsBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background: {COLOR_CARD}; border: 1px solid {COLOR_BORDER}; "
            "border-radius: 6px;"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(32)

        self._labels: dict[str, QLabel] = {}
        for key, title in [
            ("total",     "Śledzone symbole"),
            ("watchlist", "W watchliście"),
            ("active",    "Aktywne (score>0.05)"),
            ("top",       "Najwyższy score"),
            ("updated",   "Ostatni odczyt"),
        ]:
            col = QVBoxLayout()
            col.setSpacing(2)
            lbl_title = QLabel(title.upper())
            lbl_title.setStyleSheet(
                f"color: {COLOR_MUTED}; font-size: 9px; font-weight: bold; "
                "letter-spacing: 0.5px;"
            )
            lbl_val = QLabel("—")
            lbl_val.setStyleSheet(
                "font-size: 16px; font-weight: bold; color: #d4d4d4;"
            )
            col.addWidget(lbl_title)
            col.addWidget(lbl_val)
            lay.addLayout(col)
            self._labels[key] = lbl_val

        lay.addStretch()

    def update_stats(self, data: dict[str, dict], watchlist_size: int):
        total  = len(data)
        active = sum(1 for e in data.values() if e.get("score", 0) >= 0.05)

        top_sym   = ""
        top_score = 0.0
        for sym, e in data.items():
            if e.get("score", 0) > top_score:
                top_score = e["score"]
                top_sym   = sym

        self._labels["total"].setText(str(total))
        self._labels["watchlist"].setText(str(watchlist_size))
        self._labels["active"].setText(str(active))
        self._labels["top"].setText(
            f"{top_sym}  {top_score:.4f}" if top_sym else "—"
        )
        self._labels["updated"].setText(
            datetime.now().strftime("%H:%M:%S")
        )


# ── Main tab ──────────────────────────────────────────────────────────────────

class BrainTab(QWidget):
    def __init__(self, config: dict, brain=None, worker=None, scanner=None, parent=None):
        super().__init__(parent)
        self._config  = config
        self._brain   = brain    # live SymbolBrain object (optional)
        self._scanner = scanner  # BrainScannerWorker (optional)
        self._data: dict[str, dict] = {}

        data_cfg       = config.get("data", {})
        brain_cfg      = config.get("brain", {})
        data_dir       = Path(data_cfg.get("data_dir", "data")).resolve()
        self._brain_path = data_dir / "symbol_brain.json"
        self._watchlist_size = brain_cfg.get("watchlist_size", 30)

        self._build_ui()
        self._load()

        if worker is not None:
            worker.cycle_done.connect(self._load)

        # Fallback timer — refresh even if bot is stopped
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._load)
        self._timer.start(30_000)   # 30 s

    # ── Scanner status slots ──────────────────────────────────────────────

    def on_scanner_status(self, status: str):
        self._lbl_scanner.setText(f"Scanner: {status}")

    def on_scan_completed(self, scanned: int, total: int):
        self._lbl_scanner.setText(f"Scanner: ukończono {scanned}/{total} symboli")
        self._load()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Stats bar
        self._stats = StatsBar()
        root.addWidget(self._stats)

        # Scanner status bar
        scanner_bar = QFrame()
        scanner_bar.setStyleSheet(
            f"background: {COLOR_CARD}; border: 1px solid {COLOR_BORDER}; border-radius: 4px;"
        )
        scanner_lay = QHBoxLayout(scanner_bar)
        scanner_lay.setContentsMargins(12, 4, 12, 4)
        lbl_title = QLabel("AI SCANNER")
        lbl_title.setStyleSheet(
            f"color: {COLOR_GOLD}; font-size: 10px; font-weight: bold; letter-spacing: 0.5px;"
        )
        self._lbl_scanner = QLabel("Scanner: inicjalizacja…")
        self._lbl_scanner.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        scanner_lay.addWidget(lbl_title)
        scanner_lay.addSpacing(12)
        scanner_lay.addWidget(self._lbl_scanner)
        scanner_lay.addStretch()
        root.addWidget(scanner_bar)

        # Toolbar
        tb = QHBoxLayout()
        tb.setSpacing(8)

        lbl_sym = QLabel("Symbol:")
        lbl_sym.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        self._sym_edit = QLineEdit()
        self._sym_edit.setPlaceholderText("filtruj…")
        self._sym_edit.setFixedWidth(100)
        self._sym_edit.textChanged.connect(self._apply_filters)

        lbl_act = QLabel("LLM:")
        lbl_act.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        self._action_combo = QComboBox()
        self._action_combo.addItems(["ALL", "BUY", "SELL", "HOLD", "—"])
        self._action_combo.setFixedWidth(80)
        self._action_combo.currentTextChanged.connect(self._apply_filters)

        lbl_score = QLabel("Min score:")
        lbl_score.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        self._score_combo = QComboBox()
        self._score_combo.addItems(["0.00", "0.05", "0.10", "0.20", "0.50"])
        self._score_combo.setCurrentIndex(1)   # default 0.05
        self._score_combo.setFixedWidth(70)
        self._score_combo.currentTextChanged.connect(self._apply_filters)

        btn_refresh = QPushButton("↻ Odśwież")
        btn_refresh.setFixedHeight(26)
        btn_refresh.setFixedWidth(90)
        btn_refresh.clicked.connect(self._load)

        self._lbl_count = QLabel("")
        self._lbl_count.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")

        tb.addWidget(lbl_sym);   tb.addWidget(self._sym_edit)
        tb.addWidget(lbl_act);   tb.addWidget(self._action_combo)
        tb.addWidget(lbl_score); tb.addWidget(self._score_combo)
        tb.addSpacing(8)
        tb.addWidget(btn_refresh)
        tb.addStretch()
        tb.addWidget(self._lbl_count)
        root.addLayout(tb)

        # Splitter: table | detail
        splitter = QSplitter(Qt.Horizontal)

        # Model + proxy
        self._model = QStandardItemModel(0, 10)
        self._model.setHorizontalHeaderLabels([
            "Symbol", "Score", "News hits", "Momentum",
            "Vol ratio", "LLM", "Pewność", "Scanner", "Analizy", "Ostatnia aktyw.",
        ])

        self._proxy = BrainProxy()
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortRole(Qt.UserRole)   # numeric sort

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QTableView.SelectRows)
        self._table.setSelectionMode(QTableView.SingleSelection)
        self._table.setEditTriggers(QTableView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._table.setColumnWidth(_C_SYM,     80)
        self._table.setColumnWidth(_C_SCORE,   75)
        self._table.setColumnWidth(_C_NEWS,    80)
        self._table.setColumnWidth(_C_MOMT,    90)
        self._table.setColumnWidth(_C_VOL,     80)
        self._table.setColumnWidth(_C_ACTION,  65)
        self._table.setColumnWidth(_C_CONF,    70)
        self._table.setColumnWidth(_C_SCANNER, 90)
        self._table.setColumnWidth(_C_COUNT,   70)
        self._table.setColumnWidth(_C_LAST,    120)
        self._table.selectionModel().currentRowChanged.connect(self._on_row_selected)
        # Default sort by score descending
        self._proxy.sort(_C_SCORE, Qt.DescendingOrder)

        self._detail = BrainDetail()

        splitter.addWidget(self._table)
        splitter.addWidget(self._detail)
        splitter.setSizes([700, 380])
        root.addWidget(splitter, 1)

    # ── Data loading ──────────────────────────────────────────────────────

    def _load(self):
        self._data = _load_brain(self._brain_path)
        self._rebuild_model()
        self._stats.update_stats(self._data, self._watchlist_size)
        self._apply_filters()

    def _rebuild_model(self):
        self._model.removeRows(0, self._model.rowCount())

        for sym, entry in self._data.items():
            score      = float(entry.get("score", 0.0))
            news       = float(entry.get("news_hits", 0.0))
            momt       = float(entry.get("momentum_pct", 0.0))
            volr       = float(entry.get("volume_ratio", 1.0) or 1.0)
            action     = entry.get("llm_action") or "—"
            conf       = float(entry.get("llm_confidence", 0.0) or 0.0)
            sc_action  = entry.get("scanner_action") or "—"
            sc_conf    = float(entry.get("scanner_confidence", 0.0) or 0.0)
            count      = int(entry.get("analyze_count", 0))
            last       = _hours_ago(entry.get("last_activity"))

            score_color     = QColor(_score_color(score))
            action_color    = QColor(_ACTION_COLOR.get(action, COLOR_MUTED))
            sc_action_color = QColor(_ACTION_COLOR.get(sc_action, COLOR_MUTED))

            def _item(text: str, sort_val=None, align=Qt.AlignLeft) -> QStandardItem:
                it = QStandardItem(str(text))
                it.setTextAlignment(align | Qt.AlignVCenter)
                it.setEditable(False)
                if sort_val is not None:
                    it.setData(sort_val, Qt.UserRole)
                else:
                    try:
                        it.setData(float(str(text).replace("%", "").replace("x", "")), Qt.UserRole)
                    except (ValueError, TypeError):
                        it.setData(str(text), Qt.UserRole)
                return it

            it_sym    = _item(sym, sym, Qt.AlignCenter)
            it_score  = _item(f"{score:.4f}", score, Qt.AlignCenter)
            it_score.setForeground(score_color)

            it_news   = _item(f"{news:.1f}", news, Qt.AlignCenter)

            momt_color = QColor(COLOR_GREEN if momt >= 0 else COLOR_RED)
            it_momt   = _item(f"{momt:+.2f}%", momt, Qt.AlignCenter)
            it_momt.setForeground(momt_color)

            it_vol    = _item(f"{volr:.2f}x", volr, Qt.AlignCenter)

            it_action = _item(action, action, Qt.AlignCenter)
            it_action.setForeground(action_color)

            it_conf   = _item(f"{conf:.0%}" if conf > 0 else "—", conf, Qt.AlignCenter)

            # Scanner column: "BUY 72%" or "—"
            if sc_action != "—" and sc_conf > 0:
                sc_text = f"{sc_action} {sc_conf:.0%}"
            else:
                sc_text = "—"
            it_scanner = _item(sc_text, sc_conf, Qt.AlignCenter)
            it_scanner.setForeground(sc_action_color)

            it_count  = _item(str(count), count, Qt.AlignCenter)
            it_last   = _item(last, entry.get("last_activity") or "", Qt.AlignLeft)

            self._model.appendRow([
                it_sym, it_score, it_news, it_momt,
                it_vol, it_action, it_conf, it_scanner, it_count, it_last,
            ])

    # ── Filters ───────────────────────────────────────────────────────────

    def _apply_filters(self):
        try:
            min_score = float(self._score_combo.currentText())
        except ValueError:
            min_score = 0.0

        self._proxy.set_filters(
            symbol    = self._sym_edit.text(),
            action    = self._action_combo.currentText(),
            min_score = min_score,
        )
        visible = self._proxy.rowCount()
        total   = self._model.rowCount()
        self._lbl_count.setText(f"{visible} / {total} symboli")

    # ── Row selection ─────────────────────────────────────────────────────

    def _on_row_selected(self, current, _previous):
        if not current.isValid():
            return
        source_row = self._proxy.mapToSource(current).row()
        sym_item   = self._model.item(source_row, _C_SYM)
        if sym_item is None:
            return
        sym   = sym_item.text()
        entry = self._data.get(sym)
        if entry is not None:
            self._detail.show_entry(sym, entry)
