"""
Backtesting engine — simulates trading on historical daily data.
Uses the real LLM for decisions, so results reflect actual strategy behavior.

Note: Each day requires one LLM call per symbol.
Estimate: ~15s/call × symbols × trading days = plan your time accordingly.
  3 months × 5 symbols ≈ 325 calls ≈ ~80 minutes
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger("777moneymaker")


# ------------------------------------------------------------------ #
#  In-memory account state                                            #
# ------------------------------------------------------------------ #

@dataclass
class BacktestPosition:
    symbol: str
    side: str          # "long" | "short"
    qty: int
    entry_price: float
    entry_date: date
    stop_loss: Optional[float]
    take_profit: Optional[float]
    confidence: float


@dataclass
class BacktestTrade:
    date: date
    symbol: str
    action: str        # BUY | SELL | SHORT | COVER | SL_EXIT | TP_EXIT
    qty: int
    price: float
    pnl: Optional[float] = None
    confidence: float = 0.0
    reasoning: str = ""


class BacktestState:
    def __init__(self, starting_cash: float):
        self.cash = starting_cash
        self.starting_cash = starting_cash
        self.positions: dict[str, BacktestPosition] = {}
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[tuple[date, float]] = []

    def get_equity(self, current_prices: dict[str, float]) -> float:
        portfolio = 0.0
        for sym, pos in self.positions.items():
            price = current_prices.get(sym, pos.entry_price)
            if pos.side == "long":
                portfolio += pos.qty * price
            else:
                portfolio -= pos.qty * price
        return self.cash + portfolio

    def open_long(self, symbol, qty, price, sl, tp, day, confidence, reasoning):
        self.cash -= qty * price
        self.positions[symbol] = BacktestPosition(
            symbol=symbol, side="long", qty=qty, entry_price=price,
            entry_date=day, stop_loss=sl, take_profit=tp, confidence=confidence,
        )
        self.trades.append(BacktestTrade(
            date=day, symbol=symbol, action="BUY", qty=qty, price=price,
            confidence=confidence, reasoning=reasoning[:200],
        ))

    def close_long(self, symbol, price, day, action):
        pos = self.positions.pop(symbol)
        pnl = (price - pos.entry_price) * pos.qty
        self.cash += pos.qty * price
        self.trades.append(BacktestTrade(
            date=day, symbol=symbol, action=action, qty=pos.qty, price=price, pnl=pnl,
        ))
        return pnl

    def open_short(self, symbol, qty, price, sl, tp, day, confidence, reasoning):
        self.cash += qty * price
        self.positions[symbol] = BacktestPosition(
            symbol=symbol, side="short", qty=qty, entry_price=price,
            entry_date=day, stop_loss=sl, take_profit=tp, confidence=confidence,
        )
        self.trades.append(BacktestTrade(
            date=day, symbol=symbol, action="SHORT", qty=qty, price=price,
            confidence=confidence, reasoning=reasoning[:200],
        ))

    def close_short(self, symbol, price, day, action):
        pos = self.positions.pop(symbol)
        pnl = (pos.entry_price - price) * pos.qty
        self.cash -= pos.qty * price
        self.trades.append(BacktestTrade(
            date=day, symbol=symbol, action=action, qty=pos.qty, price=price, pnl=pnl,
        ))
        return pnl


# ------------------------------------------------------------------ #
#  Backtesting engine                                                  #
# ------------------------------------------------------------------ #

class BacktestEngine:

    def __init__(
        self,
        config: dict,
        data_fetcher,
        llm,
        risk,
        start_date: date,
        end_date: date,
        starting_cash: float = 100_000.0,
    ):
        self._config = config
        self._data = data_fetcher
        self._llm = llm
        self._risk = risk
        self._symbols = config.get("symbols", [])
        self._start = start_date
        self._end = end_date
        self._state = BacktestState(starting_cash)
        self._log_dir = Path(config.get("logging", {}).get("log_dir", "logs"))
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> dict:
        trading_days = self._get_trading_days()
        total = len(trading_days)
        logger.info(f"Backtest {self._start} → {self._end} | {total} trading days | {len(self._symbols)} symbols")
        logger.info(f"Estimated LLM calls: ~{total * len(self._symbols)} — this may take a while")
        logger.info("=" * 60)

        for i, day in enumerate(trading_days, 1):
            logger.info(f"[{i}/{total}] {day}")

            # Fetch OHLCV for all symbols on this day (for SL/TP and pricing)
            day_ohlcv = self._fetch_day_ohlcv(day)

            # Check SL/TP exits before making new decisions
            self._check_sl_tp(day, day_ohlcv)

            # LLM analysis and trade execution
            for symbol in self._symbols:
                self._process_symbol(symbol, day, day_ohlcv)

            # Record end-of-day equity
            prices = {sym: v["close"] for sym, v in day_ohlcv.items() if v}
            equity = self._state.get_equity(prices)
            self._state.equity_curve.append((day, equity))

        return self._generate_report()

    # ------------------------------------------------------------------ #
    #  SL/TP check                                                         #
    # ------------------------------------------------------------------ #

    def _check_sl_tp(self, day: date, day_ohlcv: dict):
        for symbol, pos in list(self._state.positions.items()):
            ohlcv = day_ohlcv.get(symbol)
            if not ohlcv:
                continue
            high = ohlcv["high"]
            low = ohlcv["low"]
            sl = pos.stop_loss
            tp = pos.take_profit

            if pos.side == "long":
                if sl and low <= sl:
                    pnl = self._state.close_long(symbol, sl, day, "SL_EXIT")
                    logger.info(f"  SL_EXIT {symbol} @ ${sl:.2f} | P&L: ${pnl:+.2f}")
                elif tp and high >= tp:
                    pnl = self._state.close_long(symbol, tp, day, "TP_EXIT")
                    logger.info(f"  TP_EXIT {symbol} @ ${tp:.2f} | P&L: ${pnl:+.2f}")
            else:  # short
                if sl and high >= sl:
                    pnl = self._state.close_short(symbol, sl, day, "SL_EXIT")
                    logger.info(f"  SL_EXIT SHORT {symbol} @ ${sl:.2f} | P&L: ${pnl:+.2f}")
                elif tp and low <= tp:
                    pnl = self._state.close_short(symbol, tp, day, "TP_EXIT")
                    logger.info(f"  TP_EXIT SHORT {symbol} @ ${tp:.2f} | P&L: ${pnl:+.2f}")

    # ------------------------------------------------------------------ #
    #  Symbol processing                                                   #
    # ------------------------------------------------------------------ #

    def _process_symbol(self, symbol: str, day: date, day_ohlcv: dict):
        snapshot = self._data.get_historical_snapshot(symbol, day)
        if snapshot is None:
            return

        price = snapshot["price"]["current"]
        existing = self._state.positions.get(symbol)

        decision = self._llm.analyze(snapshot)
        if decision is None:
            return

        action = decision["action"]
        conf = decision["confidence"]
        reasoning = decision.get("reasoning", "")

        logger.info(f"  {symbol} @ ${price:.2f} | LLM → {action} conf={conf:.0%}")

        equity = self._state.get_equity({symbol: price})
        open_count = len(self._state.positions)

        if action == "BUY":
            if existing and existing.side == "short":
                pnl = self._state.close_short(symbol, price, day, "COVER")
                logger.info(f"    COVER {symbol} @ ${price:.2f} | P&L: ${pnl:+.2f}")
            elif not existing:
                ok, reason = self._risk.validate_signal(symbol, decision, open_count, equity)
                if ok:
                    pos = self._risk.calc_position("BUY", price, equity, decision)
                    if pos["qty"] * price <= self._state.cash:
                        self._state.open_long(
                            symbol, pos["qty"], price,
                            pos["stop_loss"], pos["take_profit"],
                            day, conf, reasoning,
                        )
                        logger.info(
                            f"    BUY {pos['qty']}x {symbol} @ ${price:.2f} "
                            f"SL=${pos['stop_loss']:.2f} TP=${pos['take_profit']:.2f}"
                        )

        elif action == "SELL":
            if existing and existing.side == "long":
                pnl = self._state.close_long(symbol, price, day, "SELL")
                logger.info(f"    SELL {symbol} @ ${price:.2f} | P&L: ${pnl:+.2f}")
            elif not existing:
                ok, reason = self._risk.validate_signal(symbol, decision, open_count, equity)
                if ok:
                    pos = self._risk.calc_position("SELL", price, equity, decision)
                    self._state.open_short(
                        symbol, pos["qty"], price,
                        pos["stop_loss"], pos["take_profit"],
                        day, conf, reasoning,
                    )
                    logger.info(
                        f"    SHORT {pos['qty']}x {symbol} @ ${price:.2f} "
                        f"SL=${pos['stop_loss']:.2f} TP=${pos['take_profit']:.2f}"
                    )

    # ------------------------------------------------------------------ #
    #  Report                                                              #
    # ------------------------------------------------------------------ #

    def _generate_report(self) -> dict:
        closed = [t for t in self._state.trades if t.pnl is not None]
        winners = [t for t in closed if t.pnl > 0]
        losers = [t for t in closed if t.pnl <= 0]

        gross_profit = sum(t.pnl for t in winners)
        gross_loss = abs(sum(t.pnl for t in losers))
        total_pnl = sum(t.pnl for t in closed)
        win_rate = len(winners) / len(closed) if closed else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        final_equity = self._state.equity_curve[-1][1] if self._state.equity_curve else self._state.starting_cash
        total_return = (final_equity - self._state.starting_cash) / self._state.starting_cash

        # Max drawdown from equity curve
        max_drawdown = 0.0
        peak = self._state.starting_cash
        for _, eq in self._state.equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            max_drawdown = max(max_drawdown, dd)

        # Sharpe ratio (annualized, assumes 252 trading days/year)
        sharpe = 0.0
        if len(self._state.equity_curve) > 1:
            returns = []
            for i in range(1, len(self._state.equity_curve)):
                prev_eq = self._state.equity_curve[i - 1][1]
                curr_eq = self._state.equity_curve[i][1]
                returns.append((curr_eq - prev_eq) / prev_eq if prev_eq > 0 else 0)
            import statistics
            if len(returns) > 1:
                avg_r = statistics.mean(returns)
                std_r = statistics.stdev(returns)
                sharpe = (avg_r / std_r * (252 ** 0.5)) if std_r > 0 else 0.0

        report = {
            "start": str(self._start),
            "end": str(self._end),
            "starting_cash": self._state.starting_cash,
            "final_equity": round(final_equity, 2),
            "total_return_pct": round(total_return * 100, 2),
            "total_pnl": round(total_pnl, 2),
            "total_trades": len(closed),
            "win_rate_pct": round(win_rate * 100, 1),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_pct": round(max_drawdown * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
        }

        self._print_report(report)
        self._save_trades_csv()
        self._save_equity_csv()

        return report

    def _print_report(self, r: dict):
        logger.info("=" * 60)
        logger.info("  BACKTEST RESULTS")
        logger.info("=" * 60)
        logger.info(f"  Period:          {r['start']} → {r['end']}")
        logger.info(f"  Starting equity: ${r['starting_cash']:>12,.2f}")
        logger.info(f"  Final equity:    ${r['final_equity']:>12,.2f}")
        logger.info(f"  Total return:    {r['total_return_pct']:>+11.2f}%")
        logger.info(f"  Total P&L:       ${r['total_pnl']:>+11.2f}")
        logger.info("-" * 60)
        logger.info(f"  Closed trades:   {r['total_trades']:>12}")
        logger.info(f"  Win rate:        {r['win_rate_pct']:>11.1f}%")
        logger.info(f"  Profit factor:   {r['profit_factor']:>12.2f}")
        logger.info(f"  Max drawdown:    {r['max_drawdown_pct']:>11.2f}%")
        logger.info(f"  Sharpe ratio:    {r['sharpe_ratio']:>12.2f}")
        logger.info(f"  Gross profit:    ${r['gross_profit']:>12,.2f}")
        logger.info(f"  Gross loss:      ${r['gross_loss']:>12,.2f}")
        logger.info("=" * 60)
        results_path = self._log_dir / f"backtest_{r['start']}_{r['end']}.txt"
        logger.info(f"  Trades saved to: logs/backtest_trades_{r['start']}_{r['end']}.csv")
        logger.info(f"  Equity saved to: logs/backtest_equity_{r['start']}_{r['end']}.csv")
        logger.info("=" * 60)

    def _save_trades_csv(self):
        fname = self._log_dir / f"backtest_trades_{self._start}_{self._end}.csv"
        with open(fname, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "symbol", "action", "qty", "price", "pnl", "confidence", "reasoning"])
            for t in self._state.trades:
                writer.writerow([
                    t.date, t.symbol, t.action, t.qty,
                    round(t.price, 4),
                    round(t.pnl, 2) if t.pnl is not None else "",
                    round(t.confidence, 2),
                    t.reasoning,
                ])

    def _save_equity_csv(self):
        fname = self._log_dir / f"backtest_equity_{self._start}_{self._end}.csv"
        with open(fname, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "equity"])
            for day, eq in self._state.equity_curve:
                writer.writerow([day, round(eq, 2)])

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _get_trading_days(self) -> list[date]:
        """Returns actual NYSE trading days in the backtest range via broker (SPY bars)."""
        return self._data.get_trading_days(self._start, self._end)

    def _fetch_day_ohlcv(self, day: date) -> dict[str, Optional[dict]]:
        """Fetches OHLCV for all symbols on a specific date via broker."""
        return {
            symbol: self._data.get_bar_for_date(symbol, day)
            for symbol in self._symbols
        }
