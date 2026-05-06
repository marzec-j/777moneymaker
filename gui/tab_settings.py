from __future__ import annotations

import os
from pathlib import Path

import yaml
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from . import log_action
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget,
)
from .styles import COLOR_MUTED, make_page_header


# ── Background workers ────────────────────────────────────────────────────────

class _AlpacaCheckWorker(QThread):
    done = Signal(bool, str)

    def __init__(self, api_key: str, secret_key: str, mode: str):
        super().__init__()
        self._api_key    = api_key
        self._secret_key = secret_key
        self._mode       = mode

    def run(self):
        try:
            from alpaca.trading.client import TradingClient
            paper  = (self._mode == "paper")
            client = TradingClient(api_key=self._api_key, secret_key=self._secret_key, paper=paper)
            acc    = client.get_account()
            label  = "PAPER" if paper else "LIVE"
            self.done.emit(True,
                f"Połączono z Alpaca ({label})\n"
                f"Equity: ${float(acc.equity):,.2f}  |  Cash: ${float(acc.cash):,.2f}\n"
                f"Status: {acc.status}")
        except ImportError:
            self.done.emit(False, "Brak alpaca-py — uruchom: pip install alpaca-py")
        except Exception as exc:
            self.done.emit(False, f"Błąd połączenia:\n{exc}")


class _FinnhubCheckWorker(QThread):
    done = Signal(bool, str)

    def __init__(self, api_key: str):
        super().__init__()
        self._api_key = api_key

    def run(self):
        try:
            from modules.finnhub_client import FinnhubClient
            client = FinnhubClient(self._api_key)
            if client.is_available():
                news = client.get_market_news(count=3)
                self.done.emit(True, f"Połączono z Finnhub  |  test: {len(news)} newsów")
            else:
                self.done.emit(False, "Nieprawidłowy klucz API lub brak dostępu")
        except Exception as exc:
            self.done.emit(False, f"Błąd:\n{exc}")


# ── Main settings tab ─────────────────────────────────────────────────────────

class SettingsTab(QWidget):
    settings_saved = Signal()

    def __init__(self, config: dict, config_path: str = "config.yaml", parent=None):
        super().__init__(parent)
        self._config      = config
        self._config_path = config_path
        self._setup_ui()
        self._load_values()

    # ── Build UI ──────────────────────────────────────────────────────────

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        outer.addWidget(make_page_header("Settings", "Konfiguracja systemu"))

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_broker_tab(),   "🏦  Broker")
        self._tabs.addTab(self._build_api_tab(),      "🔑  API")
        self._tabs.addTab(self._build_ai_tab(),       "🧠  AI")
        self._tabs.addTab(self._build_risk_tab(),     "⚖️  Risk")
        self._tabs.addTab(self._build_other_tab(),    "⚙️  Pozostałe")
        outer.addWidget(self._tabs)

    # ── Sub-tab builders ──────────────────────────────────────────────────

    def _build_broker_tab(self) -> QWidget:
        w, root = _scrolled()

        grp = QGroupBox("Broker")
        form = QFormLayout(grp)
        form.setSpacing(10)

        self._broker_combo = QComboBox()
        self._broker_combo.addItems(["alpaca"])
        form.addRow("Broker:", self._broker_combo)
        form.addRow("", _note("Alpaca Markets — obsługa paper i live trading przez API"))

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["paper", "live"])
        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)
        form.addRow("Tryb:", self._mode_combo)

        self._live_warning = QLabel(
            "UWAGA: Tryb LIVE używa prawdziwych pieniędzy! "
            "Sprawdź klucze API przed uruchomieniem."
        )
        self._live_warning.setStyleSheet("color: #ff6b6b; font-size: 11px; font-weight: bold;")
        self._live_warning.setWordWrap(True)
        self._live_warning.setVisible(False)
        form.addRow("", self._live_warning)

        root.addWidget(grp)
        root.addStretch()

        sl, lbl = _save_row_widgets(self._save_broker)
        self._lbl_save_broker = lbl
        root.addLayout(sl)
        return w

    def _build_api_tab(self) -> QWidget:
        w, root = _scrolled()

        # ── Alpaca ────────────────────────────────────────────────────────
        grp_alp = QGroupBox("Alpaca API")
        form_alp = QFormLayout(grp_alp)
        form_alp.setSpacing(10)

        self._api_key = QLineEdit()
        self._api_key.setPlaceholderText("PKXXXXXXXXXXXXXXXX")
        form_alp.addRow("API Key:", self._api_key)

        secret_row = QHBoxLayout()
        self._api_secret = QLineEdit()
        self._api_secret.setPlaceholderText("••••••••••••••••")
        self._api_secret.setEchoMode(QLineEdit.Password)
        self._btn_save_alpaca_keys = QPushButton("💾  Zapisz klucze")
        self._btn_save_alpaca_keys.setFixedWidth(140)
        self._btn_save_alpaca_keys.clicked.connect(self._save_alpaca_keys)
        secret_row.addWidget(self._api_secret)
        secret_row.addWidget(self._btn_save_alpaca_keys)
        form_alp.addRow("Secret Key:", secret_row)

        form_alp.addRow("", _note(
            "Klucze z alpaca.markets → Your Account → API Keys. "
            "Paper i Live mają oddzielne klucze API."
        ))

        alp_check_row = QHBoxLayout()
        self._btn_check_alpaca = QPushButton("🔌  Sprawdź połączenie")
        self._btn_check_alpaca.setFixedWidth(190)
        self._btn_check_alpaca.clicked.connect(self._check_alpaca)
        self._lbl_alpaca_check = QLabel("")
        self._lbl_alpaca_check.setWordWrap(True)
        alp_check_row.addWidget(self._btn_check_alpaca)
        alp_check_row.addWidget(self._lbl_alpaca_check)
        alp_check_row.addStretch()
        form_alp.addRow("", alp_check_row)

        root.addWidget(grp_alp)

        # ── Finnhub ───────────────────────────────────────────────────────
        grp_fh = QGroupBox("Finnhub API")
        form_fh = QFormLayout(grp_fh)
        form_fh.setSpacing(10)

        fh_key_row = QHBoxLayout()
        self._finnhub_key = QLineEdit()
        self._finnhub_key.setPlaceholderText("cxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        self._btn_save_finnhub = QPushButton("💾  Zapisz klucz")
        self._btn_save_finnhub.setFixedWidth(140)
        self._btn_save_finnhub.clicked.connect(self._save_finnhub_key)
        fh_key_row.addWidget(self._finnhub_key)
        fh_key_row.addWidget(self._btn_save_finnhub)
        form_fh.addRow("API Key:", fh_key_row)

        form_fh.addRow("", _note(
            "Klucz z finnhub.io → Dashboard → API Key. "
            "Free plan: 60 req/min — wystarczy do newsów."
        ))

        fh_check_row = QHBoxLayout()
        self._btn_check_finnhub = QPushButton("🔌  Sprawdź połączenie")
        self._btn_check_finnhub.setFixedWidth(190)
        self._btn_check_finnhub.clicked.connect(self._check_finnhub)
        self._lbl_finnhub_check = QLabel("")
        self._lbl_finnhub_check.setWordWrap(True)
        fh_check_row.addWidget(self._btn_check_finnhub)
        fh_check_row.addWidget(self._lbl_finnhub_check)
        fh_check_row.addStretch()
        form_fh.addRow("", fh_check_row)

        root.addWidget(grp_fh)
        root.addStretch()
        return w

    def _build_ai_tab(self) -> QWidget:
        w, root = _scrolled()

        grp = QGroupBox("Ollama (Local LLM)")
        form = QFormLayout(grp)
        form.setSpacing(10)

        self._ollama_url = QLineEdit("http://localhost:11434")
        form.addRow("URL:", self._ollama_url)
        form.addRow("", _note("Przed uruchomieniem bota upewnij się, że 'ollama serve' działa."))

        self._model_combo = QComboBox()
        self._model_combo.addItems(["mistral", "phi3:mini", "llama3", "neural-chat", "llama2"])
        self._model_combo.setEditable(True)
        form.addRow("Model:", self._model_combo)

        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(30, 600)
        self._timeout_spin.setSuffix(" s")
        form.addRow("Timeout:", self._timeout_spin)

        self._temp_spin = QDoubleSpinBox()
        self._temp_spin.setRange(0.0, 1.0)
        self._temp_spin.setSingleStep(0.05)
        self._temp_spin.setDecimals(2)
        form.addRow("Temperature:", self._temp_spin)
        form.addRow("", _note("Low = deterministyczny  |  High = kreatywny"))

        self._conf_spin = QDoubleSpinBox()
        self._conf_spin.setRange(0.0, 1.0)
        self._conf_spin.setSingleStep(0.05)
        self._conf_spin.setDecimals(2)
        self._conf_spin.setSuffix("  (0–1)")
        form.addRow("Min Confidence:", self._conf_spin)

        root.addWidget(grp)
        root.addStretch()

        sl, lbl = _save_row_widgets(self._save_ai)
        self._lbl_save_ai = lbl
        root.addLayout(sl)
        return w

    def _build_risk_tab(self) -> QWidget:
        w, root = _scrolled()

        grp = QGroupBox("Risk Management")
        form = QFormLayout(grp)
        form.setSpacing(10)

        self._sl_spin = QDoubleSpinBox()
        self._sl_spin.setRange(0.001, 0.5)
        self._sl_spin.setSingleStep(0.005)
        self._sl_spin.setDecimals(3)
        self._sl_spin.setSuffix("  (np. 0.02 = 2%)")
        form.addRow("Stop Loss:", self._sl_spin)

        self._tp_spin = QDoubleSpinBox()
        self._tp_spin.setRange(0.001, 1.0)
        self._tp_spin.setSingleStep(0.005)
        self._tp_spin.setDecimals(3)
        self._tp_spin.setSuffix("  (np. 0.04 = 4%)")
        form.addRow("Take Profit:", self._tp_spin)

        self._pos_spin = QDoubleSpinBox()
        self._pos_spin.setRange(0.01, 1.0)
        self._pos_spin.setSingleStep(0.01)
        self._pos_spin.setDecimals(2)
        self._pos_spin.setSuffix("  (np. 0.10 = 10%)")
        form.addRow("Max Position %:", self._pos_spin)

        self._daily_loss_spin = QDoubleSpinBox()
        self._daily_loss_spin.setRange(0.005, 0.5)
        self._daily_loss_spin.setSingleStep(0.005)
        self._daily_loss_spin.setDecimals(3)
        self._daily_loss_spin.setSuffix("  (np. 0.03 = 3%)")
        form.addRow("Daily Loss Limit:", self._daily_loss_spin)

        self._max_pos_spin = QSpinBox()
        self._max_pos_spin.setRange(1, 50)
        form.addRow("Max Open Positions:", self._max_pos_spin)

        root.addWidget(grp)
        root.addStretch()

        sl, lbl = _save_row_widgets(self._save_risk)
        self._lbl_save_risk = lbl
        root.addLayout(sl)
        return w

    def _build_other_tab(self) -> QWidget:
        w, root = _scrolled()

        grp = QGroupBox("Loop")
        form = QFormLayout(grp)
        form.setSpacing(10)

        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(10, 3600)
        self._interval_spin.setSuffix(" s")
        form.addRow("Interwał cyklu:", self._interval_spin)
        form.addRow("", _note("Jak często bot uruchamia analizę (w sekundach)."))

        root.addWidget(grp)
        root.addStretch()

        sl, lbl = _save_row_widgets(self._save_other)
        self._lbl_save_other = lbl
        root.addLayout(sl)
        return w

    # ── Load ──────────────────────────────────────────────────────────────

    def _load_values(self):
        # Broker
        mode = self._config.get("alpaca_mode", "paper")
        idx  = self._mode_combo.findText(mode)
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)
        self._on_mode_changed(mode)

        # API
        self._api_key.setText(os.getenv("ALPACA_API_KEY", ""))
        self._api_secret.setText(os.getenv("ALPACA_SECRET_KEY", ""))
        self._finnhub_key.setText(os.getenv("FINNHUB_API_KEY", ""))

        # AI
        llm = self._config.get("llm", {})
        self._ollama_url.setText(llm.get("base_url", "http://localhost:11434"))
        model = llm.get("model", "mistral")
        idx   = self._model_combo.findText(model)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)
        else:
            self._model_combo.setCurrentText(model)
        self._timeout_spin.setValue(llm.get("timeout", 120))
        self._temp_spin.setValue(llm.get("temperature", 0.1))
        self._conf_spin.setValue(self._config.get("risk", {}).get("min_confidence", 0.65))

        # Risk
        risk = self._config.get("risk", {})
        self._sl_spin.setValue(risk.get("stop_loss_pct", 0.02))
        self._tp_spin.setValue(risk.get("take_profit_pct", 0.04))
        self._pos_spin.setValue(risk.get("max_position_pct", 0.10))
        self._daily_loss_spin.setValue(risk.get("max_daily_loss_pct", 0.03))
        self._max_pos_spin.setValue(risk.get("max_open_positions", 5))

        # Other
        self._interval_spin.setValue(self._config.get("loop_interval", 60))

    # ── Save methods (one per sub-tab) ────────────────────────────────────

    def _save_broker(self):
        self._config["broker"]      = "alpaca"
        self._config["alpaca_mode"] = self._mode_combo.currentText()
        if self._write_config():
            _flash(self._lbl_save_broker, "✓ Zapisano")
            log_action("Zmieniono ustawienia")
            self.settings_saved.emit()

    def _save_ai(self):
        self._config.setdefault("llm", {})
        self._config["llm"]["base_url"]    = self._ollama_url.text().strip()
        self._config["llm"]["model"]       = self._model_combo.currentText()
        self._config["llm"]["timeout"]     = self._timeout_spin.value()
        self._config["llm"]["temperature"] = self._temp_spin.value()
        self._config.setdefault("risk", {})["min_confidence"] = self._conf_spin.value()
        if self._write_config():
            _flash(self._lbl_save_ai, "✓ Zapisano")
            log_action("Zmieniono ustawienia")
            self.settings_saved.emit()

    def _save_risk(self):
        r = self._config.setdefault("risk", {})
        r["stop_loss_pct"]      = self._sl_spin.value()
        r["take_profit_pct"]    = self._tp_spin.value()
        r["max_position_pct"]   = self._pos_spin.value()
        r["max_daily_loss_pct"] = self._daily_loss_spin.value()
        r["max_open_positions"] = self._max_pos_spin.value()
        if self._write_config():
            _flash(self._lbl_save_risk, "✓ Zapisano")
            log_action("Zmieniono ustawienia")
            self.settings_saved.emit()

    def _save_other(self):
        self._config["loop_interval"] = self._interval_spin.value()
        if self._write_config():
            _flash(self._lbl_save_other, "✓ Zapisano")
            log_action("Zmieniono ustawienia")
            self.settings_saved.emit()

    def _save_alpaca_keys(self):
        key    = self._api_key.text().strip()
        secret = self._api_secret.text().strip()
        if not key or not secret:
            QMessageBox.warning(self, "Brak danych", "Wpisz API Key i Secret Key przed zapisem.")
            return
        env = _read_env()
        env["ALPACA_API_KEY"]    = key
        env["ALPACA_SECRET_KEY"] = secret
        if _write_env(env):
            _flash_btn(self._btn_save_alpaca_keys, "✓ Zapisano", self._btn_save_alpaca_keys.text())
            log_action("Zmieniono ustawienia")
            self.settings_saved.emit()

    def _save_finnhub_key(self):
        key = self._finnhub_key.text().strip()
        if not key:
            QMessageBox.warning(self, "Brak danych", "Wpisz Finnhub API Key przed zapisem.")
            return
        env = _read_env()
        env["FINNHUB_API_KEY"] = key
        if _write_env(env):
            _flash_btn(self._btn_save_finnhub, "✓ Zapisano", self._btn_save_finnhub.text())
            log_action("Zmieniono ustawienia")
            self.settings_saved.emit()

    # ── Check connections ─────────────────────────────────────────────────

    def _on_mode_changed(self, mode: str):
        self._live_warning.setVisible(mode == "live")

    def _check_alpaca(self):
        key    = self._api_key.text().strip()
        secret = self._api_secret.text().strip()
        if not key or not secret:
            self._lbl_alpaca_check.setStyleSheet("color: #ff6b6b; font-size: 11px;")
            self._lbl_alpaca_check.setText("Wpisz API Key i Secret Key.")
            return
        log_action("Sprawdzono połączenie Alpaca")
        self._btn_check_alpaca.setEnabled(False)
        self._lbl_alpaca_check.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        self._lbl_alpaca_check.setText("Łączenie…")
        self._alpaca_worker = _AlpacaCheckWorker(key, secret, self._mode_combo.currentText())
        self._alpaca_worker.done.connect(self._on_alpaca_done)
        self._alpaca_worker.start()

    def _on_alpaca_done(self, ok: bool, msg: str):
        self._btn_check_alpaca.setEnabled(True)
        color = "#4ec94e" if ok else "#ff6b6b"
        self._lbl_alpaca_check.setStyleSheet(f"color: {color}; font-size: 11px;")
        self._lbl_alpaca_check.setText(msg)

    def _check_finnhub(self):
        key = self._finnhub_key.text().strip()
        if not key:
            self._lbl_finnhub_check.setStyleSheet("color: #ff6b6b; font-size: 11px;")
            self._lbl_finnhub_check.setText("Wpisz API Key.")
            return
        log_action("Sprawdzono połączenie Finnhub")
        self._btn_check_finnhub.setEnabled(False)
        self._lbl_finnhub_check.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        self._lbl_finnhub_check.setText("Łączenie…")
        self._finnhub_worker = _FinnhubCheckWorker(key)
        self._finnhub_worker.done.connect(self._on_finnhub_done)
        self._finnhub_worker.start()

    def _on_finnhub_done(self, ok: bool, msg: str):
        self._btn_check_finnhub.setEnabled(True)
        color = "#4ec94e" if ok else "#ff6b6b"
        self._lbl_finnhub_check.setStyleSheet(f"color: {color}; font-size: 11px;")
        self._lbl_finnhub_check.setText(msg)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _write_config(self) -> bool:
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                yaml.dump(self._config, f, default_flow_style=False, allow_unicode=True)
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Błąd", f"Nie można zapisać config.yaml:\n{exc}")
            return False


# ── Module-level helpers ──────────────────────────────────────────────────────

def _scrolled() -> tuple[QWidget, QVBoxLayout]:
    """Zwraca (widget z QScrollArea, layout wewnętrzny)."""
    outer = QWidget()
    scroll = QScrollArea(outer)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)

    inner = QWidget()
    root  = QVBoxLayout(inner)
    root.setContentsMargins(20, 16, 20, 16)
    root.setSpacing(16)

    scroll.setWidget(inner)
    lay = QVBoxLayout(outer)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(scroll)
    return outer, root


def _note(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
    lbl.setWordWrap(True)
    return lbl


def _save_row_widgets(callback) -> tuple[QHBoxLayout, QLabel]:
    """Zwraca (layout, label statusu). Przycisk wywołuje callback."""
    row = QHBoxLayout()
    row.addStretch()
    lbl = QLabel("")
    lbl.setStyleSheet("font-size: 11px;")
    btn = QPushButton("💾  Zapisz")
    btn.setFixedWidth(120)
    btn.clicked.connect(callback)
    row.addWidget(lbl)
    row.addWidget(btn)
    return row, lbl


def _flash(label: QLabel, text: str, ms: int = 2500):
    label.setStyleSheet("color: #4ec94e; font-size: 11px;")
    label.setText(text)
    QTimer.singleShot(ms, lambda: (label.setText(""), label.setStyleSheet("font-size: 11px;")))


def _flash_btn(btn: QPushButton, text: str, original: str, ms: int = 2500):
    btn.setText(text)
    btn.setStyleSheet("color: #4ec94e;")
    QTimer.singleShot(ms, lambda: (btn.setText(original), btn.setStyleSheet("")))


def _read_env() -> dict:
    env_path = Path(".env")
    env_map: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env_map[k.strip()] = v.strip()
    return env_map


def _write_env(env_map: dict) -> bool:
    try:
        with open(".env", "w", encoding="utf-8") as f:
            for k, v in env_map.items():
                f.write(f"{k}={v}\n")
        return True
    except Exception as exc:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Błąd", f"Nie można zapisać .env:\n{exc}")
        return False
