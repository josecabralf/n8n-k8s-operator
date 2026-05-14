"""Unit tests for src/charm.py — Postgres + ingress lifecycle and Pebble layer assembly."""

from __future__ import annotations

import json

import pytest
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import CheckStatus
from ops.testing import ActionFailed, Harness

from charm import N8nK8sCharm
from state import ENCRYPTION_KEY_SECRET_ID, PEER_RELATION_NAME

DB_RELATION = "postgresql"
INGRESS_RELATION = "ingress"
INGRESS_REMOTE = "traefik-k8s"
INGRESS_URL = "http://n8n.example.com/"
INGRESS_APP_DATA = {"ingress": json.dumps({"url": INGRESS_URL})}
PEER_RELATION = "n8n-peers"
CONTAINER = "n8n"
APP_NAME = "n8n-k8s"

DB_DATA = {
    "endpoints": "10.1.2.3:5432",
    "username": "n8n_user",
    "password": "s3cret",
    "database": "n8n",
}

EXPECTED_DB_ENV = {
    "DB_TYPE": "postgresdb",
    "DB_POSTGRESDB_HOST": "10.1.2.3",
    "DB_POSTGRESDB_PORT": "5432",
    "DB_POSTGRESDB_DATABASE": "n8n",
    "DB_POSTGRESDB_USER": "n8n_user",
    "DB_POSTGRESDB_PASSWORD": "s3cret",
}


def _begin(harness: Harness) -> None:
    # The traefik_k8s v2 ingress library validates the requirer app databag with
    # pydantic and requires a non-empty model name; set one explicitly so the
    # Harness doesn't trip the validator when an ingress relation joins.
    harness.set_model_name("test-model")
    harness.add_relation(PEER_RELATION, APP_NAME)
    harness.begin_with_initial_hooks()


def _relate_ingress(harness: Harness, *, with_url: bool = True) -> int:
    rel_id = harness.add_relation(INGRESS_RELATION, INGRESS_REMOTE)
    if with_url:
        harness.update_relation_data(rel_id, INGRESS_REMOTE, INGRESS_APP_DATA)
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


def test_both_relations_ready_writes_full_env(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    db_rel = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(db_rel, "postgresql-k8s", DB_DATA)
    _relate_ingress(harness)

    plan = harness.get_container_pebble_plan(CONTAINER).to_dict()
    env = plan["services"]["n8n"]["environment"]
    for k, v in EXPECTED_DB_ENV.items():
        assert env[k] == v
    assert env["N8N_HOST"] == "n8n.example.com"
    assert env["N8N_PROTOCOL"] == "http"
    assert env["N8N_PORT"] == "5678"
    assert env["N8N_PATH"] == "/"
    assert env["WEBHOOK_URL"] == "http://n8n.example.com/"
    assert env["N8N_EDITOR_BASE_URL"] == "http://n8n.example.com/"
    assert "N8N_ENCRYPTION_KEY" in env and env["N8N_ENCRYPTION_KEY"]
    assert plan["checks"]["live"]["http"]["url"].endswith("/healthz")
    assert plan["checks"]["ready"]["http"]["url"].endswith("/healthz/readiness")


def test_ingress_with_path_prefix_sets_n8n_path(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    db_rel = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(db_rel, "postgresql-k8s", DB_DATA)
    rel_id = harness.add_relation(INGRESS_RELATION, INGRESS_REMOTE)
    harness.update_relation_data(
        rel_id,
        INGRESS_REMOTE,
        {"ingress": json.dumps({"url": "http://gw.example.com/my-model-my-app/"})},
    )

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_PATH"] == "/my-model-my-app/"
    assert env["WEBHOOK_URL"] == "http://gw.example.com/my-model-my-app/"


def test_active_status_once_ready_check_is_up(harness, monkeypatch):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    db_rel = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(db_rel, "postgresql-k8s", DB_DATA)
    _relate_ingress(harness)

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
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)
    _relate_ingress(harness)

    secret_id = _stored_secret_id(harness)
    assert secret_id is not None
    expected = harness.model.get_secret(id=secret_id).get_content()["value"]

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_ENCRYPTION_KEY"] == expected


def test_config_override_with_granted_secret(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)
    _relate_ingress(harness)

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
