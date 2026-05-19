"""Pebble layer builder for the n8n container."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from ops.pebble import LayerDict

N8N_URL = "http://localhost:5678"

VALID_LOG_LEVELS = frozenset({"debug", "info", "warn", "error"})
VALID_SAVE_MODES = frozenset({"all", "none"})


def build_url_env(external_url: str) -> dict[str, str]:
    """Return n8n env vars derived from an external URL.

    N8N_PROTOCOL is fixed to "http" because TLS terminates at the
    ingress; n8n listens plaintext in-pod.
    """
    parsed = urlparse(external_url)
    return {
        "N8N_HOST": parsed.hostname or "",
        "N8N_PROTOCOL": "http",
        "N8N_PORT": "5678",
        "WEBHOOK_URL": external_url,
        "N8N_EDITOR_BASE_URL": external_url,
    }


def build_tier1_env(
    config: Mapping[str, Any],
) -> tuple[dict[str, str] | None, str | None]:
    """Translate Tier 1 charm configs into n8n env vars.

    Returns (env, None) on success or (None, msg) when a value is invalid;
    the caller surfaces ``msg`` as a BlockedStatus. This is the single
    convention for Tier 1 config→env translation (issues #7 and #8 extend
    the same pattern).
    """
    log_level = str(config.get("log-level", "info"))
    if log_level not in VALID_LOG_LEVELS:
        return (
            None,
            f"invalid log-level '{log_level}'; must be one of: debug, info, warn, error",
        )

    timezone = str(config.get("timezone", "UTC"))
    if not timezone:
        return (None, "timezone must not be empty")

    save_on_error = str(config.get("executions-data-save-on-error", "all"))
    if save_on_error not in VALID_SAVE_MODES:
        return (
            None,
            f"invalid executions-data-save-on-error '{save_on_error}'; must be 'all' or 'none'",
        )

    save_on_success = str(config.get("executions-data-save-on-success", "all"))
    if save_on_success not in VALID_SAVE_MODES:
        return (
            None,
            f"invalid executions-data-save-on-success '{save_on_success}'; must be 'all' or 'none'",
        )

    max_age = int(config.get("executions-data-max-age-hours", 336))
    if max_age < 0:
        return (None, "executions-data-max-age-hours must be >= 0")

    prune = bool(config.get("executions-data-prune", False))
    save_on_progress = bool(config.get("executions-data-save-on-progress", False))
    disable_user_reg = bool(config.get("disable-user-registration", False))

    env = {
        "N8N_LOG_LEVEL": log_level,
        "GENERIC_TIMEZONE": timezone,
        "TZ": timezone,
        "EXECUTIONS_DATA_PRUNE": "true" if prune else "false",
        "EXECUTIONS_DATA_MAX_AGE": str(max_age),
        "EXECUTIONS_DATA_SAVE_ON_ERROR": save_on_error,
        "EXECUTIONS_DATA_SAVE_ON_SUCCESS": save_on_success,
        "EXECUTIONS_DATA_SAVE_ON_PROGRESS": "true" if save_on_progress else "false",
        "N8N_USER_MANAGEMENT_DISABLED": "true" if disable_user_reg else "false",
    }
    return (env, None)


def build_smtp_env(
    config: Mapping[str, Any],
    smtp_password: str | None,
) -> tuple[dict[str, str] | None, str | None]:
    """Translate Tier 2 SMTP configs into n8n env vars.

    Returns ({}, None) when SMTP is unconfigured (all of host/user/password
    empty); (env, None) when fully configured; (None, msg) when the
    config is invalid (partial trio, port out of range).
    """
    host = str(config.get("smtp-host", "")).strip()
    user = str(config.get("smtp-user", "")).strip()
    pw_set = bool(smtp_password)

    if not (host or user or pw_set):
        return ({}, None)
    if not (host and user and pw_set):
        return (None, "smtp-host, smtp-user, and smtp-password must all be set together")

    port = int(config.get("smtp-port", 587))
    if not 1 <= port <= 65535:
        return (None, f"invalid smtp-port '{port}'; must be 1–65535")

    env = {
        "N8N_SMTP_HOST": host,
        "N8N_SMTP_PORT": str(port),
        "N8N_SMTP_USER": user,
        "N8N_SMTP_PASSWORD": smtp_password,
        "N8N_SMTP_SSL": "true" if bool(config.get("smtp-ssl-tls", False)) else "false",
    }
    sender = str(config.get("smtp-sender", "")).strip()
    if sender:
        env["N8N_SMTP_SENDER"] = sender
    return (env, None)


def build_layer(
    db_env: Mapping[str, str],
    encryption_key: str = "",
    url_env: Mapping[str, str] | None = None,
    tier1_env: Mapping[str, str] | None = None,
    smtp_env: Mapping[str, str] | None = None,
    metrics_env: Mapping[str, str] | None = None,
) -> LayerDict:
    """Return a Pebble layer dict that runs n8n with the given DB env vars.

    Args:
        db_env: Mapping of n8n Postgres env-var names to values. Must
            contain at minimum the six DB_* variables n8n needs to talk
            to PostgreSQL (DB_TYPE, DB_POSTGRESDB_HOST, _PORT,
            _DATABASE, _USER, _PASSWORD).
        encryption_key: Value to inject as ``N8N_ENCRYPTION_KEY`` in the
            n8n service environment. The caller is responsible for
            supplying a non-empty key in production. When the default
            empty string is passed the variable is omitted from the
            layer entirely; this default exists only to keep the
            signature backwards-compatible for callers that have not
            yet been updated.
        url_env: Optional mapping of ingress-derived env vars
            (``N8N_HOST``, ``N8N_PROTOCOL``, ``N8N_PORT``,
            ``WEBHOOK_URL``, ``N8N_EDITOR_BASE_URL``).
        tier1_env: Optional mapping of Tier 1 n8n env vars derived from
            charm config (logging, timezone, executions retention,
            user-management toggle).
        smtp_env: Optional mapping of Tier 2 SMTP env vars (``N8N_SMTP_HOST``,
            ``N8N_SMTP_PORT``, ``N8N_SMTP_USER``, ``N8N_SMTP_PASSWORD``,
            ``N8N_SMTP_SSL`` and optionally ``N8N_SMTP_SENDER``). Merged
            after ``tier1_env`` and before ``url_env`` so url-derived vars
            still win on collision.
        metrics_env: Optional mapping of metrics env vars, typically
            ``{"N8N_METRICS": "true"}`` when the ``metrics-endpoint``
            relation is present. Omit to leave n8n metrics disabled
            (n8n default — ``/metrics`` returns 404).

    Returns:
        A Pebble LayerDict with one service (``n8n``) plus an alive HTTP
        check on /healthz and a ready HTTP check on /healthz/readiness.
    """
    environment: dict[str, str] = dict(db_env)
    if tier1_env:
        environment.update(tier1_env)
    if smtp_env:
        environment.update(smtp_env)
    if url_env:
        environment.update(url_env)
    if metrics_env:
        environment.update(metrics_env)
    if encryption_key:
        environment["N8N_ENCRYPTION_KEY"] = encryption_key

    return {
        "summary": "n8n workload layer",
        "description": "Runs n8n against the related PostgreSQL.",
        "services": {
            "n8n": {
                "override": "replace",
                "summary": "n8n",
                "command": "n8n start",
                "startup": "enabled",
                "environment": environment,
            }
        },
        "checks": {
            "live": {
                "override": "replace",
                "level": "alive",
                "period": "30s",
                "http": {"url": f"{N8N_URL}/healthz"},
            },
            "ready": {
                "override": "replace",
                "level": "ready",
                "period": "10s",
                "threshold": 3,
                "http": {"url": f"{N8N_URL}/healthz/readiness"},
            },
        },
    }
