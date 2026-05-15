"""Pebble layer builder for the n8n container."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

from ops.pebble import LayerDict

N8N_URL = "http://localhost:5678"


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


def build_layer(
    db_env: Mapping[str, str],
    encryption_key: str = "",
    url_env: Mapping[str, str] | None = None,
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
        metrics_env: Optional mapping of metrics env vars, typically
            ``{"N8N_METRICS": "true"}`` when the ``metrics-endpoint``
            relation is present. Omit to leave n8n metrics disabled
            (n8n default — ``/metrics`` returns 404).

    Returns:
        A Pebble LayerDict with one service (``n8n``) plus an alive HTTP
        check on /healthz and a ready HTTP check on /healthz/readiness.
    """
    environment: dict[str, str] = dict(db_env)
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
