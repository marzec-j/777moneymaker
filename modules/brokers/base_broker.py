"""
Abstrakcyjna klasa bazowa dla brokerów.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import pandas as pd


class BaseBroker(ABC):

    @abstractmethod
    def connect(self) -> bool:
        """Nawiązuje połączenie. Zwraca True gdy OK."""

    @abstractmethod
    def get_account(self) -> dict:
        """Zwraca informacje o koncie: equity, cash, buying_power."""

    @abstractmethod
    def get_positions(self) -> list[dict]:
        """Zwraca listę otwartych pozycji."""

    @abstractmethod
    def get_position(self, symbol: str) -> Optional[dict]:
        """Zwraca pozycję dla danego symbolu lub None."""

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        qty: int,
        side: str,           # "buy" | "sell"
        order_type: str,     # "market" | "limit"
        limit_price: Optional[float],
        stop_loss: Optional[float],
        take_profit: Optional[float],
    ) -> Optional[dict]:
        """Składa zlecenie. Zwraca dane zamówienia lub None przy błędzie."""

    @abstractmethod
    def close_position(self, symbol: str) -> bool:
        """Zamyka pozycję dla symbolu. Zwraca True gdy OK."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Anuluje zlecenie. Zwraca True gdy OK."""

    def is_market_open(self) -> bool:
        """Opcjonalne — sprawdza czy rynek jest otwarty."""
        return True

    def get_all_assets(self) -> list[str]:
        """Opcjonalne — zwraca wszystkie aktywne handlowalne symbole."""
        return []

    @abstractmethod
    def get_bars(
        self,
        symbol: str,
        timeframe: str,      # "1d" | "1wk"
        start: datetime,
        end: datetime,
    ) -> Optional[pd.DataFrame]:
        """
        Returns OHLCV DataFrame with columns Open, High, Low, Close, Volume,
        sorted ascending by date. Returns None on failure.
        """

    @abstractmethod
    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Returns the most recent price for SL/TP checks. Returns None on failure."""
