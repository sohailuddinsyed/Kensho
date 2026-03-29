"""
tools/secrets.py — AWS Secrets Manager credential retrieval.

All credentials are fetched exclusively from Secrets Manager.
Never falls back to environment variables on failure.
"""

import json
import boto3
from botocore.exceptions import ClientError


def get_secret(secret_name: str) -> dict:
    """
    Fetch a secret from AWS Secrets Manager and return it as a dict.

    Supported paths:
      - kensho/iifl
      - kensho/twilio
      - kensho/anthropic
      - kensho/config

    Args:
        secret_name: The Secrets Manager secret path (e.g. "kensho/iifl").

    Returns:
        Parsed JSON secret as a dict.

    Raises:
        RuntimeError: If the secret cannot be retrieved for any reason.
    """
    client = boto3.client("secretsmanager")

    try:
        response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        raise RuntimeError(
            f"Failed to retrieve secret '{secret_name}' from Secrets Manager: {e}"
        ) from e

    secret_string = response.get("SecretString")
    if secret_string is None:
        raise RuntimeError(
            f"Secret '{secret_name}' has no SecretString value."
        )

    try:
        return json.loads(secret_string)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Secret '{secret_name}' is not valid JSON: {e}"
        ) from e
