"""
Built-in trading simulator for testing without a real broker.
Supports both long and short positions.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .base_broker import BaseBroker

logger = logging.getLogger("777moneymaker")

_STATE_FILE = Path("data/paper_state.json")


class PaperBroker(BaseBroker):
    """
    Local simulator — no API or account required.
    Default starting balance: $100,000.
    Supports long and short positions.
    """

    def __init__(self, starting_cash: float = 100_000.0):
        self._starting_cash = starting_cash
        self._cash = starting_cash
        self._positions: dict[str, dict] = {}
        self._orders: list[dict] = []
        self._order_counter = 0
        self._load_state()

    def connect(self) -> bool:
        logger.info(
            f"Paper Broker active | Cash: ${self._cash:,.2f} | "
            f"Positions: {len(self._positions)}"
        )
        return True

    def get_account(self) -> dict:
        portfolio_value = 0.0
        for p in self._positions.values():
            if p["side"] == "long":
                portfolio_value += p["qty"] * p["current_price"]
            else:  # short: we owe shares, value is negative exposure
                portfolio_value -= p["qty"] * p["current_price"]
        equity = self._cash + portfolio_value
        return {
            "equity": round(equity, 2),
            "cash": round(self._cash, 2),
            "buying_power": round(self._cash, 2),
            "portfolio_value": round(portfolio_value, 2),
        }

    def get_positions(self) -> list[dict]:
        return list(self._positions.values())

    def get_position(self, symbol: str) -> Optional[dict]:
        return self._positions.get(symbol)

    def place_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Optional[dict]:
        self._order_counter += 1
        order_id = f"PAPER-{self._order_counter:04d}"

        price = self._get_price(symbol, limit_price)
        if price is None:
            logger.error(f"PaperBroker: failed to fetch price for {symbol}")
            return None

        existing = self._positions.get(symbol)

        if side.lower() == "buy":
            if existing and existing["side"] == "short":
                # Close short position
                self._close_short(symbol, existing, price, qty)
            else:
                # Open or add to long position
                cost = price * qty
                if cost > self._cash:
                    logger.warning(
                        f"PaperBroker: insufficient funds! "
                        f"Need ${cost:,.2f}, available ${self._cash:,.2f}"
                    )
                    return None
                self._cash -= cost
                if existing and existing["side"] == "long":
                    total_qty = existing["qty"] + qty
                    existing["avg_entry_price"] = (
                        existing["avg_entry_price"] * existing["qty"] + price * qty
                    ) / total_qty
                    existing["qty"] = total_qty
                else:
                    self._positions[symbol] = {
                        "symbol": symbol,
                        "qty": qty,
                        "side": "long",
                        "avg_entry_price": price,
                        "current_price": price,
                        "market_value": price * qty,
                        "unrealized_pl": 0.0,
                        "unrealized_plpc": 0.0,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "opened_at": datetime.utcnow().isoformat(),
                    }

        elif side.lower() == "sell":
            if existing and existing["side"] == "long":
                # Close long position
                sell_qty = min(qty, int(existing["qty"]))
                proceeds = price * sell_qty
                pl = (price - existing["avg_entry_price"]) * sell_qty
                self._cash += proceeds
                self._positions.pop(symbol)
                logger.info(
                    f"PaperBroker SELL (close long) {sell_qty}x {symbol} @ ${price:.2f} "
                    f"| P&L: ${pl:+.2f}"
                )
            elif existing and existing["side"] == "short":
                # Add to short position
                proceeds = price * qty
                self._cash += proceeds
                total_qty = existing["qty"] + qty
                existing["avg_entry_price"] = (
                    existing["avg_entry_price"] * existing["qty"] + price * qty
                ) / total_qty
                existing["qty"] = total_qty
                logger.info(
                    f"PaperBroker SELL (add short) {qty}x {symbol} @ ${price:.2f}"
                )
            else:
                # Open new short position
                proceeds = price * qty
                self._cash += proceeds
                self._positions[symbol] = {
                    "symbol": symbol,
                    "qty": qty,
                    "side": "short",
                    "avg_entry_price": price,
                    "current_price": price,
                    "market_value": -price * qty,
                    "unrealized_pl": 0.0,
                    "unrealized_plpc": 0.0,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "opened_at": datetime.utcnow().isoformat(),
                }
                logger.info(
                    f"PaperBroker SELL (open short) {qty}x {symbol} @ ${price:.2f} "
                    f"| Cash received: ${proceeds:,.2f}"
                )

        record = {
            "order_id": order_id,
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "price": price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        }
        self._orders.append(record)
        self._save_state()
        logger.info(
            f"PaperBroker | {side.upper()} {qty}x {symbol} @ ${price:.2f} "
            f"| ID={order_id} | Cash: ${self._cash:,.2f}"
        )
        return record

    def _close_short(self, symbol: str, pos: dict, price: float, qty: int):
        cover_qty = min(qty, int(pos["qty"]))
        cost = price * cover_qty
        pl = (pos["avg_entry_price"] - price) * cover_qty
        self._cash -= cost
        self._positions.pop(symbol)
        logger.info(
            f"PaperBroker BUY (cover short) {cover_qty}x {symbol} @ ${price:.2f} "
            f"| P&L: ${pl:+.2f}"
        )

    def close_position(self, symbol: str) -> bool:
        pos = self._positions.get(symbol)
        if not pos:
            return False
        side = "buy" if pos["side"] == "short" else "sell"
        result = self.place_order(symbol, int(pos["qty"]), side)
        return result is not None

    def cancel_order(self, order_id: str) -> bool:
        logger.info(f"PaperBroker: cancel {order_id} (simulated)")
        return True

    def is_market_open(self) -> bool:
        return True  # simulator is always "open"

    def update_prices(self, prices: dict[str, float]):
        for symbol, price in prices.items():
            if symbol in self._positions:
                pos = self._positions[symbol]
                pos["current_price"] = price
                if pos["side"] == "long":
                    pos["market_value"] = pos["qty"] * price
                    pos["unrealized_pl"] = (price - pos["avg_entry_price"]) * pos["qty"]
                else:  # short
                    pos["market_value"] = -pos["qty"] * price
                    pos["unrealized_pl"] = (pos["avg_entry_price"] - price) * pos["qty"]
                if pos["avg_entry_price"] > 0:
                    if pos["side"] == "long":
                        pos["unrealized_plpc"] = (price - pos["avg_entry_price"]) / pos["avg_entry_price"]
                    else:
                        pos["unrealized_plpc"] = (pos["avg_entry_price"] - price) / pos["avg_entry_price"]

    def _save_state(self):
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"cash": self._cash, "positions": self._positions, "counter": self._order_counter},
                f, indent=2, ensure_ascii=False,
            )

    def _load_state(self):
        if _STATE_FILE.exists():
            try:
                with open(_STATE_FILE, encoding="utf-8") as f:
                    state = json.load(f)
                self._cash = state.get("cash", self._starting_cash)
                self._positions = state.get("positions", {})
                self._order_counter = state.get("counter", 0)
                logger.info(f"PaperBroker: state loaded from {_STATE_FILE}")
            except Exception:
                pass

    @staticmethod
    def _get_price(symbol: str, fallback: Optional[float]) -> Optional[float]:
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1d", interval="1m")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception:
            pass
        return fallback


    def get_bars(self, symbol, timeframe, start, end):
        return None  # PaperBroker not used for market data

    def get_latest_price(self, symbol):
        return self._get_price(symbol, None)
