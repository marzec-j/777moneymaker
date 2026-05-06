"""
Market data module: fetches OHLCV and computes technical indicators.
Supports multi-timeframe analysis (daily + weekly).
Data source: broker API (Alpaca by default).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from .brokers.base_broker import BaseBroker

logger = logging.getLogger("777moneymaker")


class MarketDataFetcher:
    """Fetches OHLCV via broker API and computes indicators."""

    def __init__(self, config: dict, broker: Optional[BaseBroker] = None):
        ind = config.get("indicators", {})
        self._rsi_period = ind.get("rsi_period", 14)
        self._macd_fast = ind.get("macd_fast", 12)
        self._macd_slow = ind.get("macd_slow", 26)
        self._macd_signal = ind.get("macd_signal", 9)
        self._bb_period = ind.get("bb_period", 20)
        self._bb_std = ind.get("bb_std", 2)
        self._sma_periods = ind.get("sma_periods", [20, 50, 200])
        self._lookback = ind.get("lookback_bars", 100)
        self._broker = broker  # None → all data methods return None gracefully

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def get_snapshot_fast(self, symbol: str) -> Optional[dict]:
        """Fast snapshot for full market scan — daily bars only, no weekly call."""
        try:
            df = self._fetch_ohlcv(symbol, interval="1d")
            if df is None or len(df) < self._macd_slow + self._macd_signal + 5:
                return None
            df = self._add_indicators(df)
            last = df.iloc[-1]
            prev = df.iloc[-2]
            return {
                "symbol": symbol,
                "timestamp": datetime.utcnow().isoformat(),
                "price": {
                    "current":    round(float(last["Close"]), 4),
                    "open":       round(float(last["Open"]), 4),
                    "high":       round(float(last["High"]), 4),
                    "low":        round(float(last["Low"]), 4),
                    "volume":     int(last["Volume"]),
                    "prev_close": round(float(prev["Close"]), 4),
                    "change_pct": round(
                        (float(last["Close"]) - float(prev["Close"]))
                        / float(prev["Close"]) * 100, 2,
                    ),
                },
                "indicators": self._extract_indicators(df),
            }
        except Exception as exc:
            logger.debug(f"{symbol}: fast snapshot error — {exc}")
            return None

    def get_snapshot(self, symbol: str) -> Optional[dict]:
        """
        Returns a dict with all data needed for LLM analysis.
        Includes daily indicators and weekly timeframe context.
        Returns None if fetching fails.
        """
        try:
            df = self._fetch_ohlcv(symbol, interval="1d")
            if df is None or len(df) < self._macd_slow + self._macd_signal + 5:
                logger.warning(f"{symbol}: insufficient historical data")
                return None

            df = self._add_indicators(df)
            last = df.iloc[-1]
            prev = df.iloc[-2]

            snap = {
                "symbol": symbol,
                "timestamp": datetime.utcnow().isoformat(),
                "price": {
                    "current": round(float(last["Close"]), 4),
                    "open": round(float(last["Open"]), 4),
                    "high": round(float(last["High"]), 4),
                    "low": round(float(last["Low"]), 4),
                    "volume": int(last["Volume"]),
                    "prev_close": round(float(prev["Close"]), 4),
                    "change_pct": round(
                        (float(last["Close"]) - float(prev["Close"]))
                        / float(prev["Close"])
                        * 100,
                        2,
                    ),
                },
                "indicators": self._extract_indicators(df),
                "recent_candles": self._recent_candles(df, n=10),
                "weekly": self._fetch_weekly_indicators(symbol),
            }
            return snap
        except Exception as exc:
            logger.error(f"{symbol}: data fetch error — {exc}", exc_info=True)
            return None

    def get_historical_snapshot(self, symbol: str, as_of: date) -> Optional[dict]:
        """
        Returns a snapshot for a specific historical date — no lookahead bias.
        Fetches data only up to and including `as_of`. Used by the backtesting engine.
        """
        try:
            end   = datetime.combine(as_of, datetime.min.time()) + timedelta(days=1)
            start = datetime.combine(as_of, datetime.min.time()) - timedelta(days=max(self._lookback * 2, 400))

            df = self._broker.get_bars(symbol, "1d", start, end)
            if df is None or df.empty:
                return None
            df = df.dropna()
            df = df.tail(self._lookback + 50)

            if len(df) < self._macd_slow + self._macd_signal + 5:
                return None

            df = self._add_indicators(df)
            last = df.iloc[-1]
            prev = df.iloc[-2]

            snap = {
                "symbol": symbol,
                "timestamp": as_of.isoformat(),
                "price": {
                    "current": round(float(last["Close"]), 4),
                    "open": round(float(last["Open"]), 4),
                    "high": round(float(last["High"]), 4),
                    "low": round(float(last["Low"]), 4),
                    "volume": int(last["Volume"]),
                    "prev_close": round(float(prev["Close"]), 4),
                    "change_pct": round(
                        (float(last["Close"]) - float(prev["Close"]))
                        / float(prev["Close"]) * 100, 2,
                    ),
                },
                "indicators": self._extract_indicators(df),
                "recent_candles": self._recent_candles(df, n=10),
                "weekly": self._fetch_weekly_indicators_as_of(symbol, as_of),
            }
            return snap
        except Exception as exc:
            logger.error(f"{symbol}: historical snapshot error for {as_of} — {exc}", exc_info=True)
            return None

    def fetch_ohlcv_with_indicators(self, symbol: str) -> Optional[pd.DataFrame]:
        """Public method for chart rendering — returns daily OHLCV with indicators."""
        if self._broker is not None:
            df = self._fetch_ohlcv(symbol, interval="1d")
            if df is not None and not df.empty:
                return self._add_indicators(df)
        # broker not connected or returned no data — try yfinance
        df = self._fetch_yfinance(symbol)
        if df is None or df.empty:
            return None
        return self._add_indicators(df)

    def _fetch_yfinance(self, symbol: str) -> Optional[pd.DataFrame]:
        try:
            import yfinance as yf
            end = datetime.now()
            start = end - timedelta(days=max(self._lookback * 2, 400))
            df = yf.download(symbol, start=start, end=end,
                             auto_adjust=True, progress=False)
            if df is None or df.empty:
                return None
            # yfinance może zwrócić MultiIndex kolumn
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
            return df.tail(self._lookback + 50)
        except Exception as exc:
            logger.warning(f"{symbol}: yfinance fallback failed — {exc}")
            return None

    def get_price_only(self, symbol: str) -> Optional[float]:
        """Lightweight price fetch — used for SL/TP checks."""
        if self._broker is None:
            return None
        return self._broker.get_latest_price(symbol)

    def get_bar_for_date(self, symbol: str, on_date: date) -> Optional[dict]:
        """Returns raw OHLCV dict for a specific date. Used by backtester."""
        start = datetime.combine(on_date, datetime.min.time())
        end   = start + timedelta(days=2)
        df = self._broker.get_bars(symbol, "1d", start, end)
        if df is None or df.empty:
            return None
        row = df.iloc[0]
        return {
            "open":   float(row["Open"]),
            "high":   float(row["High"]),
            "low":    float(row["Low"]),
            "close":  float(row["Close"]),
            "volume": int(row["Volume"]),
        }

    def get_trading_days(self, start: date, end: date) -> list[date]:
        """Returns actual trading days in the range using SPY bars from the broker."""
        try:
            s = datetime.combine(start, datetime.min.time())
            e = datetime.combine(end,   datetime.min.time()) + timedelta(days=1)
            df = self._broker.get_bars("SPY", "1d", s, e)
            if df is not None and not df.empty:
                return [ts.date() if hasattr(ts, "date") else ts for ts in df.index]
        except Exception as exc:
            logger.warning(f"get_trading_days via broker failed: {exc}")

        # Fallback: calendar weekdays
        days, d = [], start
        while d <= end:
            if d.weekday() < 5:
                days.append(d)
            d += timedelta(days=1)
        return days

    # ------------------------------------------------------------------ #
    #  Weekly timeframe                                                    #
    # ------------------------------------------------------------------ #

    def _fetch_weekly_indicators(self, symbol: str) -> Optional[dict]:
        end   = datetime.now()
        start = end - timedelta(weeks=120)
        df = self._broker.get_bars(symbol, "1wk", start, end)
        if df is None or len(df) < 30:
            return None
        return self._compute_weekly_indicators(df)

    def _fetch_weekly_indicators_as_of(self, symbol: str, as_of: date) -> Optional[dict]:
        end   = datetime.combine(as_of, datetime.min.time()) + timedelta(days=1)
        start = datetime.combine(as_of, datetime.min.time()) - timedelta(days=800)
        df = self._broker.get_bars(symbol, "1wk", start, end)
        if df is None or len(df) < 30:
            return None
        return self._compute_weekly_indicators(df)

    def _compute_weekly_indicators(self, df: pd.DataFrame) -> Optional[dict]:
        try:
            df = df.dropna()
            c = df["Close"]

            rsi  = self._calc_rsi(c, 14).iloc[-1]
            _, _, histogram = self._calc_macd(c, 12, 26, 9)
            macd_hist      = histogram.iloc[-1]
            macd_hist_prev = histogram.iloc[-2]

            sma10 = c.rolling(10).mean().iloc[-1]
            sma20 = c.rolling(20).mean().iloc[-1]
            sma50 = c.rolling(50).mean().iloc[-1]
            current = float(c.iloc[-1])

            def safe(val):
                return round(float(val), 4) if not pd.isna(val) else None

            above_sma10 = current > float(sma10) if not pd.isna(sma10) else None
            above_sma20 = current > float(sma20) if not pd.isna(sma20) else None
            above_sma50 = current > float(sma50) if not pd.isna(sma50) else None
            count = sum(x is True for x in [above_sma10, above_sma20, above_sma50])

            if count == 3:
                trend = "STRONG UPTREND (above all weekly SMAs)"
            elif count == 0:
                trend = "STRONG DOWNTREND (below all weekly SMAs)"
            elif count >= 2:
                trend = "uptrend (above most weekly SMAs)"
            else:
                trend = "downtrend / mixed (below most weekly SMAs)"

            return {
                "rsi":        safe(rsi),
                "macd_hist":  safe(macd_hist),
                "macd_trend": "rising ↑" if macd_hist > macd_hist_prev else "falling ↓",
                "sma10":      safe(sma10),
                "sma20":      safe(sma20),
                "sma50":      safe(sma50),
                "above_sma10": above_sma10,
                "above_sma20": above_sma20,
                "above_sma50": above_sma50,
                "trend":      trend,
            }
        except Exception as exc:
            logger.debug(f"_compute_weekly_indicators failed: {exc}")
            return None

    # ------------------------------------------------------------------ #
    #  Private methods                                                     #
    # ------------------------------------------------------------------ #

    def _fetch_ohlcv(
        self,
        symbol: str,
        interval: str = "1d",
        bars: Optional[int] = None,
    ) -> Optional[pd.DataFrame]:
        if self._broker is None:
            return None
        bars = bars or self._lookback
        end  = datetime.now()

        if interval == "1d":
            start = end - timedelta(days=max(bars * 2, 400))
        else:
            start = end - timedelta(weeks=max(bars * 2, 120))

        df = self._broker.get_bars(symbol, interval, start, end)
        if df is None or df.empty:
            return None
        df = df.dropna()
        return df.tail(bars + 50)

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        c = df["Close"]

        df = df.copy()
        df["rsi"] = self._calc_rsi(c, self._rsi_period)

        macd_line, signal_line, histogram = self._calc_macd(
            c, self._macd_fast, self._macd_slow, self._macd_signal
        )
        df["macd"]        = macd_line
        df["macd_signal"] = signal_line
        df["macd_hist"]   = histogram

        bb_mid = c.rolling(self._bb_period).mean()
        bb_std = c.rolling(self._bb_period).std()
        df["bb_upper"] = bb_mid + self._bb_std * bb_std
        df["bb_lower"] = bb_mid - self._bb_std * bb_std
        df["bb_mid"]   = bb_mid

        for p in self._sma_periods:
            df[f"sma_{p}"] = c.rolling(p).mean()

        high_low    = df["High"] - df["Low"]
        high_close  = (df["High"] - df["Close"].shift()).abs()
        low_close   = (df["Low"]  - df["Close"].shift()).abs()
        true_range  = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"]   = true_range.rolling(14).mean()

        df["vol_sma20"] = df["Volume"].rolling(20).mean()

        return df

    def _calc_rsi(self, series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain  = delta.clip(lower=0).rolling(period).mean()
        loss  = (-delta.clip(upper=0)).rolling(period).mean()
        rs    = gain / loss.replace(0, np.nan)
        return 100 - 100 / (1 + rs)

    def _calc_macd(self, series: pd.Series, fast: int, slow: int, signal: int):
        ema_fast = series.ewm(span=fast,   adjust=False).mean()
        ema_slow = series.ewm(span=slow,   adjust=False).mean()
        macd     = ema_fast - ema_slow
        sig      = macd.ewm(span=signal,   adjust=False).mean()
        hist     = macd - sig
        return macd, sig, hist

    def _extract_indicators(self, df: pd.DataFrame) -> dict:
        last = df.iloc[-1]
        prev = df.iloc[-2]

        def safe(val):
            if pd.isna(val):
                return None
            return round(float(val), 4)

        ind = {
            "rsi":           safe(last["rsi"]),
            "macd":          safe(last["macd"]),
            "macd_signal":   safe(last["macd_signal"]),
            "macd_hist":     safe(last["macd_hist"]),
            "macd_hist_prev":safe(prev["macd_hist"]),
            "bb_upper":      safe(last["bb_upper"]),
            "bb_lower":      safe(last["bb_lower"]),
            "bb_mid":        safe(last["bb_mid"]),
            "atr":           safe(last["atr"]),
            "volume":        int(last["Volume"]),
            "vol_sma20":     safe(last["vol_sma20"]),
            "volume_ratio": (
                round(float(last["Volume"]) / float(last["vol_sma20"]), 2)
                if last["vol_sma20"] and float(last["vol_sma20"]) > 0
                else None
            ),
        }
        for p in self._sma_periods:
            ind[f"sma_{p}"] = safe(last.get(f"sma_{p}"))

        close = float(last["Close"])
        ind["above_sma20"]  = bool(close > (ind["sma_20"]  or 0))
        ind["above_sma50"]  = bool(close > (ind["sma_50"]  or 0))
        ind["above_sma200"] = bool(close > (ind["sma_200"] or 0))

        return ind

    def _recent_candles(self, df: pd.DataFrame, n: int = 10) -> list[dict]:
        rows = []
        for _, row in df.tail(n).iterrows():
            idx = row.name
            d   = idx.date() if hasattr(idx, "date") else str(idx)
            rows.append({
                "date":   str(d),
                "open":   round(float(row["Open"]),   2),
                "high":   round(float(row["High"]),   2),
                "low":    round(float(row["Low"]),    2),
                "close":  round(float(row["Close"]),  2),
                "volume": int(row["Volume"]),
            })
        return rows
