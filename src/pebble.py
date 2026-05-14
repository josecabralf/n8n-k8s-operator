"""Pebble layer builder for the n8n container."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

from ops.pebble import LayerDict

N8N_URL = "http://localhost:5678"
N8N_INTERNAL_PORT = "5678"


def build_url_env(external_url: str | None) -> dict[str, str]:
    """Map an ingress URL to the five n8n URL-shaped env vars.

    Returns {} when external_url is None or empty. This is the single
    source of truth for WEBHOOK_URL derivation so future queue-mode work
    (where workers also need the public webhook URL) can reuse it.

    Args:
        external_url: The public ingress URL for this n8n unit, or None
            when no ingress is yet established.

    Returns:
        A dict with N8N_HOST, N8N_PROTOCOL, N8N_PORT, WEBHOOK_URL and
        N8N_EDITOR_BASE_URL. TLS terminates at the ingress, so
        N8N_PROTOCOL is always "http". WEBHOOK_URL and
        N8N_EDITOR_BASE_URL are normalised to end in exactly one "/".
    """
    if not external_url:
        return {}

    host = urlparse(external_url).hostname or ""
    normalised = f"{external_url.rstrip('/')}/"
    return {
        "N8N_HOST": host,
        "N8N_PROTOCOL": "http",
        "N8N_PORT": N8N_INTERNAL_PORT,
        "WEBHOOK_URL": normalised,
        "N8N_EDITOR_BASE_URL": normalised,
    }


def build_layer(env: Mapping[str, str]) -> LayerDict:
    """Return a Pebble layer dict that runs n8n with the given env.

    Args:
        env: The fully-merged env dict (DB + URL + future) to install on
            the n8n service. Callers are responsible for composing this
            from the DB env (from the postgresql relation) and the URL
            env (from :func:`build_url_env`); this function just
            installs whatever it's given.

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
                "environment": dict(env),
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
