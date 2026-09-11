"""
Carofi-specific overrides.

Imported last from horilla.settings.__init__ (after base + addons), which is the
extension point upstream documents for exactly this. Everything here was carried
over from the fork's old flat horilla/settings.py, which became this package in
2.x.

Do NOT `from .base import *` — that re-exports base MEDIA_* values and wipes the
AWS S3 paths addons.py sets. Selective imports only, as below.
"""

from .base import AUTHENTICATION_BACKENDS, INSTALLED_APPS, env

# Load secrets from AWS Secrets Manager when enabled. Must run before any
# setting below reads from env(). base.py has already called read_env(), so
# ENABLE_AWS_SECRET_MANAGER and the secret names are available by now.
from horilla.aws_secrets import load_aws_secrets  # noqa: E402

load_aws_secrets()


def _env_csv(name, default=""):
    raw_value = env(name, default=default)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _env_key_value_pairs(name, default=""):
    raw_value = env(name, default=default)
    parsed = {}
    for part in [item.strip() for item in raw_value.split(",") if item.strip()]:
        if "=" in part:
            key, value = part.split("=", 1)
            parsed[key.strip()] = value.strip()
    return parsed


ENABLE_SOCIAL_LOGIN = env.bool("ENABLE_SOCIAL_LOGIN", default=False)
ENABLE_LOGIN_FORM = env.bool("ENABLE_LOGIN_FORM", default=True)

if ENABLE_SOCIAL_LOGIN:
    if "social_django" not in INSTALLED_APPS:
        INSTALLED_APPS += ["social_django"]

    # APPEND, do not replace. The fork's 1.x settings did
    #   AUTHENTICATION_BACKENDS = ("django.contrib.auth.backends.ModelBackend",
    #                              "social_core.backends.google.GoogleOAuth2")
    # which is wrong against 2.x on two counts:
    #   * axes.backends.AxesStandaloneBackend MUST stay first -- it
    #     short-circuits authenticate() for a locked-out user, so any backend
    #     ahead of it would still verify the password and let an attacker keep
    #     testing credentials. Replacing the list disables brute-force lockout.
    #   * base.auth_backends.CompanyScopedBackend replaced ModelBackend in 2.x
    #     and is what enforces per-company scoping at login.
    # Appending keeps both and adds Google as a last resort.
    if "social_core.backends.google.GoogleOAuth2" not in AUTHENTICATION_BACKENDS:
        AUTHENTICATION_BACKENDS += ["social_core.backends.google.GoogleOAuth2"]

    SOCIAL_LOGIN_STRICT_EMPLOYEE_MATCH = env.bool(
        "SOCIAL_LOGIN_STRICT_EMPLOYEE_MATCH", default=False
    )
    SOCIAL_LOGIN_STRICT_REQUIRE_ACTIVE_EMPLOYEE = env.bool(
        "SOCIAL_LOGIN_STRICT_REQUIRE_ACTIVE_EMPLOYEE", default=True
    )
    SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = env(
        "SOCIAL_AUTH_GOOGLE_OAUTH2_KEY",
        default=env("GOOGLE_CLIENT_ID", default=""),
    )
    SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = env(
        "SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET",
        default=env("GOOGLE_CLIENT_SECRET", default=""),
    )
    SOCIAL_AUTH_GOOGLE_OAUTH2_SCOPE = _env_csv(
        "SOCIAL_AUTH_GOOGLE_OAUTH2_SCOPE",
        default="email,profile",
    )
    SOCIAL_AUTH_GOOGLE_OAUTH2_AUTH_EXTRA_ARGUMENTS = _env_key_value_pairs(
        "SOCIAL_AUTH_GOOGLE_OAUTH2_AUTH_EXTRA_ARGUMENTS",
        default="access_type=online",
    )
    SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS = _env_csv(
        "SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS",
        default="carofi.app",
    )
    # Reuse existing users by verified email instead of creating duplicates.
    SOCIAL_AUTH_PIPELINE = (
        "social_core.pipeline.social_auth.social_details",
        "social_core.pipeline.social_auth.social_uid",
        "social_core.pipeline.social_auth.auth_allowed",
        "social_core.pipeline.social_auth.social_user",
        "social_core.pipeline.user.get_username",
        "social_core.pipeline.social_auth.associate_by_email",
        "base.social_pipeline.enforce_employee_access",
        "social_core.pipeline.user.create_user",
        "social_core.pipeline.social_auth.associate_user",
        "base.social_pipeline.link_employee_by_email",
        "social_core.pipeline.social_auth.load_extra_data",
        "social_core.pipeline.user.user_details",
    )
    SOCIAL_AUTH_LOGIN_REDIRECT_URL = "/"
    SOCIAL_AUTH_LOGIN_ERROR_URL = "/login/"

# ---------------------------------------------------------------------------
# Carofi internal integration
#
# Used by the HR / Leave module on client.web.admin: the carofi BFF
# (server.connect.admin) exchanges a shared service token for a per-employee
# JWT via /api/auth/internal-token/, and the leave signal posts an HMAC-signed
# webhook to the BFF whenever a LeaveRequest status changes.
# ---------------------------------------------------------------------------
CAROFI_INTERNAL_SERVICE_TOKEN = env("CAROFI_INTERNAL_SERVICE_TOKEN", default="")
CAROFI_LEAVE_WEBHOOK_URL = env("CAROFI_LEAVE_WEBHOOK_URL", default="")
CAROFI_LEAVE_WEBHOOK_SECRET = env("CAROFI_LEAVE_WEBHOOK_SECRET", default="")
