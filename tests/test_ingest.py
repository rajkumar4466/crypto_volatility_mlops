"""
CoinGecko ingest tests.

Guards against silent NaN propagation from the data source.
Null fields in raw candle data must raise ValueError immediately,
never be passed downstream into features.
"""
import pytest
from unittest.mock import patch, MagicMock

from src.ingestion.coingecko import fetch_ohlcv


def test_fetch_raises_on_null():
    """
    If CoinGecko returns a candle row with any null field,
    fetch_ohlcv() must raise ValueError immediately.
    Null fields must never silently become NaN features downstream.
    """
    # Simulated response: second candle has a null close price
    mock_candles = [
        [1_000_000, 45000.0, 45100.0, 44900.0, 45000.0, 1000.0],
        [1_060_000, 45010.0, 45110.0, 44910.0, None, 1010.0],  # null close
        [1_120_000, 45020.0, 45120.0, 44920.0, 45020.0, 1020.0],
    ]

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = mock_candles

    with patch("src.ingestion.coingecko.requests.get", return_value=mock_response):
        with pytest.raises(ValueError, match="Null value"):
            fetch_ohlcv(days=0.1)
