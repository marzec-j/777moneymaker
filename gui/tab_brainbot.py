"""
BrainBotTab — zakładka BrainBot z podzakładkami:
  Logi    — tabela brain scores + status skanera (istniejący BrainTab)
  Dziennik — journal: rekomendacje, obserwuj później, notatki uczenia
  Czat    — interaktywny czat z BrainBotem (przez LLM)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from .tab_brain import BrainTab
from .styles import (
    COLOR_BG, COLOR_BORDER, COLOR_CARD, COLOR_GREEN,
    COLOR_GOLD, COLOR_MUTED, COLOR_PANEL, COLOR_RED, make_page_header,
)

if TYPE_CHECKING:
    from modules.brain_journal import BrainJournal
    from modules.brain_scanner import BrainScannerWorker
    from modules.symbol_brain import SymbolBrain


# ── Konsola skanera ───────────────────────────────────────────────────────────

class ScanConsoleWidget(QWidget):
    """Konsola wyświetlająca logi BrainBota w czasie rzeczywistym."""

    def __init__(self, scanner: "BrainScannerWorker", parent=None):
        super().__init__(parent)
        self._scanner = scanner
        self._line_count = 0
        self._build_ui()
        if scanner is not None:
            scanner.scan_log_entry.connect(self._append_entry)
            scanner.status_updated.connect(self._append_status)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Toolbar
        toolbar = QHBoxLayout()
        lbl = QLabel("KONSOLA BRAINBOTA")
        lbl.setStyleSheet(f"color: {COLOR_GOLD}; font-size: 11px; font-weight: bold;")

        self._lbl_count = QLabel("0 wpisów")
        self._lbl_count.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")

        btn_clear = QPushButton("Clear")
        btn_clear.setFixedWidth(70)
        btn_clear.clicked.connect(self._clear)

        toolbar.addWidget(lbl)
        toolbar.addStretch()
        toolbar.addWidget(self._lbl_count)
        toolbar.addSpacing(8)
        toolbar.addWidget(btn_clear)
        root.addLayout(toolbar)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QTextEdit.NoWrap)
        self._text.setStyleSheet(
            f"background: {COLOR_BG}; border: 1px solid {COLOR_BORDER}; "
            "font-family: monospace; font-size: 11px; color: #d4d4d4; padding: 4px;"
        )
        root.addWidget(self._text)

    def _append_entry(self, entry: str):
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.End)

        fmt = QTextCharFormat()
        if "BUY" in entry:
            fmt.setForeground(QColor(COLOR_GREEN))
        elif "SELL" in entry:
            fmt.setForeground(QColor(COLOR_RED))
        elif "HOLD" in entry:
            fmt.setForeground(QColor(COLOR_MUTED))
        else:
            fmt.setForeground(QColor("#e2e8f0"))

        cursor.setCharFormat(fmt)
        cursor.insertText(entry + "\n")
        self._text.ensureCursorVisible()

        self._line_count += 1
        self._lbl_count.setText(f"{self._line_count} wpisów")

        if self._line_count > 5000:
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor, 500)
            cursor.removeSelectedText()
            self._line_count -= 500

    def _append_status(self, status: str):
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(COLOR_GOLD))
        ts = datetime.now().strftime("%H:%M:%S")
        cursor.setCharFormat(fmt)
        cursor.insertText(f"[{ts}] ▸ {status}\n")
        self._text.ensureCursorVisible()

        self._line_count += 1
        self._lbl_count.setText(f"{self._line_count} wpisów")

    def _clear(self):
        self._text.clear()
        self._line_count = 0
        self._lbl_count.setText("0 wpisów")


# ── Dziennik (Journal) ────────────────────────────────────────────────────────

class JournalWidget(QWidget):
    """Wyświetla rekomendacje, watch_later i notatki uczenia z BrainJournal."""

    def __init__(self, journal: "BrainJournal", parent=None):
        super().__init__(parent)
        self._journal = journal
        self._build_ui()
        self._refresh()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(15_000)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Stats bar ─────────────────────────────────────────────────────
        stats_frame = QFrame()
        stats_frame.setStyleSheet(
            f"background: {COLOR_CARD}; border: 1px solid {COLOR_BORDER}; border-radius: 6px;"
        )
        stats_lay = QHBoxLayout(stats_frame)
        stats_lay.setContentsMargins(16, 8, 16, 8)
        stats_lay.setSpacing(32)

        self._stat_labels: dict[str, QLabel] = {}
        for key, title in [
            ("scanned",    "Przeskanowane"),
            ("recommended","Rekomendowane"),
            ("watching",   "W obserwacji"),
            ("last_scan",  "Ostatni skan"),
        ]:
            col = QVBoxLayout()
            col.setSpacing(2)
            lbl_t = QLabel(title.upper())
            lbl_t.setStyleSheet(
                f"color: {COLOR_MUTED}; font-size: 9px; font-weight: bold;"
            )
            lbl_v = QLabel("—")
            lbl_v.setStyleSheet("font-size: 16px; font-weight: bold; color: #d4d4d4;")
            col.addWidget(lbl_t)
            col.addWidget(lbl_v)
            stats_lay.addLayout(col)
            self._stat_labels[key] = lbl_v
        stats_lay.addStretch()
        root.addWidget(stats_frame)

        # ── Splitter: recommended | watch_later + learning ────────────────
        splitter = QSplitter(Qt.Horizontal)

        # Lewy panel: Polecane teraz
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 4, 0)
        left_lay.setSpacing(6)

        lbl_rec = QLabel("POLECANE TERAZ (dla TradeBota)")
        lbl_rec.setStyleSheet(
            f"color: {COLOR_GOLD}; font-size: 10px; font-weight: bold; "
            "letter-spacing: 0.5px;"
        )
        left_lay.addWidget(lbl_rec)

        self._rec_table = QTableWidget()
        self._rec_table.setColumnCount(4)
        self._rec_table.setHorizontalHeaderLabels(["Symbol", "Akcja", "Pewność", "Score"])
        self._rec_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._rec_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._rec_table.verticalHeader().setVisible(False)
        self._rec_table.setAlternatingRowColors(True)
        self._rec_table.setColumnWidth(0, 80)
        self._rec_table.setColumnWidth(1, 70)
        self._rec_table.setColumnWidth(2, 80)
        self._rec_table.setColumnWidth(3, 80)
        left_lay.addWidget(self._rec_table)

        # Prawy panel: Obserwuj później + Notatki
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(4, 0, 0, 0)
        right_lay.setSpacing(6)

        lbl_watch = QLabel("OBSERWUJ PÓŹNIEJ")
        lbl_watch.setStyleSheet(
            f"color: {COLOR_MUTED}; font-size: 10px; font-weight: bold; "
            "letter-spacing: 0.5px;"
        )
        right_lay.addWidget(lbl_watch)

        self._watch_table = QTableWidget()
        self._watch_table.setColumnCount(2)
        self._watch_table.setHorizontalHeaderLabels(["Symbol", "Score"])
        self._watch_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._watch_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._watch_table.verticalHeader().setVisible(False)
        self._watch_table.setAlternatingRowColors(True)
        self._watch_table.setColumnWidth(0, 100)
        self._watch_table.setColumnWidth(1, 80)
        self._watch_table.setMaximumHeight(200)
        right_lay.addWidget(self._watch_table)

        lbl_notes = QLabel("NOTATKI UCZENIA")
        lbl_notes.setStyleSheet(
            f"color: {COLOR_RED}; font-size: 10px; font-weight: bold; "
            "letter-spacing: 0.5px;"
        )
        right_lay.addWidget(lbl_notes)

        self._notes_text = QTextEdit()
        self._notes_text.setReadOnly(True)
        self._notes_text.setStyleSheet(
            f"background: {COLOR_BG}; border: 1px solid {COLOR_BORDER}; "
            "font-size: 11px; color: #c0c0c0;"
        )
        right_lay.addWidget(self._notes_text)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([450, 380])
        root.addWidget(splitter, 1)

        # Wytyczne użytkownika
        guidance_frame = QFrame()
        guidance_frame.setStyleSheet(
            f"background: {COLOR_CARD}; border: 1px solid {COLOR_BORDER}; border-radius: 4px;"
        )
        g_lay = QHBoxLayout(guidance_frame)
        g_lay.setContentsMargins(12, 6, 12, 6)
        lbl_g = QLabel("WYTYCZNE:")
        lbl_g.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 10px; font-weight: bold;")
        self._guidance_lbl = QLabel("brak")
        self._guidance_lbl.setStyleSheet("color: #c0c0c0; font-size: 11px;")
        self._guidance_lbl.setWordWrap(True)
        g_lay.addWidget(lbl_g)
        g_lay.addWidget(self._guidance_lbl, 1)
        root.addWidget(guidance_frame)

    def refresh(self):
        self._refresh()

    def _refresh(self):
        data   = self._journal.read_all()
        stats  = data.get("stats", {})
        rec    = data.get("recommended_now", [])
        watch  = data.get("watch_later", [])
        notes  = data.get("learning_notes", [])
        last   = data.get("last_scan_ts")
        guid   = data.get("user_guidance", "brak")

        # Stats
        self._stat_labels["scanned"].setText(str(stats.get("total_scanned", 0)))
        self._stat_labels["recommended"].setText(str(len(rec)))
        self._stat_labels["watching"].setText(str(len(watch)))
        if last:
            try:
                dt   = datetime.fromisoformat(last)
                diff = (datetime.utcnow() - dt).total_seconds()
                if diff < 60:
                    last_str = f"{int(diff)}s temu"
                elif diff < 3600:
                    last_str = f"{int(diff/60)}min temu"
                else:
                    last_str = f"{diff/3600:.1f}h temu"
            except Exception:
                last_str = last[:16]
        else:
            last_str = "—"
        self._stat_labels["last_scan"].setText(last_str)

        # Recommended table
        self._rec_table.setRowCount(len(rec))
        for i, r in enumerate(rec):
            action = r.get("action", "—")
            color  = QColor(COLOR_GREEN if action == "BUY" else COLOR_RED if action == "SELL" else COLOR_MUTED)
            for col, text in enumerate([
                r.get("symbol", ""),
                action,
                f"{r.get('confidence', 0):.0%}",
                f"{r.get('score', 0):.4f}",
            ]):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                if col in (1, 2):
                    item.setForeground(color)
                self._rec_table.setItem(i, col, item)

        # Watch later table
        self._watch_table.setRowCount(len(watch))
        for i, w in enumerate(watch):
            for col, text in enumerate([w.get("symbol", ""), f"{w.get('score', 0):.4f}"]):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self._watch_table.setItem(i, col, item)

        # Learning notes (ostatnie 20)
        lines = []
        for n in reversed(notes[-20:]):
            ts  = n.get("ts", "")[:16].replace("T", " ")
            sym = n.get("symbol", "")
            lesson = n.get("lesson", "")
            lines.append(f"[{ts}] {sym}: {lesson}")
        self._notes_text.setPlainText("\n\n".join(lines) if lines else "Brak notatek uczenia.")

        # Guidance
        self._guidance_lbl.setText(guid[:200] if guid else "brak")


# ── Czat ──────────────────────────────────────────────────────────────────────

class ChatWidget(QWidget):
    """Interfejs czatu z BrainBotem."""

    def __init__(self, scanner: "BrainScannerWorker", journal: "BrainJournal", parent=None):
        super().__init__(parent)
        self._scanner  = scanner
        self._journal  = journal
        self._waiting  = False
        self._build_ui()
        self._load_history()

        # Odbieraj odpowiedzi z BrainBota
        if scanner is not None:
            scanner.chat_response_ready.connect(self._on_brain_response)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Header
        hdr = QFrame()
        hdr.setStyleSheet(
            f"background: {COLOR_CARD}; border: 1px solid {COLOR_BORDER}; border-radius: 6px;"
        )
        h_lay = QHBoxLayout(hdr)
        h_lay.setContentsMargins(16, 10, 16, 10)
        lbl_title = QLabel("CZAT Z BRAINBOTEM")
        lbl_title.setStyleSheet(
            f"color: {COLOR_GOLD}; font-size: 12px; font-weight: bold; letter-spacing: 0.5px;"
        )
        self._status_lbl = QLabel("Gotowy")
        self._status_lbl.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        h_lay.addWidget(lbl_title)
        h_lay.addStretch()
        h_lay.addWidget(self._status_lbl)
        root.addWidget(hdr)

        # Historia czatu
        self._chat_view = QTextEdit()
        self._chat_view.setReadOnly(True)
        self._chat_view.setStyleSheet(
            f"background: {COLOR_BG}; border: 1px solid {COLOR_BORDER}; "
            "font-size: 12px; color: #d4d4d4; padding: 8px;"
        )
        root.addWidget(self._chat_view, 1)

        # Pole wejściowe
        input_lay = QHBoxLayout()
        input_lay.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "Napisz do BrainBota… (np. 'Skup się na spółkach technologicznych', "
            "'Jakie masz teraz rekomendacje?')"
        )
        self._input.setStyleSheet(
            f"background: {COLOR_CARD}; border: 1px solid {COLOR_BORDER}; "
            "color: #d4d4d4; font-size: 12px; padding: 6px; border-radius: 4px;"
        )
        self._input.returnPressed.connect(self._send)

        self._btn_send = QPushButton("Wyślij")
        self._btn_send.setFixedWidth(90)
        self._btn_send.setFixedHeight(34)
        self._btn_send.clicked.connect(self._send)

        input_lay.addWidget(self._input)
        input_lay.addWidget(self._btn_send)
        root.addLayout(input_lay)

        hint = QLabel(
            "💡 Możesz nakierowywać BrainBota: 'unikaj małych spółek', "
            "'skup się na dużych wolumenach', 'ignoruj ETF-y'"
        )
        hint.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 10px;")
        hint.setWordWrap(True)
        root.addWidget(hint)

    def _load_history(self):
        """Załaduj historię czatu z journala."""
        history = self._journal.get_chat_history()
        self._chat_view.clear()
        for msg in history[-50:]:
            self._append_message(msg.get("role", "?"), msg.get("content", ""))

    def _send(self):
        text = self._input.text().strip()
        if not text or self._waiting:
            return

        self._input.clear()
        self._append_message("user", text)

        if self._scanner is None or not self._scanner.isRunning():
            self._append_message(
                "system",
                "BrainBot nie jest uruchomiony. Uruchom aplikację z włączonym BrainBotem."
            )
            return

        self._waiting = True
        self._btn_send.setEnabled(False)
        self._status_lbl.setText("BrainBot myśli…")
        self._scanner.send_chat_message(text)

    def _on_brain_response(self, response: str):
        self._waiting = False
        self._btn_send.setEnabled(True)
        self._status_lbl.setText("Gotowy")
        self._append_message("brain", response)

    def _append_message(self, role: str, content: str):
        if role == "user":
            color  = "#74c0fc"
            prefix = "Ty"
        elif role == "brain":
            color  = COLOR_GREEN
            prefix = "BrainBot"
        else:
            color  = COLOR_MUTED
            prefix = "System"

        ts = datetime.now().strftime("%H:%M:%S")
        html = (
            f'<div style="margin-bottom:10px;">'
            f'<span style="color:{COLOR_MUTED};font-size:10px;">[{ts}]</span> '
            f'<span style="color:{color};font-weight:bold;">{prefix}:</span><br>'
            f'<span style="color:#d4d4d4;">{content}</span>'
            f'</div>'
        )
        self._chat_view.append(html)
        # Przewiń na dół
        sb = self._chat_view.verticalScrollBar()
        sb.setValue(sb.maximum())


# ── Główna zakładka BrainBot ──────────────────────────────────────────────────

class BrainBotTab(QWidget):
    """
    Zakładka BrainBot z trzema podzakładkami:
      Logi    — tabela brain scores + status skanera
      Dziennik — rekomendacje, watch later, notatki uczenia
      Czat    — interaktywny czat z BrainBotem
    """

    def __init__(
        self,
        config: dict,
        brain: Optional["SymbolBrain"] = None,
        worker=None,
        scanner: Optional["BrainScannerWorker"] = None,
        journal: Optional["BrainJournal"] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._scanner = scanner
        self._journal = journal

        self._inner = QTabWidget()
        self._inner.setDocumentMode(True)

        # Podzakładka: Konsola (logi skanera w czasie rzeczywistym)
        self._konsola = ScanConsoleWidget(scanner) if scanner else _placeholder(
            "Konsola niedostępna — BrainBot nie jest uruchomiony."
        )

        # Podzakładka: Logi (istniejący BrainTab z brain scores)
        self._logi = BrainTab(config, brain=brain, worker=worker, scanner=scanner)

        # Podzakładka: Dziennik
        if journal is not None:
            self._dziennik = JournalWidget(journal)
        else:
            self._dziennik = _placeholder("Dziennik niedostępny — brak journala BrainBota.")

        # Podzakładka: Czat
        self._czat = ChatWidget(scanner, journal) if (scanner and journal) else _placeholder(
            "Czat niedostępny — BrainBot nie jest uruchomiony."
        )

        self._inner.addTab(self._konsola,  "🖥  Konsola")
        self._inner.addTab(self._logi,     "📋  Logi")
        self._inner.addTab(self._dziennik, "📓  Dziennik")
        self._inner.addTab(self._czat,     "💬  Czat")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(16)
        lay.addWidget(make_page_header("BrainBot", "Autonomiczny skaner rynku AI"))
        lay.addWidget(self._inner)

    # ── Scanner slots (forwarding) ────────────────────────────────────────

    def on_scanner_status(self, status: str):
        self._logi.on_scanner_status(status)

    def on_scan_completed(self, scanned: int, total: int):
        self._logi.on_scan_completed(scanned, total)
        if isinstance(self._dziennik, JournalWidget):
            self._dziennik.refresh()


def _placeholder(text: str) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 12px;")
    lay.addWidget(lbl)
    return w
