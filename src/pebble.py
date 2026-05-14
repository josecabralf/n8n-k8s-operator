"""Pebble layer builder for the n8n container."""

from __future__ import annotations

from collections.abc import Mapping

from ops.pebble import LayerDict

N8N_URL = "http://localhost:5678"


def build_layer(db_env: Mapping[str, str]) -> LayerDict:
    """Return a Pebble layer dict that runs n8n with the given DB env vars.

    Args:
        db_env: Mapping of n8n Postgres env-var names to values. Must
            contain at minimum the six DB_* variables n8n needs to talk
            to PostgreSQL (DB_TYPE, DB_POSTGRESDB_HOST, _PORT,
            _DATABASE, _USER, _PASSWORD).

    Returns:
        A Pebble LayerDict with one service (``n8n``) plus an alive HTTP
        check on /healthz and a ready HTTP check on /healthz/readiness.
    """
    return {
        "summary": "n8n workload layer",
        "description": "Runs n8n against the related PostgreSQL.",
        "services": {
            "n8n": {
                "override": "replace",
                "summary": "n8n",
                "command": "n8n start",
                "startup": "enabled",
                "environment": dict(db_env),
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
