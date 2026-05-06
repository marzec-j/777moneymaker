"""
777moneymaker — GUI Dashboard
==============================
Run with:
    python dashboard.py
"""

import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

load_dotenv()

CONFIG_PATH = "config.yaml"


def load_config() -> dict:
    p = Path(CONFIG_PATH)
    if not p.exists():
        print(f"[ERROR] {CONFIG_PATH} not found")
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("777moneymaker")
    app.setFont(QFont("Segoe UI", 10))

    config = load_config()

    from modules.trade_logger import setup_logger, setup_brainbot_logger
    setup_logger(config)
    setup_brainbot_logger(config)

    from gui.main_window import MainWindow
    window = MainWindow(config, config_path=CONFIG_PATH)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
