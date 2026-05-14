"""Unit tests for src/charm.py — Postgres relation lifecycle + Pebble layer assembly."""

from __future__ import annotations

from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import CheckStatus
from ops.testing import Harness

DB_RELATION = "postgresql"
PEER_RELATION = "n8n-peers"
CONTAINER = "n8n"

DB_DATA = {
    "endpoints": "10.1.2.3:5432",
    "username": "n8n_user",
    "password": "s3cret",
    "database": "n8n",
}


def _begin(harness: Harness) -> None:
    harness.add_relation(PEER_RELATION, "n8n-k8s")
    harness.begin_with_initial_hooks()


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


def test_database_created_writes_pebble_layer_with_six_env_vars(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)

    plan = harness.get_container_pebble_plan(CONTAINER).to_dict()
    env = plan["services"]["n8n"]["environment"]
    assert env == {
        "DB_TYPE": "postgresdb",
        "DB_POSTGRESDB_HOST": "10.1.2.3",
        "DB_POSTGRESDB_PORT": "5432",
        "DB_POSTGRESDB_DATABASE": "n8n",
        "DB_POSTGRESDB_USER": "n8n_user",
        "DB_POSTGRESDB_PASSWORD": "s3cret",
    }
    assert plan["checks"]["live"]["http"]["url"].endswith("/healthz")
    assert plan["checks"]["ready"]["http"]["url"].endswith("/healthz/readiness")


def test_active_status_once_ready_check_is_up(harness, monkeypatch):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)

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
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)
    harness.update_relation_data(rel_id, "postgresql-k8s", {"endpoints": "10.9.9.9:5433"})

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["DB_POSTGRESDB_HOST"] == "10.9.9.9"
    assert env["DB_POSTGRESDB_PORT"] == "5433"


def test_relation_broken_returns_to_blocked(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)

    harness.remove_relation(rel_id)
    assert harness.charm.unit.status == BlockedStatus("waiting for postgresql relation")
