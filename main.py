"""
777moneymaker — AI Trading System
==================================
Lokalny LLM (Ollama) + broker API = automatyczny trading krótkoterminowy.

Uruchomienie:
    python main.py                              # live trading (config.yaml)
    python main.py --paper                      # paper broker (symulator)
    python main.py --once                       # jeden cykl i wyjście
    python main.py --check                      # sprawdź połączenia i wyjdź
    python main.py --symbol AAPL                # analizuj tylko jeden symbol
    python main.py --backtest --from 2024-01-01 --to 2024-06-30   # backtest
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from datetime import date, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()


def load_config(path: str = "config.yaml") -> dict:
    cfg_path = Path(path)
    if not cfg_path.exists():
        print(f"[BŁĄD] Nie znaleziono pliku konfiguracyjnego: {path}")
        sys.exit(1)
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_broker(config: dict, force_paper: bool = False):
    from modules.brokers.alpaca_broker import AlpacaBroker
    mode = "paper" if force_paper else config.get("alpaca_mode", "paper")
    return AlpacaBroker(mode=mode)


def check_connections(broker, llm, config: dict) -> bool:
    from modules.trade_logger import setup_logger
    logger = setup_logger(config)
    all_ok = True

    logger.info("Sprawdzanie połączeń...")

    if llm.is_available():
        logger.info(f"[OK] Ollama available ({config['llm']['base_url']})")
        logger.info(f"     Model: {config['llm']['model']}")
    else:
        logger.error(
            "[ERROR] Ollama unavailable!\n"
            "  1. Install: https://ollama.ai\n"
            "  2. Run: ollama serve\n"
            f"  3. Pull model: ollama pull {config['llm']['model']}"
        )
        all_ok = False

    if broker.connect():
        logger.info("[OK] Broker connected")
        acc = broker.get_account()
        logger.info(f"     Equity: ${acc.get('equity', 0):,.2f}")
    else:
        logger.error("[ERROR] Broker unavailable — check .env and configuration")
        all_ok = False

    return all_ok


def main():
    parser = argparse.ArgumentParser(
        description="777moneymaker — AI Trading System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--paper", action="store_true", help="force Alpaca paper trading mode")
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    parser.add_argument("--check", action="store_true", help="check connections and exit")
    parser.add_argument("--symbol", help="analyze only this symbol (e.g. AAPL)")
    parser.add_argument("--backtest", action="store_true", help="run backtest on historical data")
    parser.add_argument("--from", dest="date_from", help="backtest start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to", help="backtest end date (YYYY-MM-DD), default: today")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.symbol:
        config["symbols"] = [args.symbol.upper()]

    from modules.trade_logger import TradeLogger, setup_logger
    from modules.market_data import MarketDataFetcher
    from modules.llm_analyzer import LLMAnalyzer
    from modules.risk_manager import RiskManager
    from modules.trading_engine import TradingEngine

    logger = setup_logger(config)
    logger.info("=" * 60)
    logger.info("  777moneymaker — AI Trading System")
    logger.info("=" * 60)

    llm = LLMAnalyzer(config)
    data = MarketDataFetcher(config)
    risk = RiskManager(config)
    trade_log = TradeLogger(config)

    # ── Backtest mode ──────────────────────────────────────────────
    if args.backtest:
        if not args.date_from:
            print("[ERROR] --backtest requires --from YYYY-MM-DD")
            sys.exit(1)
        try:
            start_date = datetime.strptime(args.date_from, "%Y-%m-%d").date()
            end_date = (
                datetime.strptime(args.date_to, "%Y-%m-%d").date()
                if args.date_to
                else date.today()
            )
        except ValueError as e:
            print(f"[ERROR] Invalid date format: {e}")
            sys.exit(1)

        if not llm.is_available():
            logger.error("Ollama unavailable — backtest requires LLM. Run: ollama serve")
            sys.exit(1)

        from modules.backtester import BacktestEngine
        engine = BacktestEngine(config, data, llm, risk, start_date, end_date)
        engine.run()
        sys.exit(0)

    # ── Live / paper mode ──────────────────────────────────────────
    broker = build_broker(config, force_paper=args.paper)


    if args.check:
        ok = check_connections(broker, llm, config)
        sys.exit(0 if ok else 1)

    if not llm.is_available():
        logger.warning(
            "Ollama unavailable! Run: ollama serve\n"
            f"Pull model: ollama pull {config['llm']['model']}\n"
            "Program continues but trades will NOT be executed."
        )

    if not broker.connect():
        logger.error("Cannot connect to broker. Check .env")
        sys.exit(1)

    finnhub = None
    try:
        if os.getenv("FINNHUB_API_KEY", ""):
            from modules.finnhub_client import FinnhubClient
            finnhub = FinnhubClient()
            if finnhub.is_available():
                logger.info("Finnhub connected — news will be used by AI")
            else:
                finnhub = None
        else:
            logger.info("FINNHUB_API_KEY not set — news disabled")
    except Exception as exc:
        logger.warning(f"Finnhub init error: {exc}")

    engine = TradingEngine(config, broker, data, llm, risk, trade_log, finnhub=finnhub)

    _running = [True]

    def _shutdown(sig, frame):
        logger.info("Shutdown signal received — finishing current loop...")
        _running[0] = False

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    interval = config.get("loop_interval", 60)
    alpaca_mode = "paper" if args.paper else config.get("alpaca_mode", "paper")
    logger.info(
        f"Start | Broker: Alpaca ({alpaca_mode.upper()}) | "
        f"Model: {config['llm']['model']} | "
        f"Interval: {interval}s | "
        f"Symbols: {', '.join(config['symbols'])}"
    )
    logger.info("Press Ctrl+C to stop")

    while _running[0]:
        try:
            engine.run_cycle()
        except KeyboardInterrupt:
            break
        except Exception as exc:
            trade_log.log_error("Error in main cycle", exc)

        if args.once:
            logger.info("--once mode: finished after one cycle")
            break

        if _running[0]:
            logger.info(f"Next cycle in {interval}s... (Ctrl+C to stop)")
            for _ in range(interval):
                if not _running[0]:
                    break
                time.sleep(1)

    logger.info("777moneymaker stopped. Goodbye!")


if __name__ == "__main__":
    main()
