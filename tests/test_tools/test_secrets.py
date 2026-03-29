"""
tests/test_tools/test_secrets.py — Unit tests for tools/secrets.py.

All Secrets Manager calls are mocked with moto.
Dummy AWS credentials and region are set at module level.
"""

import os
import json
import pytest
import boto3
from moto import mock_aws

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")


def _create_secret(name: str, value):
    client = boto3.client("secretsmanager", region_name="us-east-1")
    secret_string = value if isinstance(value, str) else json.dumps(value)
    client.create_secret(Name=name, SecretString=secret_string)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@mock_aws
def test_get_secret_returns_parsed_dict():
    from tools.secrets import get_secret
    payload = {"api_key": "test-key-123", "secret": "test-secret-456"}
    _create_secret("kensho/iifl", payload)

    result = get_secret("kensho/iifl")
    assert result == payload


@mock_aws
def test_get_secret_all_supported_paths():
    from tools.secrets import get_secret
    paths = ["kensho/iifl", "kensho/twilio", "kensho/anthropic", "kensho/config"]
    for path in paths:
        _create_secret(path, {"path": path, "value": "dummy"})

    for path in paths:
        result = get_secret(path)
        assert result["path"] == path


# ---------------------------------------------------------------------------
# Failure cases — must raise RuntimeError, never fall back
# ---------------------------------------------------------------------------

@mock_aws
def test_get_secret_raises_on_missing_secret():
    from tools.secrets import get_secret
    with pytest.raises(RuntimeError, match="Failed to retrieve secret"):
        get_secret("kensho/nonexistent")


@mock_aws
def test_get_secret_raises_on_missing_secret_includes_name():
    from tools.secrets import get_secret
    with pytest.raises(RuntimeError) as exc_info:
        get_secret("kensho/does-not-exist")
    assert "kensho/does-not-exist" in str(exc_info.value)


@mock_aws
def test_get_secret_raises_on_invalid_json():
    from tools.secrets import get_secret
    _create_secret("kensho/bad-json", "not-valid-json{{{")
    with pytest.raises(RuntimeError):
        get_secret("kensho/bad-json")


@mock_aws
def test_get_secret_does_not_fall_back_to_env(monkeypatch):
    from tools.secrets import get_secret
    monkeypatch.setenv("KENSHO_FALLBACK", "should-never-be-used")
    with pytest.raises(RuntimeError):
        get_secret("kensho/missing")
