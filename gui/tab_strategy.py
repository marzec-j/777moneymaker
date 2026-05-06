from __future__ import annotations

from pathlib import Path

import yaml
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSlider, QSpinBox, QVBoxLayout, QWidget,
)
from .styles import COLOR_MUTED, COLOR_GREEN


class StrategyTab(QWidget):
    def __init__(self, config: dict, config_path: str = "config.yaml", parent=None):
        super().__init__(parent)
        self._config = config
        self._config_path = config_path
        self._setup_ui()
        self._load_values()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(16)

        # ── LLM / AI ─────────────────────────────────────────────────────
        grp_llm = QGroupBox("AI Model")
        form_llm = QFormLayout(grp_llm)
        form_llm.setSpacing(10)

        self._model_combo = QComboBox()
        self._model_combo.addItems(["mistral", "phi3:mini", "llama3", "neural-chat", "llama2"])
        self._model_combo.setEditable(True)
        form_llm.addRow("Model:", self._model_combo)

        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(30, 600)
        self._timeout_spin.setSuffix(" s")
        form_llm.addRow("LLM Timeout:", self._timeout_spin)

        self._temp_spin = QDoubleSpinBox()
        self._temp_spin.setRange(0.0, 1.0)
        self._temp_spin.setSingleStep(0.05)
        self._temp_spin.setDecimals(2)
        hint = QLabel("Low = deterministic  |  High = creative")
        hint.setStyleSheet(f"color: {COLOR_MUTED}; font-size: 11px;")
        form_llm.addRow("Temperature:", self._temp_spin)
        form_llm.addRow("", hint)

        self._conf_spin = QDoubleSpinBox()
        self._conf_spin.setRange(0.0, 1.0)
        self._conf_spin.setSingleStep(0.05)
        self._conf_spin.setDecimals(2)
        self._conf_spin.setSuffix("  (0–1)")
        form_llm.addRow("Min Confidence:", self._conf_spin)

        root.addWidget(grp_llm)

        # ── Risk ──────────────────────────────────────────────────────────
        grp_risk = QGroupBox("Risk Management")
        form_risk = QFormLayout(grp_risk)
        form_risk.setSpacing(10)

        self._sl_spin = QDoubleSpinBox()
        self._sl_spin.setRange(0.001, 0.5)
        self._sl_spin.setSingleStep(0.005)
        self._sl_spin.setDecimals(3)
        self._sl_spin.setSuffix("  (e.g. 0.02 = 2%)")
        form_risk.addRow("Stop Loss:", self._sl_spin)

        self._tp_spin = QDoubleSpinBox()
        self._tp_spin.setRange(0.001, 1.0)
        self._tp_spin.setSingleStep(0.005)
        self._tp_spin.setDecimals(3)
        self._tp_spin.setSuffix("  (e.g. 0.04 = 4%)")
        form_risk.addRow("Take Profit:", self._tp_spin)

        self._pos_spin = QDoubleSpinBox()
        self._pos_spin.setRange(0.01, 1.0)
        self._pos_spin.setSingleStep(0.01)
        self._pos_spin.setDecimals(2)
        self._pos_spin.setSuffix("  (e.g. 0.10 = 10%)")
        form_risk.addRow("Max Position %:", self._pos_spin)

        self._daily_loss_spin = QDoubleSpinBox()
        self._daily_loss_spin.setRange(0.005, 0.5)
        self._daily_loss_spin.setSingleStep(0.005)
        self._daily_loss_spin.setDecimals(3)
        self._daily_loss_spin.setSuffix("  (e.g. 0.03 = 3%)")
        form_risk.addRow("Daily Loss Limit:", self._daily_loss_spin)

        self._max_pos_spin = QSpinBox()
        self._max_pos_spin.setRange(1, 20)
        form_risk.addRow("Max Open Positions:", self._max_pos_spin)

        root.addWidget(grp_risk)

        # ── Loop interval ─────────────────────────────────────────────────
        grp_loop = QGroupBox("Loop")
        form_loop = QFormLayout(grp_loop)
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(10, 3600)
        self._interval_spin.setSuffix(" s")
        form_loop.addRow("Refresh Interval:", self._interval_spin)
        root.addWidget(grp_loop)

        # ── Save button ───────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_save = QPushButton("💾  Save to config.yaml")
        self._btn_save.setFixedWidth(200)
        self._btn_save.clicked.connect(self._save)
        btn_row.addWidget(self._btn_save)
        root.addLayout(btn_row)
        root.addStretch()

    def _load_values(self):
        llm  = self._config.get("llm", {})
        risk = self._config.get("risk", {})

        idx = self._model_combo.findText(llm.get("model", "mistral"))
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)
        else:
            self._model_combo.setCurrentText(llm.get("model", "mistral"))

        self._timeout_spin.setValue(llm.get("timeout", 120))
        self._temp_spin.setValue(llm.get("temperature", 0.1))
        self._conf_spin.setValue(risk.get("min_confidence", 0.65))
        self._sl_spin.setValue(risk.get("stop_loss_pct", 0.02))
        self._tp_spin.setValue(risk.get("take_profit_pct", 0.04))
        self._pos_spin.setValue(risk.get("max_position_pct", 0.10))
        self._daily_loss_spin.setValue(risk.get("max_daily_loss_pct", 0.03))
        self._max_pos_spin.setValue(risk.get("max_open_positions", 5))
        self._interval_spin.setValue(self._config.get("loop_interval", 60))

    def _save(self):
        self._config.setdefault("llm", {})
        self._config.setdefault("risk", {})

        self._config["llm"]["model"]       = self._model_combo.currentText()
        self._config["llm"]["timeout"]     = self._timeout_spin.value()
        self._config["llm"]["temperature"] = self._temp_spin.value()
        self._config["risk"]["min_confidence"]     = self._conf_spin.value()
        self._config["risk"]["stop_loss_pct"]      = self._sl_spin.value()
        self._config["risk"]["take_profit_pct"]    = self._tp_spin.value()
        self._config["risk"]["max_position_pct"]   = self._pos_spin.value()
        self._config["risk"]["max_daily_loss_pct"] = self._daily_loss_spin.value()
        self._config["risk"]["max_open_positions"] = self._max_pos_spin.value()
        self._config["loop_interval"]              = self._interval_spin.value()

        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                yaml.dump(self._config, f, default_flow_style=False, allow_unicode=True)
            QMessageBox.information(self, "Saved", f"Settings saved to {self._config_path}")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Could not save config:\n{exc}")
