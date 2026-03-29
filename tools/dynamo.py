"""
tools/dynamo.py — DynamoDB CRUD helpers for all Kensho tables.

All functions accept user_id as an explicit parameter.
No global USER_ID constant is permitted anywhere in this module.
"""

import time
import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

# TTL constants (seconds) — used when writing session_state records
ONBOARDING_SESSION_TTL_SECONDS = 1800       # 30 minutes
PANIC_COOLDOWN_SESSION_TTL_SECONDS = 300    # 5 minutes

_dynamodb = None


def _get_resource():
    """Lazy-initialise the DynamoDB resource (allows moto to patch it in tests)."""
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb


def _table(name: str):
    return _get_resource().Table(name)


# ---------------------------------------------------------------------------
# investor_profile  (PK: user_id)
# ---------------------------------------------------------------------------

def get_investor_profile(user_id: str) -> dict | None:
    """
    Retrieve the investor profile for the given user_id.

    Args:
        user_id: WhatsApp number used as the DynamoDB partition key.

    Returns:
        Profile dict if found, None otherwise.
    """
    response = _table("investor_profile").get_item(Key={"user_id": user_id})
    return response.get("Item")


def put_investor_profile(user_id: str, profile: dict) -> None:
    """
    Write or overwrite the investor profile for the given user_id.

    Args:
        user_id: WhatsApp number used as the DynamoDB partition key.
        profile: Full profile dict to persist.
    """
    item = {"user_id": user_id, **profile}
    _table("investor_profile").put_item(Item=item)


# ---------------------------------------------------------------------------
# session_state  (PK: user_id, SK: session_id, TTL: expires_at)
# ---------------------------------------------------------------------------

def get_session_state(user_id: str, session_id: str) -> dict | None:
    """
    Retrieve a session state record.

    Args:
        user_id: Partition key.
        session_id: Sort key (UUID).

    Returns:
        Session state dict if found and not expired, None otherwise.
    """
    response = _table("session_state").get_item(
        Key={"user_id": user_id, "session_id": session_id}
    )
    return response.get("Item")


def put_session_state(
    user_id: str, session_id: str, data: dict, ttl_seconds: int
) -> None:
    """
    Write a session state record with a TTL.

    Use ONBOARDING_SESSION_TTL_SECONDS or PANIC_COOLDOWN_SESSION_TTL_SECONDS
    as the ttl_seconds argument — analysis flows must NOT create session records.

    Args:
        user_id: Partition key.
        session_id: Sort key (UUID).
        data: Arbitrary state payload to persist.
        ttl_seconds: Seconds from now until DynamoDB auto-expires the record.
    """
    expires_at = int(time.time()) + ttl_seconds
    item = {
        "user_id": user_id,
        "session_id": session_id,
        "expires_at": expires_at,
        **data,
    }
    _table("session_state").put_item(Item=item)


# ---------------------------------------------------------------------------
# trade_journal  (PK: user_id, SK: trade_id)
# ---------------------------------------------------------------------------

def get_trade_journal_entries(user_id: str, limit: int = 50) -> list[dict]:
    """
    Retrieve the most recent trade journal entries for a user.

    Args:
        user_id: Partition key.
        limit: Maximum number of entries to return (default 50).

    Returns:
        List of trade journal entry dicts, ordered by sort key descending.
    """
    response = _table("trade_journal").query(
        KeyConditionExpression=Key("user_id").eq(user_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    return response.get("Items", [])


def put_trade_journal_entry(user_id: str, trade_id: str, entry: dict) -> None:
    """
    Write a trade journal entry.

    Args:
        user_id: Partition key.
        trade_id: Sort key (UUID + ISO timestamp).
        entry: Trade record dict.
    """
    item = {"user_id": user_id, "trade_id": trade_id, **entry}
    _table("trade_journal").put_item(Item=item)


# ---------------------------------------------------------------------------
# embeddings_metadata  (PK: embedding_id)
# ---------------------------------------------------------------------------

def get_embeddings_metadata(embedding_id: str) -> dict | None:
    """
    Retrieve an embeddings metadata record by its embedding_id.

    Args:
        embedding_id: UUID partition key.

    Returns:
        Metadata dict if found, None otherwise.
    """
    response = _table("embeddings_metadata").get_item(
        Key={"embedding_id": embedding_id}
    )
    return response.get("Item")


def put_embeddings_metadata(embedding_id: str, metadata: dict) -> None:
    """
    Write an embeddings metadata record.

    Args:
        embedding_id: UUID partition key.
        metadata: Dict containing ticker, source_type, chunk_text, vector, etc.
    """
    item = {"embedding_id": embedding_id, **metadata}
    _table("embeddings_metadata").put_item(Item=item)


# ---------------------------------------------------------------------------
# watchlist_alerts  (PK: user_id, SK: alert_id)
# ---------------------------------------------------------------------------

def get_watchlist_alerts(user_id: str) -> list[dict]:
    """
    Retrieve all watchlist alert records for a user.

    Args:
        user_id: Partition key.

    Returns:
        List of alert dicts.
    """
    response = _table("watchlist_alerts").query(
        KeyConditionExpression=Key("user_id").eq(user_id)
    )
    return response.get("Items", [])


def put_watchlist_alert(user_id: str, alert_id: str, alert: dict) -> None:
    """
    Write or update a watchlist alert record.

    Args:
        user_id: Partition key.
        alert_id: Sort key (UUID).
        alert: Alert dict (ticker, alert_type, stop_loss_price, last_triggered_at, etc.).
    """
    item = {"user_id": user_id, "alert_id": alert_id, **alert}
    _table("watchlist_alerts").put_item(Item=item)


# ---------------------------------------------------------------------------
# news_cache  (PK: ticker, SK: fetched_at, TTL: ttl)
# ---------------------------------------------------------------------------

def get_news_cache(ticker: str, max_age_hours: int = 12) -> list[dict]:
    """
    Retrieve cached news articles for a ticker within the given age window.

    Args:
        ticker: NSE ticker string (e.g. "RELIANCE.NS").
        max_age_hours: Only return records fetched within this many hours (default 12).

    Returns:
        List of news cache item dicts, each containing an `articles` list.
    """
    cutoff_ts = int(time.time()) - (max_age_hours * 3600)
    # fetched_at is stored as ISO string; use a numeric epoch SK for range queries
    # The table SK is a string ISO timestamp — filter client-side after query
    response = _table("news_cache").query(
        KeyConditionExpression=Key("ticker").eq(ticker)
    )
    items = response.get("Items", [])
    # Filter to only items within the age window using the ttl field
    cutoff_epoch = int(time.time()) - (max_age_hours * 3600)
    return [
        item for item in items
        if int(item.get("ttl", 0)) > cutoff_epoch + (36 * 3600 - max_age_hours * 3600)
    ]


def put_news_cache(
    ticker: str, fetched_at: str, articles: list[dict], ttl_hours: int = 36
) -> None:
    """
    Write a news cache record with a TTL.

    Args:
        ticker: NSE ticker string — partition key.
        fetched_at: ISO timestamp string — sort key.
        articles: List of article dicts to cache.
        ttl_hours: Hours until DynamoDB auto-expires the record (default 36).
    """
    ttl = int(time.time()) + (ttl_hours * 3600)
    item = {
        "ticker": ticker,
        "fetched_at": fetched_at,
        "articles": articles,
        "ttl": ttl,
    }
    _table("news_cache").put_item(Item=item)


# ---------------------------------------------------------------------------
# reports  (PK: user_id, SK: report_id)
# ---------------------------------------------------------------------------

def put_report(user_id: str, report_id: str, report: dict) -> None:
    """
    Write a report record to the reports table.

    Args:
        user_id: Partition key.
        report_id: Sort key (UUID).
        report: Report dict containing report_type, full_report_text, whatsapp_text, etc.
    """
    item = {"user_id": user_id, "report_id": report_id, **report}
    _table("reports").put_item(Item=item)


def get_reports(user_id: str, limit: int = 50) -> list[dict]:
    """
    Retrieve the most recent reports for a user.

    Args:
        user_id: Partition key.
        limit: Maximum number of reports to return (default 50).

    Returns:
        List of report dicts, ordered by sort key descending.
    """
    response = _table("reports").query(
        KeyConditionExpression=Key("user_id").eq(user_id),
        ScanIndexForward=False,
        Limit=limit,
    )
    return response.get("Items", [])
