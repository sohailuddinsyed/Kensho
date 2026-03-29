"""
tests/test_tools/test_dynamo.py — Unit tests for tools/dynamo.py.

All DynamoDB calls are mocked with moto.
Dummy AWS credentials and region are set at module level so boto3 never
attempts a real network call. Each test is decorated with @mock_aws and
calls _create_all_tables() to set up the in-memory tables.
"""

import os
import time
from decimal import Decimal
import pytest
import boto3
from moto import mock_aws

# Must be set before any boto3/tools import so the client is always local
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")

import tools.dynamo as dynamo_module
from tools.dynamo import (
    ONBOARDING_SESSION_TTL_SECONDS,
    PANIC_COOLDOWN_SESSION_TTL_SECONDS,
    get_investor_profile,
    put_investor_profile,
    get_session_state,
    put_session_state,
    get_trade_journal_entries,
    put_trade_journal_entry,
    get_embeddings_metadata,
    put_embeddings_metadata,
    get_watchlist_alerts,
    put_watchlist_alert,
    get_news_cache,
    put_news_cache,
    put_report,
    get_reports,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_all_tables():
    """Create all 7 DynamoDB tables. Must be called inside an active @mock_aws test."""
    client = boto3.client("dynamodb", region_name="us-east-1")

    client.create_table(
        TableName="investor_profile",
        KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    client.create_table(
        TableName="session_state",
        KeySchema=[
            {"AttributeName": "user_id", "KeyType": "HASH"},
            {"AttributeName": "session_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "session_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    client.create_table(
        TableName="trade_journal",
        KeySchema=[
            {"AttributeName": "user_id", "KeyType": "HASH"},
            {"AttributeName": "trade_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "trade_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    client.create_table(
        TableName="embeddings_metadata",
        KeySchema=[{"AttributeName": "embedding_id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "embedding_id", "AttributeType": "S"}
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    client.create_table(
        TableName="watchlist_alerts",
        KeySchema=[
            {"AttributeName": "user_id", "KeyType": "HASH"},
            {"AttributeName": "alert_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "alert_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    client.create_table(
        TableName="news_cache",
        KeySchema=[
            {"AttributeName": "ticker", "KeyType": "HASH"},
            {"AttributeName": "fetched_at", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "ticker", "AttributeType": "S"},
            {"AttributeName": "fetched_at", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    client.create_table(
        TableName="reports",
        KeySchema=[
            {"AttributeName": "user_id", "KeyType": "HASH"},
            {"AttributeName": "report_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "report_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    # Reset the cached resource so the module picks up the moto-patched one
    dynamo_module._dynamodb = None


# ---------------------------------------------------------------------------
# TTL constants
# ---------------------------------------------------------------------------

def test_ttl_constants_values():
    assert ONBOARDING_SESSION_TTL_SECONDS == 1800
    assert PANIC_COOLDOWN_SESSION_TTL_SECONDS == 300


def test_ttl_constants_are_not_equal():
    assert ONBOARDING_SESSION_TTL_SECONDS != PANIC_COOLDOWN_SESSION_TTL_SECONDS


# ---------------------------------------------------------------------------
# investor_profile
# ---------------------------------------------------------------------------

@mock_aws
def test_get_investor_profile_returns_none_when_missing():
    _create_all_tables()
    result = get_investor_profile("whatsapp:+919999999999")
    assert result is None


@mock_aws
def test_put_and_get_investor_profile_round_trip():
    _create_all_tables()
    user_id = "whatsapp:+919876543210"
    profile = {
        "full_name": "Test User",
        "trading_style": "positional",
        "risk_tolerance": "medium",
        "max_position_pct": Decimal("0.1"),
        "panic_drop_threshold_pct": Decimal("3.0"),
        "volume_spike_multiplier": Decimal("2.0"),
    }
    put_investor_profile(user_id, profile)
    result = get_investor_profile(user_id)

    assert result is not None
    assert result["user_id"] == user_id
    assert result["full_name"] == "Test User"
    assert result["max_position_pct"] == Decimal("0.1")


@mock_aws
def test_put_investor_profile_overwrites_existing():
    _create_all_tables()
    user_id = "whatsapp:+911111111111"
    put_investor_profile(user_id, {"full_name": "Old Name"})
    put_investor_profile(user_id, {"full_name": "New Name"})
    result = get_investor_profile(user_id)
    assert result["full_name"] == "New Name"


@mock_aws
def test_investor_profiles_are_isolated_by_user_id():
    _create_all_tables()
    put_investor_profile("user_a", {"full_name": "Alice"})
    put_investor_profile("user_b", {"full_name": "Bob"})
    assert get_investor_profile("user_a")["full_name"] == "Alice"
    assert get_investor_profile("user_b")["full_name"] == "Bob"


# ---------------------------------------------------------------------------
# session_state
# ---------------------------------------------------------------------------

@mock_aws
def test_get_session_state_returns_none_when_missing():
    _create_all_tables()
    result = get_session_state("user_x", "session_x")
    assert result is None


@mock_aws
def test_put_and_get_session_state_round_trip():
    _create_all_tables()
    user_id = "whatsapp:+919876543210"
    session_id = "sess-uuid-001"
    data = {"session_type": "onboarding", "step": 2}

    put_session_state(user_id, session_id, data, ONBOARDING_SESSION_TTL_SECONDS)
    result = get_session_state(user_id, session_id)

    assert result is not None
    assert result["session_type"] == "onboarding"
    assert result["step"] == 2


@mock_aws
def test_put_session_state_sets_expires_at_for_onboarding():
    _create_all_tables()
    user_id = "whatsapp:+919876543210"
    session_id = "sess-uuid-002"
    before = int(time.time())

    put_session_state(user_id, session_id, {}, ONBOARDING_SESSION_TTL_SECONDS)
    result = get_session_state(user_id, session_id)

    after = int(time.time())
    expires_at = int(result["expires_at"])
    assert before + ONBOARDING_SESSION_TTL_SECONDS <= expires_at <= after + ONBOARDING_SESSION_TTL_SECONDS


@mock_aws
def test_put_session_state_sets_expires_at_for_panic_cooldown():
    _create_all_tables()
    user_id = "whatsapp:+919876543210"
    session_id = "sess-panic-001"
    before = int(time.time())

    put_session_state(user_id, session_id, {"session_type": "panic_cooldown"}, PANIC_COOLDOWN_SESSION_TTL_SECONDS)
    result = get_session_state(user_id, session_id)

    after = int(time.time())
    expires_at = int(result["expires_at"])
    assert before + PANIC_COOLDOWN_SESSION_TTL_SECONDS <= expires_at <= after + PANIC_COOLDOWN_SESSION_TTL_SECONDS


# ---------------------------------------------------------------------------
# trade_journal
# ---------------------------------------------------------------------------

@mock_aws
def test_get_trade_journal_entries_returns_empty_list():
    _create_all_tables()
    result = get_trade_journal_entries("new_user")
    assert result == []


@mock_aws
def test_put_and_get_trade_journal_entry():
    _create_all_tables()
    user_id = "whatsapp:+919876543210"
    trade_id = "uuid1_2024-01-15T10:30:00"
    entry = {
        "stock": "RELIANCE.NS",
        "entry_price": Decimal("2500.0"),
        "thesis": "Breakout above resistance",
        "outcome": "win",
    }

    put_trade_journal_entry(user_id, trade_id, entry)
    results = get_trade_journal_entries(user_id)

    assert len(results) == 1
    assert results[0]["trade_id"] == trade_id
    assert results[0]["stock"] == "RELIANCE.NS"


@mock_aws
def test_get_trade_journal_entries_respects_limit():
    _create_all_tables()
    user_id = "whatsapp:+919876543210"
    for i in range(5):
        put_trade_journal_entry(user_id, f"trade_{i:03d}", {"stock": f"STOCK{i}.NS"})

    results = get_trade_journal_entries(user_id, limit=3)
    assert len(results) <= 3


@mock_aws
def test_trade_journal_entries_isolated_by_user():
    _create_all_tables()
    put_trade_journal_entry("user_a", "trade_a1", {"stock": "INFY.NS"})
    put_trade_journal_entry("user_b", "trade_b1", {"stock": "TCS.NS"})

    assert len(get_trade_journal_entries("user_a")) == 1
    assert get_trade_journal_entries("user_a")[0]["stock"] == "INFY.NS"


# ---------------------------------------------------------------------------
# embeddings_metadata
# ---------------------------------------------------------------------------

@mock_aws
def test_get_embeddings_metadata_returns_none_when_missing():
    _create_all_tables()
    result = get_embeddings_metadata("nonexistent-uuid")
    assert result is None


@mock_aws
def test_put_and_get_embeddings_metadata_round_trip():
    _create_all_tables()
    embedding_id = "emb-uuid-001"
    metadata = {
        "ticker": "RELIANCE.NS",
        "source_type": "price_chunk",
        "chunk_text": "Jan 2024 price data",
        "vector": [Decimal("0.1"), Decimal("0.2"), Decimal("0.3")],
    }

    put_embeddings_metadata(embedding_id, metadata)
    result = get_embeddings_metadata(embedding_id)

    assert result is not None
    assert result["embedding_id"] == embedding_id
    assert result["ticker"] == "RELIANCE.NS"
    assert result["vector"] == [Decimal("0.1"), Decimal("0.2"), Decimal("0.3")]


# ---------------------------------------------------------------------------
# watchlist_alerts
# ---------------------------------------------------------------------------

@mock_aws
def test_get_watchlist_alerts_returns_empty_list():
    _create_all_tables()
    result = get_watchlist_alerts("new_user")
    assert result == []


@mock_aws
def test_put_and_get_watchlist_alert():
    _create_all_tables()
    user_id = "whatsapp:+919876543210"
    alert_id = "alert-uuid-001"
    alert = {
        "ticker": "INFY.NS",
        "alert_type": "stop_loss",
        "stop_loss_price": Decimal("1400.0"),
    }

    put_watchlist_alert(user_id, alert_id, alert)
    results = get_watchlist_alerts(user_id)

    assert len(results) == 1
    assert results[0]["alert_id"] == alert_id
    assert results[0]["ticker"] == "INFY.NS"


@mock_aws
def test_watchlist_alerts_isolated_by_user():
    _create_all_tables()
    put_watchlist_alert("user_a", "alert_a1", {"ticker": "INFY.NS"})
    put_watchlist_alert("user_b", "alert_b1", {"ticker": "TCS.NS"})

    assert len(get_watchlist_alerts("user_a")) == 1
    assert len(get_watchlist_alerts("user_b")) == 1


# ---------------------------------------------------------------------------
# news_cache
# ---------------------------------------------------------------------------

@mock_aws
def test_put_news_cache_stores_record():
    _create_all_tables()
    ticker = "RELIANCE.NS"
    fetched_at = "2024-01-15T18:30:00"
    articles = [{"title": "Reliance Q3 results", "sentiment": "positive"}]

    put_news_cache(ticker, fetched_at, articles)

    resource = boto3.resource("dynamodb", region_name="us-east-1")
    item = resource.Table("news_cache").get_item(
        Key={"ticker": ticker, "fetched_at": fetched_at}
    )["Item"]

    assert item["ticker"] == ticker
    assert len(item["articles"]) == 1


@mock_aws
def test_put_news_cache_sets_ttl():
    _create_all_tables()
    ticker = "TCS.NS"
    fetched_at = "2024-01-15T18:30:00"
    before = int(time.time())

    put_news_cache(ticker, fetched_at, [], ttl_hours=36)

    resource = boto3.resource("dynamodb", region_name="us-east-1")
    item = resource.Table("news_cache").get_item(
        Key={"ticker": ticker, "fetched_at": fetched_at}
    )["Item"]

    after = int(time.time())
    ttl = int(item["ttl"])
    assert before + 36 * 3600 <= ttl <= after + 36 * 3600


@mock_aws
def test_get_news_cache_returns_list():
    _create_all_tables()
    ticker = "INFY.NS"
    fetched_at = "2024-01-15T18:30:00"
    articles = [{"title": "Infosys wins deal", "sentiment": "positive"}]

    put_news_cache(ticker, fetched_at, articles, ttl_hours=36)
    results = get_news_cache(ticker, max_age_hours=12)

    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------

@mock_aws
def test_get_reports_returns_empty_list():
    _create_all_tables()
    result = get_reports("new_user")
    assert result == []


@mock_aws
def test_put_and_get_report_round_trip():
    _create_all_tables()
    user_id = "whatsapp:+919876543210"
    report_id = "report-uuid-001"
    report = {
        "report_type": "full",
        "ticker": "RELIANCE.NS",
        "full_report_text": "Detailed analysis...",
        "whatsapp_text": "Short summary...",
        "confidence_level": "HIGH",
    }

    put_report(user_id, report_id, report)
    results = get_reports(user_id)

    assert len(results) == 1
    assert results[0]["report_id"] == report_id
    assert results[0]["report_type"] == "full"
    assert results[0]["confidence_level"] == "HIGH"


@mock_aws
def test_get_reports_respects_limit():
    _create_all_tables()
    user_id = "whatsapp:+919876543210"
    for i in range(5):
        put_report(user_id, f"report_{i:03d}", {"report_type": "full"})

    results = get_reports(user_id, limit=3)
    assert len(results) <= 3


@mock_aws
def test_reports_isolated_by_user():
    _create_all_tables()
    put_report("user_a", "rep_a1", {"report_type": "morning"})
    put_report("user_b", "rep_b1", {"report_type": "digest"})

    assert len(get_reports("user_a")) == 1
    assert get_reports("user_a")[0]["report_type"] == "morning"
