"""
Moduł logowania: zapisuje decyzje AI, transakcje i błędy.
"""

import csv
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import colorlog


def setup_logger(config: dict) -> logging.Logger:
    log_cfg = config.get("logging", {})
    level   = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_dir = Path(log_cfg.get("log_dir", "logs")).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s]%(reset)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        },
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_dir / "tradebot.log", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )

    logger = logging.getLogger("777moneymaker")
    logger.setLevel(level)

    has_file = any(isinstance(h, logging.FileHandler) for h in logger.handlers)
    has_stream = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in logger.handlers
    )
    if not has_file:
        logger.addHandler(file_handler)
    if not has_stream:
        logger.addHandler(handler)
    return logger


def setup_brainbot_logger(config: dict) -> logging.Logger:
    log_cfg = config.get("logging", {})
    level   = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_dir = Path(log_cfg.get("log_dir", "logs")).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s]%(reset)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        },
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_dir / "brainbot.log", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )

    logger = logging.getLogger("brainbot")
    logger.setLevel(level)
    logger.propagate = False

    has_file = any(isinstance(h, logging.FileHandler) for h in logger.handlers)
    has_stream = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in logger.handlers
    )
    if not has_file:
        logger.addHandler(file_handler)
    if not has_stream:
        logger.addHandler(handler)
    return logger


class _JsonEncoder(json.JSONEncoder):
    """Handles numpy/pandas types that sneak in from market data."""
    def default(self, obj):
        try:
            import numpy as np
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, (np.bool_,)):
                return bool(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
        except ImportError:
            pass
        try:
            import pandas as pd
            if isinstance(obj, pd.Timestamp):
                return obj.isoformat()
        except ImportError:
            pass
        return super().default(obj)


def _data_dir(config: dict) -> Path:
    data_cfg = config.get("data", {})
    p = Path(data_cfg.get("data_dir", "data")).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


class TradeLogger:
    """Zapisuje transakcje do CSV i decyzje AI do JSONL (w data/)."""

    def __init__(self, config: dict):
        data = _data_dir(config)
        data_cfg = config.get("data", {})

        self._trades_path    = data / data_cfg.get("trades_file",    "trades.csv")
        self._decisions_path = data / data_cfg.get("decisions_file", "ai_decisions.jsonl")
        self._logger = logging.getLogger("777moneymaker")
        self._ensure_trades_header()

    def _ensure_trades_header(self):
        if not self._trades_path.exists():
            with open(self._trades_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "symbol", "action", "qty", "price",
                    "order_id", "stop_loss", "take_profit", "confidence",
                    "ai_reasoning_summary"
                ])

    def log_trade(self, symbol: str, action: str, qty: float, price: float,
                  order_id: str, stop_loss: float, take_profit: float,
                  confidence: float, reasoning: str):
        row = [
            datetime.utcnow().isoformat(), symbol, action, qty, price,
            order_id, stop_loss, take_profit, confidence,
            reasoning[:200].replace("\n", " ")
        ]
        try:
            with open(self._trades_path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(row)
        except Exception as exc:
            self._logger.error(f"Failed to write trade to CSV: {exc}")

        self._logger.info(
            f"TRADE | {action} {qty}x {symbol} @ ${price:.2f} "
            f"| SL=${stop_loss:.2f} TP=${take_profit:.2f} "
            f"| conf={confidence:.0%} | order={order_id}"
        )

    def log_ai_decision(self, symbol: str, decision: dict, market_snapshot: dict):
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "decision": decision,
            "market_snapshot": market_snapshot,
        }
        try:
            line = json.dumps(record, cls=_JsonEncoder, ensure_ascii=False)
            with open(self._decisions_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
            self._logger.debug(f"Decision logged for {symbol} → {self._decisions_path}")
        except Exception as exc:
            self._logger.error(f"Failed to write AI decision for {symbol}: {exc}", exc_info=True)

    def log_skip(self, symbol: str, reason: str):
        self._logger.info(f"SKIP  | {symbol} — {reason}")

    def log_error(self, msg: str, exc: Exception = None):
        if exc:
            self._logger.error(f"{msg}: {exc}", exc_info=True)
        else:
            self._logger.error(msg)
