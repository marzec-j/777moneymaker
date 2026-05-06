"""
LLM communication module via Ollama HTTP API.
Sends market snapshot + news + self-learning history and receives a structured trading decision.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from collections import deque
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("777moneymaker")

# ── Keyword-based news sentiment ──────────────────────────────────────────────

_BULLISH = {
    "beat", "beats", "surge", "surges", "gain", "gains", "rally", "rallies",
    "upgrade", "upgrades", "outperform", "strong", "record", "growth", "profit",
    "positive", "rises", "bullish", "buy", "opportunity", "partnership", "deal",
    "expands", "expansion", "innovative", "breakthrough", "approval",
}
_BEARISH = {
    "miss", "misses", "drop", "drops", "fall", "falls", "decline", "declines",
    "downgrade", "downgrades", "underperform", "weak", "loss", "losses", "cut",
    "cuts", "layoffs", "layoff", "risk", "risks", "fear", "fears", "crisis",
    "recession", "inflation", "hawkish", "rate hike", "investigation", "fraud",
    "fine", "fined", "recall", "recalled", "bankrupt", "bankruptcy",
    "warning", "shortfall", "deficit", "concern", "probe", "lawsuit", "sell",
}


def _news_sentiment(headline: str) -> str:
    words = set(re.findall(r"\w+", headline.lower()))
    bull = sum(1 for w in _BULLISH if w in words)
    bear = sum(1 for w in _BEARISH if w in words)
    if bull > bear:
        return "📈 BULLISH"
    if bear > bull:
        return "📉 BEARISH"
    return "⬜ NEUTRAL"


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert AI hedge fund manager specializing in short-term US stock trading.
You analyze technical indicators, multi-timeframe charts, global news, and your own trade history.
You trade BOTH directions — long (BUY) and short (SELL). Strong downtrends are SHORT opportunities, not HOLD.

DECISION RULES:
1. Respond ONLY in valid JSON — no text before or after the JSON block.
2. HOLD only when signals are genuinely mixed or unclear. A clear downtrend is a SHORT, not a HOLD.
3. Confidence 0.0-1.0: below 0.65 → auto-rejected by risk manager.
4. Always provide stop_loss and take_profit (use ATR for sizing).
5. BUY and SELL signals must be equally considered — directional bias is a flaw, not a feature.

SELF-LEARNING RULES (mandatory — read the SYMBOL LEARNING PROFILE section):
6. If win rate < 40%: require RSI + MACD + volume ALL aligned before any BUY or SELL. Raise confidence threshold.
7. If win rate > 65%: trust the working pattern — maintain current signal requirements.
8. If a signal type appears often in LOSING trades: treat it as a red flag, not a trigger.
9. If a signal type appears often in WINNING trades: weight it more heavily.
10. Use calibration note to adjust your behavior every cycle — this is how you improve.

NEWS INTEGRATION RULES (symmetric — apply equally to longs and shorts):
11. 📈 BULLISH company news + technical buy signal → increase BUY confidence +5-15%.
12. 📉 BEARISH company news + oversold/neutral RSI → increase SHORT (SELL) confidence +5-15%.
13. 📉 BEARISH company news + overbought RSI → strong SHORT signal, raise confidence +10-20%.
14. Global macro risk (Fed hawkish, recession fears, geopolitical crisis) → reduce BUY confidence by 10-20% AND increase SHORT confidence by 5-15%.
15. Global macro positive (rate cuts, strong GDP, trade deals) → increase BUY confidence, reduce SHORT confidence.
16. Breaking negative news overrides technical signals — do not BUY into known bad news; consider SHORT instead.

TREND-DIRECTION RULES:
17. Stock below SMA20 + SMA50 + SMA200 ("STRONG DOWNTREND") → default bias is SHORT, not HOLD.
18. Stock in weekly downtrend + daily MACD falling + RSI < 50 → SHORT is the correct directional trade.
19. Stock above all SMAs + MACD rising + RSI > 50 → BUY is the correct directional trade.
20. Mixed signals (e.g. above SMA200 but below SMA20) → reduce confidence, consider HOLD.

RESPONSE FORMAT (strict JSON):
{
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": 0.0-1.0,
  "entry_price": <number or null>,
  "stop_loss": <number or null>,
  "take_profit": <number or null>,
  "reasoning": "<what drove the decision — cite news + technicals>",
  "key_signals": ["signal1", "signal2", "signal3"],
  "news_impact": "bullish" | "bearish" | "neutral"
}"""

# ── Prompt template ───────────────────────────────────────────────────────────

USER_PROMPT_TEMPLATE = """Analyze {symbol} and make a trading decision.

╔══════════════════════════════════════════════════════════════╗
║  SYMBOL LEARNING PROFILE (self-learned, use to calibrate)    ║
╚══════════════════════════════════════════════════════════════╝
{symbol_profile_section}

╔══════════════════════════════════════════════════════════════╗
║  GLOBAL MACRO NEWS (market-wide context)                     ║
╚══════════════════════════════════════════════════════════════╝
{global_news_section}

╔══════════════════════════════════════════════════════════════╗
║  COMPANY NEWS: {symbol}                                      ║
╚══════════════════════════════════════════════════════════════╝
{news_section}

╔══════════════════════════════════════════════════════════════╗
║  WEEKLY TIMEFRAME (higher-timeframe direction)               ║
╚══════════════════════════════════════════════════════════════╝
{weekly_section}

╔══════════════════════════════════════════════════════════════╗
║  DAILY PRICE & INDICATORS                                    ║
╚══════════════════════════════════════════════════════════════╝
Price:    ${current:.2f}  ({change_pct:+.2f}% today)
OHLC:     O=${open:.2f}  H=${high:.2f}  L=${low:.2f}  prev=${prev_close:.2f}

RSI(14):  {rsi:.1f}  → {rsi_interp}
MACD:     {macd:.4f} | Signal: {macd_signal:.4f} | Hist: {macd_hist:.4f}  ({macd_trend})
BB:       L=${bb_lower:.2f}  M=${bb_mid:.2f}  U=${bb_upper:.2f}  → {bb_position}
ATR(14):  {atr:.2f}

SMA20:  ${sma_20:.2f}  ({above_sma20})
SMA50:  ${sma_50:.2f}  ({above_sma50})
SMA200: ${sma_200:.2f}  ({above_sma200})
Trend:  {trend_desc}

Volume: {volume:,} (avg {vol_sma20:,.0f}) → {volume_ratio:.1f}x  {volume_interp}

Last 10 daily candles:
{candles_str}

╔══════════════════════════════════════════════════════════════╗
║  YOUR DECISION & TRADE HISTORY FOR {symbol}                  ║
╚══════════════════════════════════════════════════════════════╝
{history_section}

─────────────────────────────────────────────────────────────
Priority: self-learning profile → news → technicals → historical accuracy.
Apply calibration notes before deciding.

IMPORTANT: Output ONLY the JSON object below — no explanation, no text before or after:
{{"action": "BUY|SELL|HOLD", "confidence": 0.0, "entry_price": null, "stop_loss": null, "take_profit": null, "reasoning": "...", "key_signals": [], "news_impact": "neutral"}}"""


# ── Helper functions ──────────────────────────────────────────────────────────

def _interpret_rsi(rsi: Optional[float]) -> str:
    if rsi is None:
        return "no data"
    if rsi >= 75:
        return "EXTREMELY OVERBOUGHT ⚠️"
    if rsi >= 70:
        return "OVERBOUGHT (sell signal)"
    if rsi <= 25:
        return "EXTREMELY OVERSOLD ⚠️"
    if rsi <= 30:
        return "OVERSOLD (buy signal)"
    if rsi >= 60:
        return "strong (neutral-bullish)"
    if rsi <= 40:
        return "weak (neutral-bearish)"
    return "neutral"


def _interpret_bb(price: float, bb_lower: float, bb_mid: float, bb_upper: float) -> str:
    pct = (price - bb_lower) / max(bb_upper - bb_lower, 0.0001)
    if pct < 0.1:
        return f"near lower band ({pct:.0%}) — potential bounce"
    if pct > 0.9:
        return f"near upper band ({pct:.0%}) — potential reversal"
    return f"mid-channel ({pct:.0%})"


def _interpret_volume(ratio: Optional[float]) -> str:
    if ratio is None:
        return "no data"
    if ratio >= 2.0:
        return "VERY HIGH — strong conviction"
    if ratio >= 1.5:
        return "above average — move confirmed"
    if ratio <= 0.5:
        return "VERY LOW — weak conviction"
    return "normal"


def _trend_desc(above_20: bool, above_50: bool, above_200: bool) -> str:
    count = sum([above_20, above_50, above_200])
    if count == 3:
        return "STRONG UPTREND (above all SMAs)"
    if count == 0:
        return "STRONG DOWNTREND (below all SMAs)"
    if above_200 and above_50:
        return "uptrend (long- and mid-term)"
    if not above_200 and not above_50:
        return "downtrend (long- and mid-term)"
    return "mixed — no clear trend"


# ── Main class ────────────────────────────────────────────────────────────────

class LLMAnalyzer:
    """Sends data to local Ollama, includes news + self-learning history, parses JSON response."""

    def __init__(self, config: dict):
        llm_cfg = config.get("llm", {})
        self._base_url   = llm_cfg.get("base_url", "http://localhost:11434").rstrip("/")
        self._model      = llm_cfg.get("model", "mistral")
        self._timeout    = llm_cfg.get("timeout", 120)
        self._temperature = llm_cfg.get("temperature", 0.1)

        data_cfg = config.get("data", {})
        data_dir = Path(data_cfg.get("data_dir", "data"))
        self._decisions_path = data_dir / data_cfg.get("decisions_file", "ai_decisions.jsonl")
        self._trades_path    = data_dir / data_cfg.get("trades_file",    "trades.csv")

    def is_available(self) -> bool:
        try:
            r = requests.get(f"{self._base_url}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def analyze(
        self,
        snapshot: dict,
        news: Optional[list] = None,
        global_news: Optional[list] = None,
        symbol_profile: Optional[str] = None,
    ) -> Optional[dict]:
        prompt = self._build_prompt(snapshot, news or [], global_news or [], symbol_profile or "")
        raw = self._call_ollama(prompt)
        if raw is None:
            return None
        decision = self._parse_response(raw)
        if decision:
            logger.debug(
                f"{snapshot['symbol']}: LLM → {decision['action']} "
                f"conf={decision.get('confidence', 0):.0%} "
                f"news={decision.get('news_impact', '?')}"
            )
        return decision

    # ── Prompt building ───────────────────────────────────────────────────────

    def _build_prompt(self, snap: dict, news: list, global_news: list, symbol_profile: str = "") -> str:
        p   = snap["price"]
        ind = snap["indicators"]

        def v(key, default=0.0):
            val = ind.get(key)
            return val if val is not None else default

        candles_str = "\n".join(
            f"  {c['date']}  O={c['open']}  H={c['high']}  L={c['low']}  "
            f"C={c['close']}  Vol={c['volume']:,}"
            for c in snap.get("recent_candles", [])
        )

        return USER_PROMPT_TEMPLATE.format(
            symbol=snap["symbol"],
            symbol_profile_section=symbol_profile or "No profile yet — first analysis of this symbol.",
            global_news_section=self._build_global_news_section(global_news),
            news_section=self._build_news_section(news, snap["symbol"]),
            weekly_section=self._build_weekly_section(snap.get("weekly")),
            current=p["current"],
            change_pct=p["change_pct"],
            open=p["open"],
            high=p["high"],
            low=p["low"],
            prev_close=p["prev_close"],
            rsi=v("rsi"),
            rsi_interp=_interpret_rsi(ind.get("rsi")),
            macd=v("macd"),
            macd_signal=v("macd_signal"),
            macd_hist=v("macd_hist"),
            macd_trend="rising ↑" if v("macd_hist") > v("macd_hist_prev") else "falling ↓",
            bb_lower=v("bb_lower"),
            bb_mid=v("bb_mid"),
            bb_upper=v("bb_upper"),
            bb_position=_interpret_bb(p["current"], v("bb_lower"), v("bb_mid"), v("bb_upper")),
            atr=v("atr"),
            sma_20=v("sma_20"),
            above_sma20="ABOVE ↑" if ind.get("above_sma20") else "BELOW ↓",
            sma_50=v("sma_50"),
            above_sma50="ABOVE ↑" if ind.get("above_sma50") else "BELOW ↓",
            sma_200=v("sma_200"),
            above_sma200="ABOVE ↑" if ind.get("above_sma200") else "BELOW ↓",
            trend_desc=_trend_desc(
                ind.get("above_sma20", False),
                ind.get("above_sma50", False),
                ind.get("above_sma200", False),
            ),
            volume=p["volume"],
            vol_sma20=v("vol_sma20"),
            volume_ratio=v("volume_ratio", 1.0),
            volume_interp=_interpret_volume(ind.get("volume_ratio")),
            candles_str=candles_str,
            history_section=self._build_history_context(snap["symbol"], p["current"]),
        )

    # ── News sections ─────────────────────────────────────────────────────────

    @staticmethod
    def _build_news_section(news: list, symbol: str) -> str:
        if not news:
            return f"No recent news for {symbol}."
        lines = []
        for item in news[:8]:
            headline  = item.get("headline", "")
            content   = (item.get("content") or item.get("summary") or "").strip()
            dt        = item.get("datetime", "")
            src       = item.get("source", "")
            sentiment = _news_sentiment(headline)
            line = f"{sentiment} [{dt}] {headline}  ({src})"
            if content and len(content) > 30 and content[:50] != headline[:50]:
                line += f"\n     ↳ {content[:700]}"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _build_global_news_section(global_news: list) -> str:
        if not global_news:
            return "No global macro news available."
        lines = []
        for item in global_news[:10]:
            headline  = item.get("headline", "")
            content   = (item.get("content") or item.get("summary") or "").strip()
            dt        = item.get("datetime", "")
            src       = item.get("source", "")
            sentiment = _news_sentiment(headline)
            line = f"{sentiment} [{dt}] {headline}  ({src})"
            if content and len(content) > 30 and content[:50] != headline[:50]:
                line += f"\n     ↳ {content[:500]}"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _build_weekly_section(weekly: Optional[dict]) -> str:
        if not weekly:
            return "Weekly data unavailable."
        rsi     = weekly.get("rsi")
        rsi_str = f"{rsi:.1f} → {_interpret_rsi(rsi)}" if rsi is not None else "N/A"
        sma10   = weekly.get("sma10")
        sma20   = weekly.get("sma20")
        sma50   = weekly.get("sma50")
        a10 = "ABOVE ↑" if weekly.get("above_sma10") else "BELOW ↓"
        a20 = "ABOVE ↑" if weekly.get("above_sma20") else "BELOW ↓"
        a50 = "ABOVE ↑" if weekly.get("above_sma50") else "BELOW ↓"
        return (
            f"RSI(14w):  {rsi_str}\n"
            f"MACD:      {weekly.get('macd_trend', 'N/A')}\n"
            f"SMA10w:    {'${:.2f}  ({})'.format(sma10, a10) if sma10 else 'N/A'}\n"
            f"SMA20w:    {'${:.2f}  ({})'.format(sma20, a20) if sma20 else 'N/A'}\n"
            f"SMA50w:    {'${:.2f}  ({})'.format(sma50, a50) if sma50 else 'N/A'}\n"
            f"Trend:     {weekly.get('trend', 'N/A')}"
        )

    # ── History context ───────────────────────────────────────────────────────

    def _build_history_context(self, symbol: str, current_price: float) -> str:
        """
        Combines:
        1) Last 8 AI decisions for this symbol (with win/loss outcome estimate)
        2) Last 5 actual executed trades from trades.csv
        """
        decision_section = self._load_decision_history(symbol, current_price)
        trade_section    = self._load_trade_history(symbol)
        return decision_section + ("\n\n" + trade_section if trade_section else "")

    def _load_decision_history(self, symbol: str, current_price: float) -> str:
        if not self._decisions_path.exists():
            return "No decision history yet — this is your first analysis of this symbol."

        records = []
        try:
            with open(self._decisions_path, encoding="utf-8") as f:
                tail = deque(f, maxlen=2000)
            for line in tail:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("symbol") == symbol:
                        records.append(rec)
                except json.JSONDecodeError:
                    pass
        except Exception as exc:
            logger.debug(f"History read failed for {symbol}: {exc}")
            return "History unavailable."

        if not records:
            return "No previous AI decisions for this symbol."

        recent = records[-8:]
        lines  = []
        wins = losses = 0

        for rec in reversed(recent):
            ts     = rec.get("timestamp", "")[:16].replace("T", " ")
            dec    = rec.get("decision", {})
            action = dec.get("action", "HOLD")
            conf   = dec.get("confidence", 0)
            entry  = dec.get("entry_price")
            sl     = dec.get("stop_loss")
            tp     = dec.get("take_profit")

            line = f"  {ts} | {action:4s} | conf={conf:.0%}"

            if action in ("BUY", "SELL") and entry is not None:
                pct = (current_price - entry) / entry * 100
                outcome_pct = pct if action == "BUY" else -pct
                is_win = outcome_pct >= 0
                arrow  = "✓ +{:.1f}%".format(outcome_pct) if is_win else "✗ {:.1f}%".format(outcome_pct)
                line += f" | entry=${entry:.2f}→now=${current_price:.2f} {arrow}"
                if sl:  line += f" SL=${sl:.2f}"
                if tp:  line += f" TP=${tp:.2f}"
                if is_win: wins += 1
                else:      losses += 1
            else:
                line += " | HOLD — no trade"

            signals = dec.get("key_signals", [])
            if signals:
                line += f"\n    ↳ {', '.join(signals[:3])}"
            lines.append(line)

        total = wins + losses
        if total > 0:
            acc = wins / total * 100
            note = ""
            if acc < 40:
                note = " ← Be MORE conservative — current strategy losing."
            elif acc > 70:
                note = " ← Strategy working — maintain current approach."
            perf = f"\n  Accuracy: {wins}W / {losses}L = {acc:.0f}%{note}"
        else:
            perf = "\n  No directional calls yet."

        return "AI Decision History (newest first):\n" + "\n".join(lines) + perf

    def _load_trade_history(self, symbol: str) -> str:
        """Load last 5 actual executed trades from trades.csv."""
        if not self._trades_path.exists():
            return ""
        trades = []
        try:
            with open(self._trades_path, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("symbol") == symbol:
                        trades.append(row)
        except Exception as exc:
            logger.debug(f"Trade history read failed for {symbol}: {exc}")
            return ""

        if not trades:
            return ""

        lines = []
        for t in list(reversed(trades))[:5]:
            ts     = (t.get("timestamp") or "")[:16].replace("T", " ")
            action = t.get("action", "?")
            qty    = t.get("qty", "?")
            price  = t.get("price", "?")
            conf   = t.get("confidence", "?")
            sl     = t.get("stop_loss", "")
            tp     = t.get("take_profit", "")
            extra  = f" SL={sl} TP={tp}" if sl and sl != "0" else ""
            lines.append(f"  {ts} | {action:8s} {qty}x @ ${price} | conf={conf}{extra}")

        return "Actual Executed Trades (newest first):\n" + "\n".join(lines)

    # ── Ollama call ───────────────────────────────────────────────────────────

    def _call_ollama(self, user_prompt: str) -> Optional[str]:
        try:
            # Try modern /api/chat first (Ollama >= 0.1.14)
            payload = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": self._temperature,
                    "num_predict": 512,
                },
            }
            response = requests.post(
                f"{self._base_url}/api/chat",
                json=payload,
                timeout=self._timeout,
            )
            if response.status_code == 404:
                raise requests.HTTPError("404", response=response)
            response.raise_for_status()
            data = response.json()
            return data["message"]["content"]
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                # Fall back to /api/generate (older Ollama versions)
                return self._call_ollama_generate(user_prompt)
            logger.error(f"Ollama call error: {e}", exc_info=True)
        except requests.Timeout:
            logger.error(f"Ollama timeout after {self._timeout}s — model too slow")
        except requests.ConnectionError:
            logger.error("Ollama unavailable — run: ollama serve")
        except Exception as exc:
            logger.error(f"Ollama call error: {exc}", exc_info=True)
        return None

    def _call_ollama_generate(self, user_prompt: str) -> Optional[str]:
        payload = {
            "model": self._model,
            "system": SYSTEM_PROMPT,
            "prompt": user_prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self._temperature,
                "num_predict": 512,
            },
        }
        try:
            response = requests.post(
                f"{self._base_url}/api/generate",
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
            return data["response"]
        except requests.Timeout:
            logger.error(f"Ollama timeout after {self._timeout}s — model too slow")
        except requests.ConnectionError:
            logger.error("Ollama unavailable — run: ollama serve")
        except Exception as exc:
            logger.error(f"Ollama call error: {exc}", exc_info=True)
        return None

    # ── Response parsing ──────────────────────────────────────────────────────

    @staticmethod
    def _repair_json(raw: str) -> str:
        raw = re.sub(r'(["\d\.truefalsn\]l])([ \t]*)\n([ \t]+")', r'\1,\n\3', raw)
        if raw.count("{") > raw.count("}"):
            last_comma = raw.rfind(",")
            last_colon = raw.rfind(":")
            if last_comma > last_colon:
                raw = raw[:last_comma] + "\n}"
            else:
                raw = raw + "}" if last_comma == 0 else raw[:last_comma] + "\n}"
        return raw

    def _parse_response(self, raw: str) -> Optional[dict]:
        raw = raw.strip()
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            raw = match.group(1)
        else:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                raw = match.group(0)

        raw = re.sub(r":\s*\$(\d[\d.,]*)", lambda m: ": " + m.group(1).replace(",", ""), raw)
        raw = self._repair_json(raw)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM: {e}\nResponse: {raw[:300]}")
            return None

        action = str(data.get("action", "HOLD")).upper().strip()
        if action not in ("BUY", "SELL", "HOLD"):
            action = "HOLD"

        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        def safe_float(key):
            val = data.get(key)
            if val is None:
                return None
            try:
                return float(val)
            except (TypeError, ValueError):
                return None

        return {
            "action":      action,
            "confidence":  confidence,
            "entry_price": safe_float("entry_price"),
            "stop_loss":   safe_float("stop_loss"),
            "take_profit": safe_float("take_profit"),
            "reasoning":   str(data.get("reasoning", "")),
            "key_signals": list(data.get("key_signals", [])),
            "news_impact": str(data.get("news_impact", "neutral")).lower(),
        }
