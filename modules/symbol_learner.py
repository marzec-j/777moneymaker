"""
Symbol learner — builds per-symbol performance profiles from past AI decisions and trades.
Injected into the LLM prompt so the bot learns from its own history over time.

Profile covers:
- Decision counts (BUY / SELL / HOLD)
- Actual trade win-rate and average return
- Confidence calibration (are high-conf calls actually winning?)
- News impact correlation (bullish/bearish news → outcome)
- Most frequent key signals in winning vs losing trades
- Recent decision pattern (last 10 calls)
"""

from __future__ import annotations

import csv
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger("777moneymaker")

_MAX_DECISIONS = 300   # scan up to last N decisions per symbol
_RECENT_N      = 10    # decisions to show in "recent pattern"


class SymbolLearner:

    def __init__(self, config: dict):
        data_cfg = config.get("data", {})
        data_dir = Path(data_cfg.get("data_dir", "data"))
        self._decisions_path = data_dir / data_cfg.get("decisions_file", "ai_decisions.jsonl")
        self._trades_path    = data_dir / data_cfg.get("trades_file",    "trades.csv")

    # ── Public API ─────────────────────────────────────────────────────────

    def get_profile(self, symbol: str) -> dict:
        """Compute and return a full learning profile for the symbol."""
        decisions = self._load_decisions(symbol)
        trades    = self._load_trades(symbol)
        return self._compute(symbol, decisions, trades)

    def format_for_llm(self, profile: dict) -> str:
        """Return a compact multi-line summary for injection into the LLM prompt."""
        if not profile or profile["total_decisions"] == 0:
            return "No historical data yet — this is an early analysis."

        lines = []
        n = profile["total_decisions"]
        b = profile["buy_count"]
        s = profile["sell_count"]
        h = profile["hold_count"]
        lines.append(f"Total decisions: {n}  (BUY:{b}  SELL:{s}  HOLD:{h})")

        ct = profile["closed_trades"]
        if ct > 0:
            wr  = profile["win_rate"]
            ar  = profile["avg_return_pct"]
            wstr = f"{wr:.0%}" if wr is not None else "?"
            astr = f"{ar:+.2f}%" if ar is not None else "?"
            lines.append(f"Closed trades: {ct} | Win rate: {wstr} | Avg return: {astr}")

            cw = profile["avg_conf_winners"]
            cl = profile["avg_conf_losers"]
            if cw is not None and cl is not None:
                diff = cw - cl
                note = " ← confidence IS predictive" if diff > 0.05 else " ← confidence not reliable"
                lines.append(f"Confidence: winners avg {cw:.0%} / losers avg {cl:.0%}{note}")

        if profile["top_winning_signals"]:
            lines.append(f"Signals in wins:   {profile['top_winning_signals']}")
        if profile["top_losing_signals"]:
            lines.append(f"Signals in losses: {profile['top_losing_signals']}")

        if profile["news_bull_wins"] + profile["news_bull_losses"] > 0:
            total_bull = profile["news_bull_wins"] + profile["news_bull_losses"]
            bull_wr = profile["news_bull_wins"] / total_bull
            lines.append(f"Bullish-news trades: {total_bull}  win rate {bull_wr:.0%}")

        if profile["news_bear_wins"] + profile["news_bear_losses"] > 0:
            total_bear = profile["news_bear_wins"] + profile["news_bear_losses"]
            bear_wr = profile["news_bear_wins"] / total_bear
            lines.append(f"Bearish-news trades: {total_bear}  win rate {bear_wr:.0%}")

        if profile["recent_pattern"]:
            lines.append(f"Last {_RECENT_N} decisions: {profile['recent_pattern']}")

        if profile["calibration_note"]:
            lines.append(f"⚠ Calibration: {profile['calibration_note']}")

        return "\n".join(lines)

    # ── Data loading ───────────────────────────────────────────────────────

    def _load_decisions(self, symbol: str) -> list[dict]:
        if not self._decisions_path.exists():
            return []
        result = []
        try:
            with open(self._decisions_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        if d.get("symbol") == symbol:
                            result.append(d)
                    except Exception:
                        pass
        except Exception as exc:
            logger.debug(f"SymbolLearner load decisions {symbol}: {exc}")
        return result[-_MAX_DECISIONS:]

    def _load_trades(self, symbol: str) -> list[dict]:
        if not self._trades_path.exists():
            return []
        result = []
        try:
            with open(self._trades_path, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("symbol") == symbol:
                        result.append(row)
        except Exception as exc:
            logger.debug(f"SymbolLearner load trades {symbol}: {exc}")
        return result

    # ── Profile computation ────────────────────────────────────────────────

    def _compute(self, symbol: str, decisions: list[dict], trades: list[dict]) -> dict:
        profile: dict = {
            "symbol":              symbol,
            "total_decisions":     len(decisions),
            "buy_count":           0,
            "sell_count":          0,
            "hold_count":          0,
            "closed_trades":       0,
            "win_rate":            None,
            "avg_return_pct":      None,
            "avg_conf_winners":    None,
            "avg_conf_losers":     None,
            "top_winning_signals": "",
            "top_losing_signals":  "",
            "news_bull_wins":      0,
            "news_bull_losses":    0,
            "news_bear_wins":      0,
            "news_bear_losses":    0,
            "recent_pattern":      "",
            "calibration_note":    "",
        }

        if not decisions:
            return profile

        # Decision counts
        for d in decisions:
            action = d.get("decision", {}).get("action", "HOLD")
            if action == "BUY":
                profile["buy_count"] += 1
            elif action in ("SELL", "SHORT"):
                profile["sell_count"] += 1
            else:
                profile["hold_count"] += 1

        # Recent pattern (last N decisions, oldest→newest)
        recent = decisions[-_RECENT_N:]
        parts = []
        for d in recent:
            a = d.get("decision", {}).get("action", "HOLD")
            c = d.get("decision", {}).get("confidence", 0)
            parts.append(f"{a}({c:.0%})")
        profile["recent_pattern"] = " → ".join(parts)

        # Match BUY→SELL/EXIT pairs to compute actual returns
        buys  = [t for t in trades if t.get("action") == "BUY"]
        exits = [t for t in trades if t.get("action") in ("SELL", "TP_EXIT", "SL_EXIT", "COVER")]

        returns:       list[float] = []
        conf_winners:  list[float] = []
        conf_losers:   list[float] = []
        winning_sigs:  list[str]   = []
        losing_sigs:   list[str]   = []

        buy_q = list(buys)
        for ex in exits:
            if not buy_q:
                break
            buy = buy_q.pop(0)
            try:
                bp = float(buy.get("price", 0) or 0)
                sp = float(ex.get("price",  0) or 0)
                if bp <= 0:
                    continue
                ret = (sp - bp) / bp * 100
                returns.append(ret)

                # Match the corresponding AI decision by timestamp proximity
                buy_ts = (buy.get("timestamp") or "")[:16]
                matched_dec = None
                for dec in decisions:
                    if (dec.get("timestamp") or "")[:16] == buy_ts:
                        matched_dec = dec
                        break

                if matched_dec:
                    conf = matched_dec.get("decision", {}).get("confidence")
                    sigs = matched_dec.get("decision", {}).get("key_signals", [])
                    ni   = matched_dec.get("decision", {}).get("news_impact", "neutral")
                    is_win = ret > 0

                    if conf is not None:
                        (conf_winners if is_win else conf_losers).append(float(conf))
                    if is_win:
                        winning_sigs.extend(sigs)
                        if "bullish" in str(ni):
                            profile["news_bull_wins"] += 1
                        elif "bearish" in str(ni):
                            profile["news_bear_wins"] += 1
                    else:
                        losing_sigs.extend(sigs)
                        if "bullish" in str(ni):
                            profile["news_bull_losses"] += 1
                        elif "bearish" in str(ni):
                            profile["news_bear_losses"] += 1
            except Exception:
                pass

        if returns:
            winners = [r for r in returns if r > 0]
            profile["closed_trades"]  = len(returns)
            profile["win_rate"]       = len(winners) / len(returns)
            profile["avg_return_pct"] = sum(returns) / len(returns)

        if conf_winners:
            profile["avg_conf_winners"] = sum(conf_winners) / len(conf_winners)
        if conf_losers:
            profile["avg_conf_losers"] = sum(conf_losers) / len(conf_losers)

        # Top signals in wins vs losses
        if winning_sigs:
            top = Counter(winning_sigs).most_common(3)
            profile["top_winning_signals"] = ", ".join(f"{s}({n}x)" for s, n in top)
        if losing_sigs:
            top = Counter(losing_sigs).most_common(3)
            profile["top_losing_signals"] = ", ".join(f"{s}({n}x)" for s, n in top)

        # Calibration note
        wr = profile["win_rate"]
        n  = profile["closed_trades"]
        if wr is not None and n >= 3:
            if wr < 0.35:
                profile["calibration_note"] = (
                    f"Win rate only {wr:.0%} — be MORE conservative, require stronger signals, "
                    f"consider raising confidence threshold."
                )
            elif wr > 0.70:
                profile["calibration_note"] = (
                    f"Win rate {wr:.0%} — current strategy effective, maintain approach."
                )

        return profile
