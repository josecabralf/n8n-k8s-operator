"""Unit tests for src/charm.py — Postgres relation lifecycle + Pebble layer assembly."""

from __future__ import annotations

import pytest
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import CheckStatus
from ops.testing import ActionFailed, Harness

from charm import N8nK8sCharm
from state import ENCRYPTION_KEY_SECRET_ID, PEER_RELATION_NAME

DB_RELATION = "postgresql"
PEER_RELATION = "n8n-peers"
INGRESS_RELATION = "traefik-route"
CONTAINER = "n8n"
APP_NAME = "n8n-k8s"

DB_DATA = {
    "endpoints": "10.1.2.3:5432",
    "username": "n8n_user",
    "password": "s3cret",
    "database": "n8n",
}

INGRESS_DATA = {"external_host": "traefik.local", "scheme": "http"}

EXPECTED_DB_ENV = {
    "DB_TYPE": "postgresdb",
    "DB_POSTGRESDB_HOST": "10.1.2.3",
    "DB_POSTGRESDB_PORT": "5432",
    "DB_POSTGRESDB_DATABASE": "n8n",
    "DB_POSTGRESDB_USER": "n8n_user",
    "DB_POSTGRESDB_PASSWORD": "s3cret",
}


def _begin(harness: Harness) -> None:
    harness.add_relation(PEER_RELATION, APP_NAME)
    harness.begin_with_initial_hooks()


def _add_ingress(harness: Harness, data: dict | None = INGRESS_DATA) -> int:
    rel_id = harness.add_relation(INGRESS_RELATION, "traefik-k8s")
    if data:
        harness.update_relation_data(rel_id, "traefik-k8s", data)
    return rel_id


def _stored_secret_id(harness: Harness) -> str | None:
    rel = harness.charm.model.get_relation(PEER_RELATION_NAME)
    assert rel is not None
    return rel.data[harness.charm.app].get(ENCRYPTION_KEY_SECRET_ID)


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


def test_database_created_writes_pebble_layer_with_db_env_and_encryption_key(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_ingress(harness)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)

    plan = harness.get_container_pebble_plan(CONTAINER).to_dict()
    env = plan["services"]["n8n"]["environment"]
    for k, v in EXPECTED_DB_ENV.items():
        assert env[k] == v
    assert "N8N_ENCRYPTION_KEY" in env and env["N8N_ENCRYPTION_KEY"]
    assert plan["checks"]["live"]["http"]["url"].endswith("/healthz")
    assert plan["checks"]["ready"]["http"]["url"].endswith("/healthz/readiness")


def test_active_status_once_ready_check_is_up(harness, monkeypatch):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_ingress(harness)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)

    container = harness.charm.unit.get_container(CONTAINER)

    class _Check:
        status = CheckStatus.UP

    monkeypatch.setattr(container, "get_check", lambda _name: _Check())
    harness.charm.on.update_status.emit()
    assert harness.charm.unit.status == ActiveStatus()


def test_endpoints_changed_updates_env(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_ingress(harness)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)
    harness.update_relation_data(rel_id, "postgresql-k8s", {"endpoints": "10.9.9.9:5433"})

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["DB_POSTGRESDB_HOST"] == "10.9.9.9"
    assert env["DB_POSTGRESDB_PORT"] == "5433"


def test_relation_broken_returns_to_blocked(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_ingress(harness)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)

    harness.remove_relation(rel_id)
    assert harness.charm.unit.status == BlockedStatus("waiting for postgresql relation")


# --- Encryption-key tests (issue #3) ---


def test_install_creates_app_secret_once(harness):
    _begin(harness)

    first_id = _stored_secret_id(harness)
    assert first_id is not None and first_id.startswith("secret:")

    # Re-emit install: must NOT mint a new secret.
    harness.charm.on.install.emit()
    second_id = _stored_secret_id(harness)
    assert second_id == first_id

    # Trigger another reconcile via update-status: still same id.
    harness.charm.on.update_status.emit()
    assert _stored_secret_id(harness) == first_id


def test_pebble_env_contains_encryption_key(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_ingress(harness)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)

    secret_id = _stored_secret_id(harness)
    assert secret_id is not None
    expected = harness.model.get_secret(id=secret_id).get_content()["value"]

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_ENCRYPTION_KEY"] == expected


def test_config_override_with_granted_secret(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_ingress(harness)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)

    user_secret_id = harness.add_user_secret({"value": "OVERRIDE"})
    harness.grant_secret(user_secret_id, APP_NAME)
    harness.update_config({"encryption-key": user_secret_id})

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_ENCRYPTION_KEY"] == "OVERRIDE"


def test_config_override_with_ungranted_secret_blocks(harness):
    _begin(harness)

    user_secret_id = harness.add_user_secret({"value": "OVERRIDE"})
    # Do NOT grant.
    harness.update_config({"encryption-key": user_secret_id})

    assert harness.charm.unit.status == BlockedStatus("encryption-key secret not granted to app")


def test_get_encryption_key_action_returns_active_key(harness):
    _begin(harness)

    # Auto-generated path
    secret_id = _stored_secret_id(harness)
    assert secret_id is not None
    auto_value = harness.model.get_secret(id=secret_id).get_content()["value"]

    output = harness.run_action("get-encryption-key")
    assert output.results["encryption-key"] == auto_value

    # Override path
    user_secret_id = harness.add_user_secret({"value": "OVERRIDE-VALUE"})
    harness.grant_secret(user_secret_id, APP_NAME)
    harness.update_config({"encryption-key": user_secret_id})

    output2 = harness.run_action("get-encryption-key")
    assert output2.results["encryption-key"] == "OVERRIDE-VALUE"


def test_followers_wait_for_encryption_key():
    harness = Harness(N8nK8sCharm)
    harness.set_leader(False)
    harness.set_can_connect(CONTAINER, True)
    harness.add_relation(PEER_RELATION, APP_NAME)
    harness.begin_with_initial_hooks()
    try:
        assert harness.charm.unit.status == WaitingStatus("waiting for encryption key")
        assert _stored_secret_id(harness) is None
    finally:
        harness.cleanup()


def test_action_fails_when_override_secret_not_granted(harness):
    _begin(harness)

    user_secret_id = harness.add_user_secret({"value": "x"})
    harness.update_config({"encryption-key": user_secret_id})

    with pytest.raises(ActionFailed) as exc_info:
        harness.run_action("get-encryption-key")
    assert "not granted" in exc_info.value.message
