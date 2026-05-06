"""
Zakładka News — wyświetla newsy zapisane w data/news.jsonl.
Newsy są pobierane automatycznie co minutę przez NewsPoller.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, QDate, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QHBoxLayout, QHeaderView, QLabel,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from .styles import COLOR_GREEN, COLOR_MUTED
from . import log_action


class NewsTab(QWidget):
    def __init__(self, config: dict, worker=None, parent=None):
        super().__init__(parent)
        self._config = config
        self._urls: list[str] = []
        self._setup_ui()
        self._load_from_store()
        if worker is not None:
            worker.cycle_done.connect(self._on_cycle_done)

    # ── UI ────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # ── Toolbar ───────────────────────────────────────────────────────
        tb = QHBoxLayout()
        tb.setSpacing(8)

        lbl = QLabel("NEWSY RYNKOWE")
        lbl.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px; font-weight: bold;")
        tb.addWidget(lbl)
        tb.addSpacing(12)

        lbl_sym = QLabel("Symbol:")
        lbl_sym.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        tb.addWidget(lbl_sym)

        self._sym_combo = QComboBox()
        self._sym_combo.setFixedWidth(120)
        self._sym_combo.currentTextChanged.connect(self._load_from_store)
        tb.addWidget(self._sym_combo)
        tb.addSpacing(8)

        lbl_od = QLabel("Od:")
        lbl_od.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        tb.addWidget(lbl_od)

        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDate(QDate.currentDate().addDays(-7))
        self._date_from.setFixedWidth(110)
        self._date_from.dateChanged.connect(self._load_from_store)
        tb.addWidget(self._date_from)

        lbl_do = QLabel("Do:")
        lbl_do.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        tb.addWidget(lbl_do)

        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDate(QDate.currentDate())
        self._date_to.setFixedWidth(110)
        self._date_to.dateChanged.connect(self._load_from_store)
        tb.addWidget(self._date_to)

        tb.addStretch()

        self._lbl_status = QLabel("Pobieranie co minutę — automatycznie")
        self._lbl_status.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        tb.addWidget(self._lbl_status)

        root.addLayout(tb)

        # ── Tabela ────────────────────────────────────────────────────────
        cols = ["Data", "Symbol", "Nagłówek", "Źródło"]
        self._table = QTableWidget(0, len(cols))
        self._table.setHorizontalHeaderLabels(cols)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)

        hdr = self._table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.Fixed)
        self._table.setColumnWidth(3, 110)

        self._table.cellDoubleClicked.connect(self._open_url)
        root.addWidget(self._table)

        hint = QLabel("Dwuklik → otwiera artykuł w przeglądarce  |  Newsy pobierane automatycznie co minutę")
        hint.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 10px;")
        root.addWidget(hint)

        self._refresh_sym_combo()

    def _refresh_sym_combo(self):
        self._sym_combo.blockSignals(True)
        current = self._sym_combo.currentText()
        self._sym_combo.clear()
        self._sym_combo.addItem("Wszystkie", "")
        try:
            from modules.news_store import NewsStore
            store = NewsStore(self._config)
            for sym in store.symbols():
                self._sym_combo.addItem(sym, sym)
        except Exception:
            pass
        idx = self._sym_combo.findText(current)
        self._sym_combo.setCurrentIndex(max(0, idx))
        self._sym_combo.blockSignals(False)

    # ── Data loading ──────────────────────────────────────────────────────

    def _load_from_store(self):
        try:
            from modules.news_store import NewsStore
            store = NewsStore(self._config)
            sym   = self._sym_combo.currentData() or None
            df    = self._date_from.date().toString("yyyy-MM-dd")
            dt    = self._date_to.date().toString("yyyy-MM-dd")
            items = store.query(symbol=sym, date_from=df, date_to=dt)
            self._populate(items)
        except Exception as exc:
            self._lbl_status.setText(f"Błąd odczytu: {exc}")

    def _populate(self, items: list[dict]):
        self._table.setRowCount(0)
        self._urls = []

        for item in items:
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._urls.append(item.get("url", ""))

            sym       = item.get("symbol", "")
            sym_color = COLOR_GREEN if sym and sym != "MARKET" else None

            def _cell(text, align=Qt.AlignLeft, color=None):
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(align | Qt.AlignVCenter)
                if color:
                    it.setForeground(QColor(color))
                return it

            self._table.setItem(r, 0, _cell(item.get("datetime", "")[:16], Qt.AlignCenter))
            self._table.setItem(r, 1, _cell(sym, Qt.AlignCenter, sym_color))
            self._table.setItem(r, 2, _cell(item.get("headline", "")))
            self._table.setItem(r, 3, _cell(item.get("source", ""), Qt.AlignCenter))

        self._lbl_status.setText(
            f"{len(items)} newsów  •  ostatni refresh: {datetime.now().strftime('%H:%M:%S')}"
        )

    # ── External signals ──────────────────────────────────────────────────

    def on_news_updated(self, new_count: int):
        """Called by NewsPoller every time fresh articles are saved."""
        self._refresh_sym_combo()
        self._load_from_store()

    def _on_cycle_done(self):
        """Po każdym cyklu bota odśwież widok."""
        self._refresh_sym_combo()
        self._load_from_store()

    # ── URL open ──────────────────────────────────────────────────────────

    def _open_url(self, row: int, _col: int):
        if row < len(self._urls) and self._urls[row]:
            url = self._urls[row]
            headline = ""
            item = self._table.item(row, 2)
            if item:
                headline = item.text()[:60]
            log_action(f"Otwarto artykuł: {headline}")
            QDesktopServices.openUrl(QUrl(url))
