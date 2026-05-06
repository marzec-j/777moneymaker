"""
Risk management module.
Calculates position sizes, validates signals, and tracks daily losses.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional, Tuple

logger = logging.getLogger("777moneymaker")


class RiskManager:
    def __init__(self, config: dict):
        self._config = config
        r = config.get("risk", {})
        self._max_pos_pct = r.get("max_position_pct", 0.10)
        self._max_daily_loss_pct = r.get("max_daily_loss_pct", 0.03)
        self._stop_loss_pct = r.get("stop_loss_pct", 0.02)
        self._take_profit_pct = r.get("take_profit_pct", 0.04)
        self._min_conf = r.get("min_confidence", 0.65)

    @property
    def _max_open(self) -> int:
        return self._config.get("risk", {}).get("max_open_positions", 5)

        self._daily_start_equity: Optional[float] = None
        self._daily_pnl: float = 0.0
        self._today: date = date.today()
        self._trading_halted: bool = False

    def update_equity(self, equity: float):
        today = date.today()
        if today != self._today:
            self._today = today
            self._daily_start_equity = equity
            self._daily_pnl = 0.0
            self._trading_halted = False
            logger.info(f"New day — daily P&L reset. Starting equity: ${equity:,.2f}")
        elif self._daily_start_equity is None:
            self._daily_start_equity = equity

        if self._daily_start_equity and self._daily_start_equity > 0:
            self._daily_pnl = (equity - self._daily_start_equity) / self._daily_start_equity

        if self._daily_pnl <= -self._max_daily_loss_pct and not self._trading_halted:
            self._trading_halted = True
            logger.warning(
                f"DAILY STOP ACTIVATED: loss {self._daily_pnl:.2%} "
                f"exceeds limit {self._max_daily_loss_pct:.2%}. "
                f"Trading halted for the rest of the day."
            )

    @property
    def is_halted(self) -> bool:
        return self._trading_halted

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    def validate_signal(
        self,
        symbol: str,
        decision: dict,
        open_positions_count: int,
        equity: float,
    ) -> Tuple[bool, str]:
        action = decision["action"]
        conf = decision.get("confidence", 0.0)

        if self._trading_halted:
            return False, f"trading halted — daily stop {self._daily_pnl:.2%}"

        if action == "HOLD":
            return False, "HOLD signal — no action"

        if conf < self._min_conf:
            return False, f"confidence too low {conf:.0%} < {self._min_conf:.0%}"

        if open_positions_count >= self._max_open:
            return False, f"max open positions ({self._max_open}) reached"

        if equity <= 0:
            return False, "zero equity — account error"

        return True, ""

    def calc_position(
        self,
        action: str,
        current_price: float,
        equity: float,
        decision: dict,
        atr: Optional[float] = None,
        buying_power: Optional[float] = None,
    ) -> dict:
        max_value = equity * self._max_pos_pct
        if buying_power is not None and buying_power > 0:
            # Never spend more than 98% of available cash (2% safety buffer)
            max_value = min(max_value, buying_power * 0.98)
        qty = max(1, int(max_value / current_price))

        if action == "BUY":
            sl = self._safe_level(
                decision.get("stop_loss"),
                current_price * (1 - self._stop_loss_pct),
                lambda x: 0 < x < current_price,
            )
            tp = self._safe_level(
                decision.get("take_profit"),
                current_price * (1 + self._take_profit_pct),
                lambda x: x > current_price,
            )
        else:  # SELL / short
            sl = self._safe_level(
                decision.get("stop_loss"),
                current_price * (1 + self._stop_loss_pct),
                lambda x: x > current_price,
            )
            tp = self._safe_level(
                decision.get("take_profit"),
                current_price * (1 - self._take_profit_pct),
                lambda x: 0 < x < current_price,
            )

        result = {
            "qty": qty,
            "stop_loss": round(sl, 4),
            "take_profit": round(tp, 4),
            "max_position_value": round(qty * current_price, 2),
        }
        logger.debug(
            f"Position: {action} {qty}x @ ${current_price:.2f} "
            f"| SL=${sl:.2f} TP=${tp:.2f} | value=${result['max_position_value']:,.2f}"
        )
        return result

    @staticmethod
    def _safe_level(llm_value, default: float, validator) -> float:
        if llm_value is not None:
            try:
                v = float(llm_value)
                if validator(v):
                    return v
            except (TypeError, ValueError):
                pass
        return default
