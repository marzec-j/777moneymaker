"""
Trading engine — connects all modules into a single decision cycle.
Handles SL/TP enforcement and multi-timeframe signal logging.
Uses SymbolBrain to dynamically discover and prioritize symbols.
TradeBot działa WYŁĄCZNIE na symbolach podanych przez BrainBota (journal.recommended_now).
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional, TYPE_CHECKING

from .brokers.base_broker import BaseBroker
from .llm_analyzer import LLMAnalyzer
from .market_data import MarketDataFetcher
from .risk_manager import RiskManager
from .symbol_learner import SymbolLearner
from .trade_logger import TradeLogger

if TYPE_CHECKING:
    from .symbol_brain import SymbolBrain
    from .brain_journal import BrainJournal

logger = logging.getLogger("777moneymaker")


class TradingEngine:

    def __init__(
        self,
        config: dict,
        broker: BaseBroker,
        data_fetcher: MarketDataFetcher,
        llm: LLMAnalyzer,
        risk: RiskManager,
        trade_log: TradeLogger,
        finnhub=None,
        brain: Optional["SymbolBrain"] = None,
        journal: Optional["BrainJournal"] = None,
        on_trade_closed: Optional[Callable[[dict], None]] = None,
    ):
        self._config = config
        self._broker = broker
        self._data   = data_fetcher
        self._llm    = llm
        self._risk   = risk
        self._log    = trade_log
        self._finnhub = finnhub
        self._brain   = brain
        self._journal = journal
        self._on_trade_closed = on_trade_closed

        # Fallback symbol list (used when brain is None or as seed)
        self._config_symbols: list[str] = config.get("symbols", [])
        if not self._config_symbols:
            try:
                dynamic = broker.get_all_assets()
                if dynamic:
                    self._config_symbols = dynamic
                    logger.info(
                        f"TradingEngine: using {len(dynamic)} symbols from broker "
                        "(no config list)"
                    )
            except Exception:
                pass

        if finnhub:
            try:
                from .news_store import NewsStore
                self._news_store: Optional["NewsStore"] = NewsStore(config)
            except Exception:
                self._news_store = None
        else:
            self._news_store = None

        self._global_news: list = []
        self._learner = SymbolLearner(config)

    # ─────────────────────────────────────────────────────────────────────────
    #  Main cycle
    # ─────────────────────────────────────────────────────────────────────────

    def run_cycle(self):
        logger.info("=" * 60)
        logger.info(f"NEW CYCLE | {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")

        account      = self._broker.get_account()
        equity       = account.get("equity", 0)
        cash         = account.get("cash", 0)
        buying_power = account.get("buying_power", cash)
        dtbp         = account.get("daytrading_buying_power")
        # effective_bp = the real constraint for new orders.
        # daytrading_buying_power is 4× margin and doesn't shrink as positions open;
        # buying_power is the actual available amount Alpaca will enforce.
        # Use the smaller of the two so we never overcommit.
        if dtbp is not None:
            effective_bp = min(dtbp, buying_power)
        else:
            effective_bp = buying_power
        dtbp_str = f" | DayTrade BP: ${dtbp:,.2f}" if dtbp is not None else ""
        logger.info(
            f"Account | Equity: ${equity:,.2f} | Cash: ${cash:,.2f} | "
            f"Portfolio: ${account.get('portfolio_value', 0):,.2f} | "
            f"BP: ${buying_power:,.2f}{dtbp_str}"
        )

        self._risk.update_equity(equity)
        if self._risk.is_halted:
            logger.warning("Trading halted — daily stop loss active!")
            return

        if not self._broker.is_market_open():
            logger.info("Market closed — skipping cycle")
            return

        # Minimum buying power to bother with new-position analysis ($10 threshold).
        # SL/TP checks still run below regardless of buying power.
        _min_bp_for_analysis = self._config.get("risk", {}).get("min_buying_power", 10.0)
        _no_new_positions = buying_power < _min_bp_for_analysis
        if _no_new_positions:
            logger.info(
                f"Buying power ${buying_power:,.2f} — skipping new positions, checking SL/TP only"
            )

        # ── Step 1: determine which symbols to fetch news for ─────────────
        # Use brain's current watchlist if available; otherwise fall back to config.
        if self._brain:
            news_symbols = self._brain.get_watchlist()
        else:
            news_symbols = self._config_symbols

        # ── Step 2: fetch all news once per cycle ─────────────────────────
        self._global_news = []
        if self._finnhub:
            try:
                all_news = self._finnhub.get_all_news(news_symbols, count_market=30)
                self._global_news = all_news
                if all_news:
                    logger.info(f"News fetched: {len(all_news)} articles")
                    if self._news_store:
                        saved = self._news_store.save(all_news)
                        if saved:
                            logger.debug(f"NewsStore: +{saved} new articles saved")

                    # ── Step 3: update brain from news (discovers new symbols) ─
                    if self._brain:
                        new_syms = self._brain.update_from_news(all_news)
                        if new_syms > 0:
                            logger.info(
                                f"SymbolBrain: {new_syms} new symbol(s) discovered from news"
                            )
            except Exception as exc:
                logger.debug(f"News fetch error: {exc}")

        # ── Step 4: enforce SL/TP before analysis ─────────────────────────
        self._check_sl_tp_exits()

        # ── Step 5: get fresh positions (some may have been closed by SL/TP) ─
        open_positions = self._broker.get_positions()
        open_count     = len(open_positions)
        open_symbols   = {p["symbol"] for p in open_positions}
        logger.info(
            f"Open positions ({open_count}): {', '.join(open_symbols) or 'none'}"
        )
        for pos in open_positions:
            side_label = pos.get("side", "long").upper()
            logger.info(
                f"  [{side_label}] {pos['symbol']}: {pos['qty']}x "
                f"@ ${pos['avg_entry_price']:.2f} | "
                f"P&L: ${pos.get('unrealized_pl', 0):+.2f} "
                f"({pos.get('unrealized_plpc', 0):+.2%})"
            )

        # ── Step 6: build watchlist for this cycle ────────────────────────
        if self._brain:
            watchlist = self._brain.get_watchlist(open_symbols)
            brain_total = self._brain.symbol_count()
            logger.info(
                f"SymbolBrain watchlist: {len(watchlist)} symbols "
                f"(tracking {brain_total} total)"
            )
            top = self._brain.top_scored(8)
            if top:
                top_str = "  |  ".join(f"{s} {sc:.3f}" for s, sc in top)
                logger.info(f"  Top scores: {top_str}")
        else:
            watchlist = self._config_symbols

        # ── TradeBot: ogranicz do rekomendacji BrainBota (journal) ────────
        if self._journal:
            journal_syms = set(self._journal.get_recommended_symbols())
            if journal_syms:
                filtered = [s for s in watchlist if s in journal_syms or s in open_symbols]
                if filtered:
                    watchlist = filtered
                    logger.info(
                        f"TradeBot: watchlist ograniczony do {len(watchlist)} symboli "
                        f"z journala BrainBota ({len(journal_syms)} rekomendowanych)"
                    )
                else:
                    logger.warning(
                        "TradeBot: journal symbols dały pustą watchlistę — "
                        "używam pełnej listy brain"
                    )
            else:
                logger.info("TradeBot: journal BrainBota pusty — używam pełnej listy brain")

        # ── Step 7: analyze each symbol in watchlist ──────────────────────
        if _no_new_positions:
            # Only manage existing positions (exits via SL/TP already run above)
            for pos in open_positions:
                self._analyze_symbol(
                    pos["symbol"], open_count, equity, cash, effective_bp,
                    open_positions, self._global_news,
                )
                time.sleep(2)
        else:
            for symbol in watchlist:
                self._analyze_symbol(symbol, open_count, equity, cash, effective_bp,
                                     open_positions, self._global_news)
                time.sleep(2)

    # ─────────────────────────────────────────────────────────────────────────
    #  SL/TP enforcement
    # ─────────────────────────────────────────────────────────────────────────

    def _check_sl_tp_exits(self):
        positions = self._broker.get_positions()
        if not positions:
            return

        for pos in positions:
            symbol = pos["symbol"]
            sl     = pos.get("stop_loss")
            tp     = pos.get("take_profit")
            side   = pos.get("side", "long")

            if not sl and not tp:
                continue

            price = self._data.get_price_only(symbol)
            if price is None:
                logger.warning(f"SL/TP check: could not fetch price for {symbol}")
                continue

            triggered = None
            if side == "long":
                if sl and price <= sl:
                    triggered = ("SL", sl, "sell")
                elif tp and price >= tp:
                    triggered = ("TP", tp, "sell")
            else:
                if sl and price >= sl:
                    triggered = ("SL", sl, "buy")
                elif tp and price <= tp:
                    triggered = ("TP", tp, "buy")

            if triggered:
                label, level, close_side = triggered
                qty = int(pos["qty"])
                logger.info(
                    f"[{label} HIT] {symbol} | price=${price:.2f} crossed "
                    f"{label}=${level:.2f} | closing {side} position"
                )
                order = self._broker.place_order(
                    symbol=symbol, qty=qty, side=close_side, order_type="market",
                )
                if order:
                    action = "SL_EXIT" if label == "SL" else "TP_EXIT"
                    self._log.log_trade(
                        symbol=symbol, action=action, qty=qty, price=price,
                        order_id=order["order_id"], stop_loss=sl or 0,
                        take_profit=tp or 0, confidence=0.0,
                        reasoning=f"{label} hit at ${price:.2f} (level: ${level:.2f})",
                    )
                else:
                    logger.error(f"{symbol}: {label} exit order was not placed!")

    # ─────────────────────────────────────────────────────────────────────────
    #  Symbol analysis
    # ─────────────────────────────────────────────────────────────────────────

    def _analyze_symbol(
        self,
        symbol: str,
        open_count: int,
        equity: float,
        cash: float,
        effective_bp: float,
        open_positions: list[dict],
        global_news: Optional[list] = None,
    ):
        logger.info(f"--- Analysis: {symbol} ---")

        snapshot = self._data.get_snapshot(symbol)
        if snapshot is None:
            self._log.log_skip(symbol, "no market data")
            return

        # ── Update brain with fresh market data ───────────────────────────
        if self._brain:
            self._brain.update_from_snapshot(symbol, snapshot)

        price   = snapshot["price"]["current"]
        rsi_val = snapshot["indicators"].get("rsi")
        rsi_str = f"{rsi_val:.1f}" if rsi_val is not None else "N/A"
        logger.info(
            f"{symbol} @ ${price:.2f} "
            f"({snapshot['price']['change_pct']:+.2f}%) | RSI(D)={rsi_str}"
        )

        weekly = snapshot.get("weekly")
        if weekly:
            w_rsi     = weekly.get("rsi")
            w_rsi_str = f"{w_rsi:.1f}" if w_rsi is not None else "N/A"
            logger.info(
                f"  Weekly | RSI={w_rsi_str} | "
                f"MACD {weekly.get('macd_trend', '?')} | "
                f"{weekly.get('trend', '?')}"
            )

        news = [
            item for item in (global_news or [])
            if item.get("symbol") == symbol
        ]
        macro_news = [
            item for item in (global_news or [])
            if item.get("symbol") == "MARKET"
        ]
        if news:
            logger.info(f"  Company news: {len(news)} articles for {symbol}")

        profile      = self._learner.get_profile(symbol)
        profile_text = self._learner.format_for_llm(profile)
        if profile["total_decisions"] > 0:
            wr_str = (
                "{:.0%}".format(profile["win_rate"])
                if profile["win_rate"] is not None
                else "N/A"
            )
            logger.info(
                f"  Learning: {profile['total_decisions']} decisions | "
                f"win rate: {wr_str} | "
                f"pattern: {(profile['recent_pattern'] or '')[-40:] or 'none'}"
            )

        existing_pos = self._broker.get_position(symbol)

        decision = self._llm.analyze(
            snapshot,
            news=news,
            global_news=macro_news,
            symbol_profile=profile_text,
        )
        if decision is None:
            self._log.log_skip(symbol, "no LLM response")
            return

        # ── Record LLM decision in brain ──────────────────────────────────
        if self._brain:
            self._brain.mark_analyzed(symbol, decision, profile)

        self._log.log_ai_decision(symbol, decision, snapshot)

        action    = decision["action"]
        conf      = decision["confidence"]
        reasoning = decision.get("reasoning", "")
        signals   = ", ".join(decision.get("key_signals", []))

        logger.info(f"{symbol}: LLM → {action} | conf={conf:.0%} | {reasoning[:120]}")
        if signals:
            logger.info(f"  Signals: {signals}")

        # ── Trade execution ───────────────────────────────────────────────
        if action == "BUY":
            if existing_pos and existing_pos["side"] == "short":
                self._handle_short_exit(symbol, existing_pos, price, decision)
            elif existing_pos and existing_pos["side"] == "long":
                logger.info(f"{symbol}: already long — skipping BUY signal")
            else:
                ok, reason = self._risk.validate_signal(symbol, decision, open_count, equity)
                if ok:
                    if effective_bp <= 0:
                        self._log.log_skip(symbol, "insufficient day trading buying power")
                        logger.warning(f"{symbol}: BUY skipped — insufficient day trading buying power")
                    else:
                        self._handle_entry(symbol, price, equity, effective_bp, decision, snapshot)
                else:
                    self._log.log_skip(symbol, reason)

        elif action == "SELL":
            if existing_pos and existing_pos["side"] == "long":
                self._handle_exit(symbol, existing_pos, price, decision)
            elif existing_pos and existing_pos["side"] == "short":
                logger.info(f"{symbol}: already short — skipping SELL signal")
            else:
                ok, reason = self._risk.validate_signal(symbol, decision, open_count, equity)
                if ok:
                    if effective_bp <= 0:
                        self._log.log_skip(symbol, "insufficient day trading buying power")
                        logger.warning(f"{symbol}: SHORT skipped — insufficient day trading buying power")
                    else:
                        self._handle_short_entry(symbol, price, equity, effective_bp, decision, snapshot)
                else:
                    self._log.log_skip(symbol, reason)

    # ─────────────────────────────────────────────────────────────────────────
    #  Order execution
    # ─────────────────────────────────────────────────────────────────────────

    def _handle_entry(self, symbol, price, equity, buying_power, decision, snapshot):
        # Re-fetch buying_power — multiple entries in one cycle drain it; stale value causes rejections
        try:
            fresh = self._broker.get_account()
            fresh_bp = fresh.get("buying_power", buying_power)
            buying_power = min(buying_power, fresh_bp)
            if buying_power < price:
                logger.warning(
                    f"{symbol}: BUY skipped — buying power ${buying_power:,.2f} < price ${price:,.2f}"
                )
                self._log.log_skip(symbol, f"buying power ${buying_power:,.2f} < price")
                return
        except Exception:
            pass
        atr = snapshot["indicators"].get("atr")
        pos = self._risk.calc_position("BUY", price, equity, decision, atr, buying_power=buying_power)
        order = self._broker.place_order(
            symbol=symbol, qty=pos["qty"], side="buy", order_type="market",
            stop_loss=pos["stop_loss"], take_profit=pos["take_profit"],
        )
        if order:
            self._log.log_trade(
                symbol=symbol, action="BUY", qty=pos["qty"], price=price,
                order_id=order["order_id"], stop_loss=pos["stop_loss"],
                take_profit=pos["take_profit"], confidence=decision["confidence"],
                reasoning=decision.get("reasoning", ""),
            )
        else:
            logger.error(f"{symbol}: BUY order was not placed!")

    def _handle_exit(self, symbol, existing_pos, price, decision):
        qty   = int(existing_pos["qty"])
        order = self._broker.place_order(
            symbol=symbol, qty=qty, side="sell", order_type="market"
        )
        if order:
            self._log.log_trade(
                symbol=symbol, action="SELL", qty=qty, price=price,
                order_id=order["order_id"], stop_loss=0, take_profit=0,
                confidence=decision["confidence"],
                reasoning=decision.get("reasoning", ""),
            )
            pnl = existing_pos.get("unrealized_pl", 0.0)
            self._notify_trade_closed(symbol, "SELL", pnl)
        else:
            logger.error(f"{symbol}: SELL order was not placed!")

    def _handle_short_entry(self, symbol, price, equity, buying_power, decision, snapshot):
        # Re-fetch position — race condition: get_position() in _analyze_symbol may have
        # returned None while a long position actually exists (timing / transient API error).
        # Trying to short more shares than held causes Alpaca 403 "insufficient qty".
        fresh_pos = self._broker.get_position(symbol)
        if fresh_pos and fresh_pos["side"] == "long":
            logger.info(
                f"{symbol}: re-fetch found existing long position — closing instead of shorting"
            )
            self._handle_exit(symbol, fresh_pos, price, decision)
            return

        try:
            fresh = self._broker.get_account()
            fresh_bp = fresh.get("buying_power", buying_power)
            buying_power = min(buying_power, fresh_bp)
            if buying_power < price:
                logger.warning(
                    f"{symbol}: SHORT skipped — buying power ${buying_power:,.2f} < price ${price:,.2f}"
                )
                self._log.log_skip(symbol, f"buying power ${buying_power:,.2f} < price")
                return
        except Exception:
            pass
        atr = snapshot["indicators"].get("atr")
        pos = self._risk.calc_position("SELL", price, equity, decision, atr, buying_power=buying_power)
        order = self._broker.place_order(
            symbol=symbol, qty=pos["qty"], side="sell", order_type="market",
            stop_loss=pos["stop_loss"], take_profit=pos["take_profit"],
        )
        if order:
            self._log.log_trade(
                symbol=symbol, action="SHORT", qty=pos["qty"], price=price,
                order_id=order["order_id"], stop_loss=pos["stop_loss"],
                take_profit=pos["take_profit"], confidence=decision["confidence"],
                reasoning=decision.get("reasoning", ""),
            )
        else:
            logger.error(f"{symbol}: SHORT order was not placed!")

    def _handle_short_exit(self, symbol, existing_pos, price, decision):
        qty   = int(existing_pos["qty"])
        order = self._broker.place_order(
            symbol=symbol, qty=qty, side="buy", order_type="market"
        )
        if order:
            self._log.log_trade(
                symbol=symbol, action="COVER", qty=qty, price=price,
                order_id=order["order_id"], stop_loss=0, take_profit=0,
                confidence=decision["confidence"],
                reasoning=decision.get("reasoning", ""),
            )
            pnl = existing_pos.get("unrealized_pl", 0.0)
            self._notify_trade_closed(symbol, "COVER", pnl)
        else:
            logger.error(f"{symbol}: COVER order was not placed!")

    def _notify_trade_closed(self, symbol: str, action: str, pnl: float):
        if self._on_trade_closed:
            was_rec = self._journal.get_recommended_symbols() if self._journal else []
            self._on_trade_closed({
                "symbol":         symbol,
                "action":         action,
                "pnl":            pnl,
                "was_recommended": symbol in was_rec,
            })
