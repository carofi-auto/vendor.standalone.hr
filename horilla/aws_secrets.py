"""
AWS Secrets Manager integration for Horilla.

Mirrors the pattern used by the carofi Node.js services: when
``ENABLE_AWS_SECRET_MANAGER`` is set to ``"true"`` (case-insensitive) the
helper fetches one or two named secrets from AWS SM and injects their
key-value pairs into ``os.environ`` so django-environ / settings.py can
read them transparently.

Usage in settings.py
--------------------
::

    from horilla.aws_secrets import load_aws_secrets
    load_aws_secrets()          # no-op when ENABLE_AWS_SECRET_MANAGER != "true"

    # Secrets are now in os.environ, so env("MY_SECRET") works as usual.

Required env vars (only when enabled):
    ENABLE_AWS_SECRET_MANAGER   "true" to enable
    AWS_REGION                  AWS region (default us-east-1)
    COMMON_SECRET_NAME          Name of the shared/common secret in SM
    SERVICE_SECRET_NAME         (optional) Name of a service-specific secret
"""

import json
import logging
import os

logger = logging.getLogger(__name__)


def load_aws_secrets() -> None:
    """Fetch secrets from AWS Secrets Manager and inject into ``os.environ``."""
    enabled = os.environ.get("ENABLE_AWS_SECRET_MANAGER", "").strip().lower()
    if enabled != "true":
        return

    # boto3 is already in requirements.txt (used for S3 storage).
    # Import lazily so the module doesn't fail at import time when AWS
    # credentials are not configured (e.g. local development).
    try:
        import boto3
    except ImportError:
        logger.warning("boto3 is not installed — skipping AWS Secrets Manager")
        return

    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("secretsmanager", region_name=region)

    common_name = os.environ.get("COMMON_SECRET_NAME", "")
    service_name = os.environ.get("SERVICE_SECRET_NAME", "")

    for secret_name in (common_name, service_name):
        if not secret_name:
            continue
        try:
            response = client.get_secret_value(SecretId=secret_name)
            secret_string = response.get("SecretString")
            if secret_string:
                pairs = json.loads(secret_string)
            else:
                import base64

                raw = base64.b64decode(response["SecretBinary"])
                pairs = json.loads(raw)

            if not isinstance(pairs, dict):
                logger.error(
                    "AWS SM secret '%s' is not a JSON object — skipping", secret_name
                )
                continue

            for key, value in pairs.items():
                os.environ[key] = str(value)
            logger.info(
                "Loaded %d key(s) from AWS SM secret '%s'", len(pairs), secret_name
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to load AWS SM secret '%s' — proceeding without it",
                secret_name,
            )
