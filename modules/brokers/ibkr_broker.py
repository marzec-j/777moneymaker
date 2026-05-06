"""
Integracja z Interactive Brokers przez ib_insync.
Wymaga uruchomionego TWS lub IB Gateway.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from .base_broker import BaseBroker

logger = logging.getLogger("777moneymaker")


class IBKRBroker(BaseBroker):

    def __init__(self):
        self._host = os.getenv("IBKR_HOST", "127.0.0.1")
        self._port = int(os.getenv("IBKR_PORT", "7497"))   # 7497=paper, 7496=live
        self._client_id = int(os.getenv("IBKR_CLIENT_ID", "1"))
        self._ib = None

    def connect(self) -> bool:
        try:
            import ib_insync
            self._ib = ib_insync.IB()
            self._ib.connect(self._host, self._port, clientId=self._client_id)
            logger.info(
                f"IBKR połączone ({self._host}:{self._port}) "
                f"| {'PAPER' if self._port == 7497 else 'LIVE'}"
            )
            return True
        except ImportError:
            logger.error("Zainstaluj ib_insync: pip install ib_insync")
            return False
        except Exception as exc:
            logger.error(
                f"Błąd połączenia z IBKR ({self._host}:{self._port}): {exc}\n"
                "Upewnij się że TWS lub IB Gateway jest uruchomiony i API jest włączone.",
                exc_info=True,
            )
            return False

    def get_account(self) -> dict:
        try:
            vals = self._ib.accountValues()
            data = {v.tag: v.value for v in vals if v.currency == "USD"}
            return {
                "equity": float(data.get("NetLiquidation", 0)),
                "cash": float(data.get("CashBalance", 0)),
                "buying_power": float(data.get("BuyingPower", 0)),
                "portfolio_value": float(data.get("NetLiquidation", 0)),
            }
        except Exception as exc:
            logger.error(f"Błąd pobierania konta IBKR: {exc}")
            return {"equity": 0, "cash": 0, "buying_power": 0, "portfolio_value": 0}

    def get_positions(self) -> list[dict]:
        try:
            import ib_insync
            self._ib.reqPositions()
            positions = []
            for pos in self._ib.positions():
                positions.append({
                    "symbol": pos.contract.symbol,
                    "qty": float(pos.position),
                    "side": "long" if pos.position > 0 else "short",
                    "avg_entry_price": float(pos.avgCost),
                    "market_value": 0.0,
                    "unrealized_pl": 0.0,
                    "unrealized_plpc": 0.0,
                    "current_price": 0.0,
                })
            return positions
        except Exception as exc:
            logger.error(f"Błąd pobierania pozycji IBKR: {exc}")
            return []

    def get_position(self, symbol: str) -> Optional[dict]:
        positions = self.get_positions()
        for p in positions:
            if p["symbol"] == symbol:
                return p
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
            import ib_insync
            contract = ib_insync.Stock(symbol, "SMART", "USD")
            action = "BUY" if side.lower() == "buy" else "SELL"

            if order_type == "limit" and limit_price:
                order = ib_insync.LimitOrder(action, qty, limit_price)
            else:
                order = ib_insync.MarketOrder(action, qty)

            trade = self._ib.placeOrder(contract, order)
            self._ib.sleep(1)

            order_id = str(trade.order.orderId)
            logger.info(f"IBKR zlecenie: {action} {qty}x {symbol} | ID={order_id}")

            # Pomocnicze zlecenia SL/TP
            if side.lower() == "buy" and stop_loss:
                sl_order = ib_insync.StopOrder("SELL", qty, stop_loss)
                sl_order.parentId = trade.order.orderId
                self._ib.placeOrder(contract, sl_order)

            if side.lower() == "buy" and take_profit:
                tp_order = ib_insync.LimitOrder("SELL", qty, take_profit)
                tp_order.parentId = trade.order.orderId
                self._ib.placeOrder(contract, tp_order)

            return {"order_id": order_id, "symbol": symbol, "qty": qty, "side": side}
        except Exception as exc:
            logger.error(f"Błąd zlecenia IBKR {side} {symbol}: {exc}", exc_info=True)
            return None

    def close_position(self, symbol: str) -> bool:
        try:
            import ib_insync
            pos = self.get_position(symbol)
            if not pos:
                return False
            contract = ib_insync.Stock(symbol, "SMART", "USD")
            qty = abs(int(pos["qty"]))
            action = "SELL" if pos["side"] == "long" else "BUY"
            order = ib_insync.MarketOrder(action, qty)
            self._ib.placeOrder(contract, order)
            logger.info(f"IBKR — zamknięcie pozycji {symbol}")
            return True
        except Exception as exc:
            logger.error(f"Błąd zamknięcia pozycji IBKR {symbol}: {exc}")
            return False

    def cancel_order(self, order_id: str) -> bool:
        logger.warning("Anulowanie zleceń IBKR wymaga ręcznej implementacji przez orderId")
        return False

    def is_market_open(self) -> bool:
        try:
            import ib_insync
            contract = ib_insync.Stock("SPY", "SMART", "USD")
            details = self._ib.reqContractDetails(contract)
            return bool(details)
        except Exception:
            return True
