"""Unit tests for the ingress (ingress v2) relation wiring."""

from __future__ import annotations

import json

from ops.model import BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import N8nK8sCharm

DB_RELATION = "postgresql"
PEER_RELATION = "n8n-peers"
INGRESS_RELATION = "ingress"
CONTAINER = "n8n"
APP_NAME = "n8n"
TRAEFIK_APP = "traefik-k8s"

DB_DATA = {
    "endpoints": "10.1.2.3:5432",
    "username": "n8n_user",
    "password": "s3cret",
    "database": "n8n",
}


def _begin(harness: Harness) -> None:
    harness.set_model_name("my-model")
    harness.add_relation(PEER_RELATION, APP_NAME)
    harness.begin_with_initial_hooks()


def _add_postgres(harness: Harness) -> int:
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)
    return rel_id


def _add_ingress(harness: Harness, url="http://traefik.local/") -> int:
    rel_id = harness.add_relation(INGRESS_RELATION, TRAEFIK_APP)
    if url is not None:
        harness.update_relation_data(rel_id, TRAEFIK_APP, {"ingress": json.dumps({"url": url})})
    return rel_id


def _env(harness: Harness) -> dict[str, str]:
    return harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]


def test_blocked_without_ingress_even_with_postgres(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_postgres(harness)
    assert harness.charm.unit.status == BlockedStatus("waiting for ingress relation")


def test_waiting_when_related_but_no_url(harness, monkeypatch):
    monkeypatch.setattr(N8nK8sCharm, "_probe_owner_setup", lambda self: True)
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_postgres(harness)
    _add_ingress(harness, url=None)
    # Adding the relation without a URL does not fire the requirer's `ready`
    # event, so nudge a reconcile the way Juju's periodic hook would.
    harness.charm.on.update_status.emit()

    assert harness.charm.unit.status == WaitingStatus("waiting for ingress URL")


def test_env_vars_set_when_url_published(harness, monkeypatch):
    monkeypatch.setattr(N8nK8sCharm, "_probe_owner_setup", lambda self: True)
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_postgres(harness)
    _add_ingress(harness)

    env = _env(harness)
    assert env["N8N_HOST"] == "traefik.local"
    assert env["N8N_PROTOCOL"] == "http"
    assert env["N8N_PORT"] == "5678"
    assert env["N8N_PATH"] == "/"
    assert env["WEBHOOK_URL"] == "http://traefik.local/"
    assert env["N8N_EDITOR_BASE_URL"] == "http://traefik.local/"


def test_url_change_replans_with_new_host(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_postgres(harness)
    rel_id = _add_ingress(harness)
    harness.update_relation_data(rel_id, TRAEFIK_APP, {"ingress": json.dumps({"url": "http://new.example.com/"})})

    env = _env(harness)
    assert env["N8N_HOST"] == "new.example.com"
    assert env["WEBHOOK_URL"] == "http://new.example.com/"


def test_pebble_checks_target_localhost(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_postgres(harness)
    _add_ingress(harness)

    plan = harness.get_container_pebble_plan(CONTAINER).to_dict()
    assert "localhost:5678" in plan["checks"]["live"]["http"]["url"]
    assert "localhost:5678" in plan["checks"]["ready"]["http"]["url"]


def test_revoked_returns_to_blocked(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_postgres(harness)
    rel_id = _add_ingress(harness)

    harness.remove_relation(rel_id)
    assert harness.charm.unit.status == BlockedStatus("waiting for ingress relation")
