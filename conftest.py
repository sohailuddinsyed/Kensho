"""
conftest.py — Shared pytest fixtures for the Kensho test suite.

All agent integration tests must use mock_anthropic_model so no real
Anthropic API key is required to run the test suite.
"""

import time
import pytest
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# SessionContext dataclass (mirrors agents/orchestrator.py definition)
# ---------------------------------------------------------------------------

@dataclass
class SessionContext:
    user_id: str
    investor_profile: dict
    live_portfolio: list[dict]
    sector_allocations: dict[str, float]
    cache_age_seconds: int
    cache_is_stale: bool
    language: str  # "en" | "hi"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_investor_profile() -> dict:
    """
    Complete investor profile dict including all required fields.
    Includes panic_drop_threshold_pct and volume_spike_multiplier as
    configurable values (not hardcoded defaults).
    """
    return {
        "user_id": "whatsapp:+919876543210",
        "full_name": "Test Investor",
        "trading_style": "positional",
        "risk_tolerance": "moderate",
        "preferred_sectors": ["Banking", "IT", "Pharma"],
        "max_position_pct": 0.10,           # 10% of portfolio per position
        "max_sector_concentration_pct": 0.30,  # 30% max per sector
        "stop_loss_style": "percentage",
        "watchlist_tickers": ["HDFCBANK.NS", "INFY.NS", "SUNPHARMA.NS"],
        "portfolio_size_band": "10L-50L",
        "language_preference": "en",
        "panic_drop_threshold_pct": 3.0,    # configurable, not hardcoded
        "volume_spike_multiplier": 2.0,     # configurable, not hardcoded
        "stop_loss_levels": {
            "RELIANCE.NS": 2400.0,
            "TCS.NS": 3500.0,
            "HDFCBANK.NS": 1550.0,
        },
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-15T10:00:00",
    }


@pytest.fixture
def mock_iifl_portfolio() -> list[dict]:
    """
    Fixed list of holdings with prices and P&L for use in tests.
    Covers multiple sectors to enable sector concentration tests.
    """
    return [
        {
            "ticker": "RELIANCE.NS",
            "qty": 50,
            "avg_buy_price": 2350.00,
            "live_price": 2480.00,
            "pnl_rupees": 6500.00,
            "pnl_pct": 5.53,
            "sector": "Energy",
        },
        {
            "ticker": "TCS.NS",
            "qty": 30,
            "avg_buy_price": 3600.00,
            "live_price": 3520.00,
            "pnl_rupees": -2400.00,
            "pnl_pct": -2.22,
            "sector": "IT",
        },
        {
            "ticker": "HDFCBANK.NS",
            "qty": 100,
            "avg_buy_price": 1580.00,
            "live_price": 1620.00,
            "pnl_rupees": 4000.00,
            "pnl_pct": 2.53,
            "sector": "Banking",
        },
        {
            "ticker": "SUNPHARMA.NS",
            "qty": 40,
            "avg_buy_price": 1100.00,
            "live_price": 1145.00,
            "pnl_rupees": 1800.00,
            "pnl_pct": 4.09,
            "sector": "Pharma",
        },
        {
            "ticker": "MARUTI.NS",
            "qty": 10,
            "avg_buy_price": 10200.00,
            "live_price": 10050.00,
            "pnl_rupees": -1500.00,
            "pnl_pct": -1.47,
            "sector": "Auto",
        },
    ]


@pytest.fixture
def mock_session_context(mock_investor_profile, mock_iifl_portfolio) -> SessionContext:
    """
    Fully populated SessionContext dataclass with test data.
    Uses mock_investor_profile and mock_iifl_portfolio fixtures.
    """
    return SessionContext(
        user_id="whatsapp:+919876543210",
        investor_profile=mock_investor_profile,
        live_portfolio=mock_iifl_portfolio,
        sector_allocations={
            "Energy": 0.28,
            "IT": 0.24,
            "Banking": 0.36,
            "Pharma": 0.10,
            "Auto": 0.02,
        },
        cache_age_seconds=120,
        cache_is_stale=False,
        language="en",
    )


@pytest.fixture
def mock_anthropic_model(monkeypatch):
    """
    Patches AnthropicModel to return pre-defined response dicts without
    making real API calls. All agent integration tests must use this fixture.

    The mock agent callable returns a MagicMock whose .message attribute
    contains a pre-defined text response, and whose string representation
    is a JSON-serialisable analysis stub.
    """
    mock_response = MagicMock()
    mock_response.message = "Mock analysis response from Claude."
    mock_response.__str__ = lambda self: (
        '{"analysis": "mock", "confidence": "HIGH", '
        '"disclaimer": "This is research assistance only. Not financial advice. '
        'Past performance does not guarantee future results."}'
    )

    mock_agent_instance = MagicMock()
    mock_agent_instance.return_value = mock_response
    mock_agent_instance.__call__ = lambda self, *args, **kwargs: mock_response

    mock_model_cls = MagicMock()
    mock_model_cls.return_value = MagicMock()

    mock_agent_cls = MagicMock()
    mock_agent_cls.return_value = mock_agent_instance

    monkeypatch.setattr("strands.models.anthropic.AnthropicModel", mock_model_cls)
    monkeypatch.setattr("strands.Agent", mock_agent_cls)

    return mock_agent_instance


@pytest.fixture
def cold_start_timer():
    """
    Context manager fixture that asserts Lambda initialisation including
    FAISS index load completes in under 10 seconds (Requirement 24.3).

    Usage:
        def test_cold_start(cold_start_timer):
            with cold_start_timer:
                # perform cold-start initialisation (e.g. load FAISS index)
                ...
    """
    class _ColdStartTimer:
        def __enter__(self):
            self._start = time.perf_counter()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            elapsed = time.perf_counter() - self._start
            assert elapsed < 10.0, (
                f"Cold start exceeded 10-second budget: {elapsed:.2f}s "
                "(Requirement 24.1, 24.3)"
            )
            return False  # do not suppress exceptions

    return _ColdStartTimer()
