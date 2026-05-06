"""
Integracja z Alpaca Markets przez alpaca-py SDK.
Obsługuje zarówno paper trading jak i live trading.
"""

from __future__ import annotations

import logging
import os
import time as _time
from typing import Optional

from .base_broker import BaseBroker

logger = logging.getLogger("777moneymaker")


class AlpacaBroker(BaseBroker):

    def __init__(self, mode: str = "paper"):
        self._mode = mode  # "paper" or "live"
        self._api_key = os.getenv("ALPACA_API_KEY", "")
        self._secret_key = os.getenv("ALPACA_SECRET_KEY", "")
        self._trading = None
        self._data = None
        self._assets_cache: list[str] = []
        self._assets_cache_time: float = 0

    def connect(self) -> bool:
        if not self._api_key or not self._secret_key:
            logger.error(
                "Brak kluczy Alpaca! Ustaw ALPACA_API_KEY i ALPACA_SECRET_KEY w pliku .env"
            )
            return False
        try:
            from alpaca.trading.client import TradingClient
            from alpaca.data.historical import StockHistoricalDataClient

            paper = (self._mode == "paper")
            self._trading = TradingClient(
                api_key=self._api_key,
                secret_key=self._secret_key,
                paper=paper,
            )
            self._data = StockHistoricalDataClient(
                api_key=self._api_key,
                secret_key=self._secret_key,
            )
            account = self._trading.get_account()
            logger.info(
                f"Alpaca połączona ({'PAPER' if paper else 'LIVE'}) | "
                f"Equity: ${float(account.equity):,.2f} | "
                f"Cash: ${float(account.cash):,.2f}"
            )
            return True
        except ImportError:
            logger.error("Zainstaluj alpaca-py: pip install alpaca-py")
            return False
        except Exception as exc:
            logger.error(f"Błąd połączenia z Alpaca: {exc}", exc_info=True)
            return False

    def get_account(self) -> dict:
        try:
            acc = self._trading.get_account()
            dtbp_raw = getattr(acc, "daytrading_buying_power", None)
            return {
                "equity": float(acc.equity),
                "cash": float(acc.cash),
                "buying_power": float(acc.buying_power),
                "portfolio_value": float(acc.portfolio_value),
                "daytrade_count": getattr(acc, "daytrade_count", 0),
                "daytrading_buying_power": float(dtbp_raw) if dtbp_raw is not None else None,
            }
        except Exception as exc:
            logger.error(f"Błąd pobierania konta: {exc}")
            return {"equity": 0, "cash": 0, "buying_power": 0, "portfolio_value": 0}

    def get_positions(self) -> list[dict]:
        try:
            positions = self._trading.get_all_positions()
            return [self._format_position(p) for p in positions]
        except Exception as exc:
            logger.error(f"Błąd pobierania pozycji: {exc}")
            return []

    def get_position(self, symbol: str) -> Optional[dict]:
        try:
            pos = self._trading.get_open_position(symbol)
            return self._format_position(pos)
        except Exception:
            return None

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
        try:
            from alpaca.trading.requests import (
                MarketOrderRequest,
                LimitOrderRequest,
                TakeProfitRequest,
                StopLossRequest,
            )
            from alpaca.trading.enums import OrderSide, TimeInForce

            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

            # Bracket order (z SL i TP) tylko dla BUY
            if side.lower() == "buy" and stop_loss and take_profit:
                import math
                # Floor stop_loss to 2 decimals — rounding up could violate
                # Alpaca's rule: stop_price <= base_price - 0.01
                sl_price = math.floor(stop_loss * 100) / 100
                tp_price = round(take_profit, 2)
                req = MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=order_side,
                    time_in_force=TimeInForce.DAY,
                    order_class="bracket",
                    stop_loss=StopLossRequest(stop_price=sl_price),
                    take_profit=TakeProfitRequest(limit_price=tp_price),
                )
            elif order_type == "limit" and limit_price:
                req = LimitOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=order_side,
                    time_in_force=TimeInForce.DAY,
                    limit_price=round(limit_price, 2),
                )
            else:
                req = MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=order_side,
                    time_in_force=TimeInForce.DAY,
                )

            order = self._trading.submit_order(req)
            logger.info(f"Zlecenie wysłane: {side.upper()} {qty}x {symbol} | ID={order.id}")
            return {
                "order_id": str(order.id),
                "symbol": symbol,
                "qty": qty,
                "side": side,
                "status": str(order.status),
            }
        except Exception as exc:
            # Bracket orders are only valid for new entry positions.
            # If Alpaca rejects it (e.g. position already exists from a prior cycle),
            # fall back to a plain market order so the trade still goes through.
            if "bracket orders must be entry orders" in str(exc):
                logger.warning(
                    f"{symbol}: bracket order rejected — retrying as plain market order"
                )
                try:
                    from alpaca.trading.requests import MarketOrderRequest
                    from alpaca.trading.enums import OrderSide, TimeInForce
                    order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
                    plain_req = MarketOrderRequest(
                        symbol=symbol,
                        qty=qty,
                        side=order_side,
                        time_in_force=TimeInForce.DAY,
                    )
                    order = self._trading.submit_order(plain_req)
                    logger.info(
                        f"Zlecenie wysłane (plain): {side.upper()} {qty}x {symbol} | ID={order.id}"
                    )
                    return {
                        "order_id": str(order.id),
                        "symbol": symbol,
                        "qty": qty,
                        "side": side,
                        "status": str(order.status),
                    }
                except Exception as retry_exc:
                    logger.error(
                        f"Błąd składania zlecenia plain {side} {symbol}: {retry_exc}",
                        exc_info=True,
                    )
                    return None
            logger.error(f"Błąd składania zlecenia {side} {symbol}: {exc}", exc_info=True)
            return None

    def close_position(self, symbol: str) -> bool:
        try:
            self._trading.close_position(symbol)
            logger.info(f"Pozycja zamknięta: {symbol}")
            return True
        except Exception as exc:
            logger.error(f"Błąd zamknięcia pozycji {symbol}: {exc}")
            return False

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._trading.cancel_order_by_id(order_id)
            return True
        except Exception as exc:
            logger.error(f"Błąd anulowania zlecenia {order_id}: {exc}")
            return False

    def is_market_open(self) -> bool:
        try:
            clock = self._trading.get_clock()
            return bool(clock.is_open)
        except Exception:
            return True  # zakładamy otwarty gdy błąd

    # ── Market data ───────────────────────────────────────────────────────

    def get_bars(self, symbol: str, timeframe: str, start, end):
        if self._data is None:
            return None
        try:
            import pandas as pd
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame

            tf_map = {"1d": TimeFrame.Day, "1wk": TimeFrame.Week}
            tf = tf_map.get(timeframe, TimeFrame.Day)

            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=start,
                end=end,
                feed="iex",
            )
            bars = self._data.get_stock_bars(request)
            df = bars.df
            if df is None or df.empty:
                return None

            if isinstance(df.index, pd.MultiIndex):
                if symbol not in df.index.get_level_values(0):
                    return None
                df = df.xs(symbol, level=0)

            df = df.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })
            return df[["Open", "High", "Low", "Close", "Volume"]].copy()
        except Exception as exc:
            logger.debug(f"get_bars {symbol} {timeframe}: {exc}")
            return None

    def get_latest_price(self, symbol: str):
        if self._data is None:
            return None
        try:
            from alpaca.data.requests import StockLatestBarRequest
            request = StockLatestBarRequest(symbol_or_symbols=symbol)
            bars = self._data.get_stock_latest_bar(request)
            bar = bars.get(symbol)
            if bar:
                return float(bar.close)
        except Exception as exc:
            logger.debug(f"get_latest_price {symbol}: {exc}")
        return None

    def get_snapshots_batch(self, symbols: list[str], chunk_size: int = 1000) -> dict:
        """
        Batch snapshot dla wielu symboli naraz — 1 API call na 1000 symboli.
        Zwraca {symbol: {"change_pct": float, "volume": int}}.
        """
        if self._data is None:
            return {}
        result: dict = {}
        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i: i + chunk_size]
            try:
                from alpaca.data.requests import StockSnapshotRequest
                request = StockSnapshotRequest(symbol_or_symbols=chunk, feed="iex")
                snapshots = self._data.get_stock_snapshot(request)
                for sym, snap in snapshots.items():
                    try:
                        daily = snap.daily_bar
                        prev  = snap.prev_daily_bar
                        if daily and prev and prev.close and float(prev.close) > 0:
                            change_pct = (
                                (float(daily.close) - float(prev.close))
                                / float(prev.close) * 100
                            )
                            result[sym] = {
                                "change_pct": round(change_pct, 2),
                                "volume":     int(daily.volume),
                            }
                    except Exception:
                        pass
            except Exception as exc:
                logger.debug(f"get_snapshots_batch chunk {i}: {exc}")
        return result

    def get_all_assets(self) -> list[str]:
        """Fetches all active tradable US equity/ETF symbols from Alpaca. Cached 1 hour."""
        now = _time.time()
        if self._assets_cache and (now - self._assets_cache_time) < 3600:
            return self._assets_cache
        if self._trading is None:
            return []
        try:
            from alpaca.trading.requests import GetAssetsRequest
            from alpaca.trading.enums import AssetClass, AssetStatus
            req = GetAssetsRequest(
                asset_class=AssetClass.US_EQUITY,
                status=AssetStatus.ACTIVE,
            )
            assets = self._trading.get_all_assets(req)
            symbols = sorted([a.symbol for a in assets if a.tradable])
            self._assets_cache = symbols
            self._assets_cache_time = now
            logger.info(f"Loaded {len(symbols)} tradable US equity symbols from Alpaca")
            return symbols
        except Exception as exc:
            logger.debug(f"get_all_assets: {exc}")
            return []

    @staticmethod
    def _format_position(pos) -> dict:
        return {
            "symbol": str(pos.symbol),
            "qty": float(pos.qty),
            "side": str(pos.side),
            "avg_entry_price": float(pos.avg_entry_price),
            "market_value": float(pos.market_value),
            "unrealized_pl": float(pos.unrealized_pl),
            "unrealized_plpc": float(pos.unrealized_plpc),
            "current_price": float(pos.current_price),
        }
