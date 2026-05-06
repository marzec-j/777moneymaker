from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)
from .styles import COLOR_GREEN, COLOR_RED, COLOR_GOLD, COLOR_MUTED
from . import log_action


_LEVEL_COLORS = {
    "DEBUG":    "#858585",
    "INFO":     "#d4d4d4",
    "WARNING":  "#ffd43b",
    "ERROR":    "#f03e3e",
    "CRITICAL": "#ff6b6b",
}

_KEYWORD_COLORS = {
    "BUY":    COLOR_GREEN,
    "COVER":  COLOR_GREEN,
    "TP_EXIT": COLOR_GREEN,
    "SELL":   COLOR_RED,
    "SHORT":  COLOR_RED,
    "SL_EXIT": COLOR_RED,
    "ERROR":  COLOR_RED,
    "WARNING": COLOR_GOLD,
}


class LogsTab(QWidget):
    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self._worker = worker
        self._filter_level = "ALL"
        self._setup_ui()
        worker.log_emitted.connect(self._append)
        worker.error_occurred.connect(lambda msg: self._append("ERROR", f"[ERROR] {msg}"))

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        # Toolbar
        toolbar = QHBoxLayout()
        lbl = QLabel("LOGS")
        lbl.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px; font-weight: bold;")

        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["ALL", "INFO", "WARNING", "ERROR"])
        self._filter_combo.setFixedWidth(90)
        self._filter_combo.currentTextChanged.connect(self._set_filter)

        btn_clear = QPushButton("Clear")
        btn_clear.setFixedWidth(70)
        btn_clear.clicked.connect(self._text.clear if hasattr(self, "_text") else lambda: None)

        self._lbl_count = QLabel("0 lines")
        self._lbl_count.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")

        self._lbl_autoscroll = QLabel("⬇ auto")
        self._lbl_autoscroll.setStyleSheet(f"color: {COLOR_GREEN}; font-size: 11px;")
        self._lbl_autoscroll.setToolTip("Auto-scroll aktywny — przewiń w górę aby wyłączyć")

        toolbar.addWidget(lbl)
        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("Filter:"))
        toolbar.addWidget(self._filter_combo)
        toolbar.addStretch()
        toolbar.addWidget(self._lbl_autoscroll)
        toolbar.addSpacing(8)
        toolbar.addWidget(self._lbl_count)
        toolbar.addSpacing(8)
        toolbar.addWidget(btn_clear)
        lay.addLayout(toolbar)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QTextEdit.NoWrap)
        lay.addWidget(self._text)

        # Reconnect clear after _text exists
        btn_clear.clicked.disconnect()
        btn_clear.clicked.connect(self._clear)

        self._line_count = 0
        self._auto_scroll = True

        sb = self._text.verticalScrollBar()
        # New content added → scroll to bottom only when auto-scroll is on
        sb.rangeChanged.connect(self._on_range_changed)
        # User moved scrollbar → toggle auto-scroll based on position
        sb.valueChanged.connect(self._on_scroll_changed)

    def _append(self, level: str, message: str):
        if self._filter_level != "ALL":
            level_order = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            if level_order.index(level) < level_order.index(self._filter_level):
                return

        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.End)

        fmt = QTextCharFormat()
        color = _LEVEL_COLORS.get(level, "#d4d4d4")

        # Highlight special keywords
        for kw, kw_color in _KEYWORD_COLORS.items():
            if kw in message:
                color = kw_color
                break

        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(message + "\n")

        self._line_count += 1
        self._lbl_count.setText(f"{self._line_count} lines")

        # Keep max 5000 lines to avoid memory bloat
        if self._line_count > 5000:
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor, 500)
            cursor.removeSelectedText()
            self._line_count -= 500

    def _on_range_changed(self, _min: int, _max: int):
        """New content arrived — scroll to bottom if auto-scroll is on."""
        if self._auto_scroll:
            self._text.verticalScrollBar().setValue(_max)

    def _on_scroll_changed(self, value: int):
        """User moved the scrollbar — enable auto-scroll only when at the bottom."""
        sb = self._text.verticalScrollBar()
        at_bottom = value >= sb.maximum() - 4
        if at_bottom != self._auto_scroll:
            self._auto_scroll = at_bottom
            if at_bottom:
                self._lbl_autoscroll.setText("⬇ auto")
                self._lbl_autoscroll.setStyleSheet(f"color: {COLOR_GREEN}; font-size: 11px;")
                self._lbl_autoscroll.setToolTip("Auto-scroll aktywny — przewiń w górę aby wyłączyć")
            else:
                self._lbl_autoscroll.setText("⏸ pauza")
                self._lbl_autoscroll.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
                self._lbl_autoscroll.setToolTip("Auto-scroll wyłączony — przewiń na dół aby wznowić")

    def _set_filter(self, level: str):
        self._filter_level = level

    def _clear(self):
        self._text.clear()
        self._line_count = 0
        self._lbl_count.setText("0 lines")
        log_action("Wyczyszczono logi")
