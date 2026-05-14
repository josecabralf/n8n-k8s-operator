"""Unit tests for src/charm.py — Postgres + ingress lifecycle and Pebble layer assembly."""

from __future__ import annotations

import json

from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import CheckStatus
from ops.testing import Harness

DB_RELATION = "postgresql"
INGRESS_RELATION = "ingress"
INGRESS_REMOTE = "traefik-k8s"
INGRESS_URL = "http://n8n.example.com/"
INGRESS_APP_DATA = {"ingress": json.dumps({"url": INGRESS_URL})}
PEER_RELATION = "n8n-peers"
CONTAINER = "n8n"

DB_DATA = {
    "endpoints": "10.1.2.3:5432",
    "username": "n8n_user",
    "password": "s3cret",
    "database": "n8n",
}


def _begin(harness: Harness) -> None:
    # The traefik_k8s v2 ingress library validates the requirer app databag with
    # pydantic and requires a non-empty model name; set one explicitly so the
    # Harness doesn't trip the validator when an ingress relation joins.
    harness.set_model_name("test-model")
    harness.add_relation(PEER_RELATION, "n8n-k8s")
    harness.begin_with_initial_hooks()


def _relate_ingress(harness: Harness, *, with_url: bool = True) -> int:
    rel_id = harness.add_relation(INGRESS_RELATION, INGRESS_REMOTE)
    if with_url:
        harness.update_relation_data(rel_id, INGRESS_REMOTE, INGRESS_APP_DATA)
    return rel_id


def test_install_without_postgres_is_blocked(harness):
    _begin(harness)
    assert harness.charm.unit.status == BlockedStatus("waiting for postgresql relation")


def test_pebble_ready_without_postgres_stays_blocked(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    assert harness.charm.unit.status == BlockedStatus("waiting for postgresql relation")


def test_relation_added_but_no_creds_yields_waiting(harness):
    _begin(harness)
    harness.add_relation(DB_RELATION, "postgresql-k8s")
    assert harness.charm.unit.status == WaitingStatus("waiting for database credentials")


def test_postgres_alone_does_not_write_pebble_layer_and_blocks_on_ingress(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)

    assert harness.charm.unit.status == BlockedStatus("waiting for ingress relation")
    plan = harness.get_container_pebble_plan(CONTAINER).to_dict()
    assert "n8n" not in plan.get("services", {})


def test_postgres_only_blocks_on_ingress(harness):
    _begin(harness)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)

    assert harness.charm.unit.status == BlockedStatus("waiting for ingress relation")


def test_ingress_relation_without_url_yields_waiting(harness):
    _begin(harness)
    db_rel = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(db_rel, "postgresql-k8s", DB_DATA)
    _relate_ingress(harness, with_url=False)
    # add_relation without app data doesn't fire ingress.on.ready, so nudge a
    # reconcile via update-status to re-evaluate the relation/URL state.
    harness.charm.on.update_status.emit()

    assert harness.charm.unit.status == WaitingStatus("waiting for ingress url")


def test_both_relations_ready_writes_eleven_env_vars(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    db_rel = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(db_rel, "postgresql-k8s", DB_DATA)
    _relate_ingress(harness)

    plan = harness.get_container_pebble_plan(CONTAINER).to_dict()
    env = plan["services"]["n8n"]["environment"]
    assert env == {
        "DB_TYPE": "postgresdb",
        "DB_POSTGRESDB_HOST": "10.1.2.3",
        "DB_POSTGRESDB_PORT": "5432",
        "DB_POSTGRESDB_DATABASE": "n8n",
        "DB_POSTGRESDB_USER": "n8n_user",
        "DB_POSTGRESDB_PASSWORD": "s3cret",
        "N8N_HOST": "n8n.example.com",
        "N8N_PROTOCOL": "http",
        "N8N_PORT": "5678",
        "WEBHOOK_URL": "http://n8n.example.com/",
        "N8N_EDITOR_BASE_URL": "http://n8n.example.com/",
    }
    assert plan["checks"]["live"]["http"]["url"].endswith("/healthz")
    assert plan["checks"]["ready"]["http"]["url"].endswith("/healthz/readiness")


def test_active_status_once_ready_check_is_up(harness, monkeypatch):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    db_rel = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(db_rel, "postgresql-k8s", DB_DATA)
    _relate_ingress(harness)

    # Force the "ready" check to report UP, then nudge a reconcile via update-status.
    container = harness.charm.unit.get_container(CONTAINER)

    class _Check:
        status = CheckStatus.UP

    monkeypatch.setattr(container, "get_check", lambda _name: _Check())
    harness.charm.on.update_status.emit()
    assert harness.charm.unit.status == ActiveStatus()


def test_endpoints_changed_updates_env(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    db_rel = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(db_rel, "postgresql-k8s", DB_DATA)
    _relate_ingress(harness)
    harness.update_relation_data(db_rel, "postgresql-k8s", {"endpoints": "10.9.9.9:5433"})

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["DB_POSTGRESDB_HOST"] == "10.9.9.9"
    assert env["DB_POSTGRESDB_PORT"] == "5433"


def test_ingress_url_change_propagates(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    db_rel = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(db_rel, "postgresql-k8s", DB_DATA)
    ingress_rel = _relate_ingress(harness)

    new_url = "http://n8n-2.example.com/"
    harness.update_relation_data(
        ingress_rel, INGRESS_REMOTE, {"ingress": json.dumps({"url": new_url})}
    )

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_HOST"] == "n8n-2.example.com"
    assert env["WEBHOOK_URL"] == new_url
    assert env["N8N_EDITOR_BASE_URL"] == new_url


def test_ingress_relation_broken_reverts_to_blocked(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    db_rel = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(db_rel, "postgresql-k8s", DB_DATA)
    ingress_rel = _relate_ingress(harness)

    harness.remove_relation(ingress_rel)
    assert harness.charm.unit.status == BlockedStatus("waiting for ingress relation")


def test_relation_broken_returns_to_blocked(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)

    harness.remove_relation(rel_id)
    assert harness.charm.unit.status == BlockedStatus("waiting for postgresql relation")
