from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from .styles import COLOR_GREEN, COLOR_RED, COLOR_MUTED
from . import log_action


class PositionsTab(QWidget):
    refresh_requested = Signal()

    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self._worker = worker
        self._setup_ui()
        worker.positions_updated.connect(self._update)

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("OPEN POSITIONS")
        title.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px; font-weight: bold;")
        self._lbl_count = QLabel("0 positions")
        self._lbl_count.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        btn_refresh = QPushButton("↻  Refresh")
        btn_refresh.setFixedWidth(100)
        btn_refresh.clicked.connect(self._on_refresh_clicked)

        btn_close = QPushButton("Close Selected")
        btn_close.setFixedWidth(130)
        btn_close.clicked.connect(self._close_selected)

        header.addWidget(title)
        header.addWidget(self._lbl_count)
        header.addStretch()
        header.addWidget(btn_refresh)
        header.addSpacing(6)
        header.addWidget(btn_close)
        lay.addLayout(header)

        cols = ["Symbol", "Side", "Qty", "Entry Price", "Current Price",
                "P&L ($)", "P&L (%)", "Stop Loss", "Take Profit", "Opened At"]
        self._table = QTableWidget(0, len(cols))
        self._table.setHorizontalHeaderLabels(cols)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self._table)

    def _update(self, positions: list):
        self._table.setRowCount(0)
        for pos in positions:
            r = self._table.rowCount()
            self._table.insertRow(r)

            side  = pos.get("side", "long").upper()
            pnl   = pos.get("unrealized_pl", 0.0)
            pnlpc = pos.get("unrealized_plpc", 0.0)
            pnl_color = QColor(COLOR_GREEN) if pnl >= 0 else QColor(COLOR_RED)
            side_color = QColor(COLOR_GREEN) if side == "LONG" else QColor(COLOR_RED)

            def _item(text, color=None, align=Qt.AlignRight):
                it = QTableWidgetItem(str(text))
                it.setTextAlignment(align | Qt.AlignVCenter)
                if color:
                    it.setForeground(color)
                return it

            sl = pos.get("stop_loss")
            tp = pos.get("take_profit")
            opened = str(pos.get("opened_at", ""))[:16]

            self._table.setItem(r, 0, _item(pos["symbol"], align=Qt.AlignLeft))
            self._table.setItem(r, 1, _item(side, side_color))
            self._table.setItem(r, 2, _item(pos.get("qty", 0)))
            self._table.setItem(r, 3, _item(f"${pos.get('avg_entry_price', 0):,.2f}"))
            self._table.setItem(r, 4, _item(f"${pos.get('current_price', 0):,.2f}"))
            self._table.setItem(r, 5, _item(f"${pnl:+,.2f}", pnl_color))
            self._table.setItem(r, 6, _item(f"{pnlpc:+.2%}", pnl_color))
            self._table.setItem(r, 7, _item(f"${sl:,.2f}" if sl else "—"))
            self._table.setItem(r, 8, _item(f"${tp:,.2f}" if tp else "—"))
            self._table.setItem(r, 9, _item(opened, align=Qt.AlignLeft))

        self._lbl_count.setText(f"{len(positions)} position{'s' if len(positions) != 1 else ''}")

    def _on_refresh_clicked(self):
        log_action("Positions refreshed")
        self.refresh_requested.emit()

    def _close_selected(self):
        rows = {idx.row() for idx in self._table.selectedIndexes()}
        if not rows:
            return
        broker = self._worker.get_broker()
        if not broker:
            QMessageBox.warning(self, "Not connected", "Bot is not running — no broker available.")
            return
        syms = []
        for row in rows:
            sym_item = self._table.item(row, 0)
            if sym_item:
                syms.append(sym_item.text())
                broker.close_position(sym_item.text())
        if syms:
            log_action(f"Positions closed: {', '.join(syms)}")
