"""Unit tests for src/charm.py — Postgres relation lifecycle + Pebble layer assembly."""

from __future__ import annotations

import logging

import pytest
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import CheckStatus
from ops.testing import ActionFailed, Harness

from charm import (
    ERR_ALREADY_BOOTSTRAPPED,
    STATUS_WAITING_N8N,
    N8nK8sCharm,
)
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


def _fully_ready(harness: Harness) -> None:
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_ingress(harness)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)


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
    # No binary-data storage attached → Active carries the fallback warning.
    assert harness.charm.unit.status == ActiveStatus(
        "binary data in DB; attach 'binary-data' storage or " "relate s3-integrator for production use"
    )


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


# --- Tier 1 typed configs (issue #6) ---


def test_config_change_log_level_propagates_to_env(harness):
    _fully_ready(harness)
    harness.update_config({"log-level": "debug"})

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_LOG_LEVEL"] == "debug"


def test_config_invalid_log_level_blocks(harness):
    _fully_ready(harness)
    harness.update_config({"log-level": "garbage"})

    assert harness.charm.unit.status == BlockedStatus(
        "invalid log-level 'garbage'; must be one of: debug, info, warn, error"
    )


def test_config_timezone_sets_both_env_vars(harness):
    _fully_ready(harness)
    harness.update_config({"timezone": "Europe/Madrid"})

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["GENERIC_TIMEZONE"] == "Europe/Madrid"
    assert env["TZ"] == "Europe/Madrid"


# --- Owner bootstrap (issue #5) ---


def test_create_admin_action_writes_owner_env_to_pebble_layer(harness, monkeypatch):
    monkeypatch.setattr(N8nK8sCharm, "_probe_owner_setup", lambda self: False)
    _fully_ready(harness)
    output = harness.run_action(
        "create-admin",
        params={
            "email": "ops@example.com",
            "password": "hunter2",
            "first-name": "Ops",
            "last-name": "Admin",
        },
    )
    assert output.results == {"created": True, "email": "ops@example.com"}
    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_INSTANCE_OWNER_MANAGED_BY_ENV"] == "true"
    assert env["N8N_INSTANCE_OWNER_EMAIL"] == "ops@example.com"
    assert env["N8N_INSTANCE_OWNER_FIRST_NAME"] == "Ops"
    assert env["N8N_INSTANCE_OWNER_LAST_NAME"] == "Admin"
    assert env["N8N_INSTANCE_OWNER_PASSWORD_HASH"].startswith("$2b$")


def test_create_admin_action_fails_on_follower():
    harness = Harness(N8nK8sCharm)
    harness.set_leader(False)
    harness.set_can_connect(CONTAINER, True)
    harness.add_relation(PEER_RELATION, APP_NAME)
    harness.begin_with_initial_hooks()
    try:
        with pytest.raises(ActionFailed) as exc_info:
            harness.run_action(
                "create-admin",
                params={
                    "email": "ops@example.com",
                    "password": "hunter2",
                    "first-name": "Ops",
                    "last-name": "Admin",
                },
            )
        assert "leader" in exc_info.value.message
    finally:
        harness.cleanup()


def test_create_admin_action_fails_when_container_not_connectable():
    harness = Harness(N8nK8sCharm)
    harness.set_leader(True)
    harness.add_relation(PEER_RELATION, APP_NAME)
    harness.begin_with_initial_hooks()
    harness.set_can_connect(CONTAINER, False)
    try:
        with pytest.raises(ActionFailed) as exc_info:
            harness.run_action(
                "create-admin",
                params={
                    "email": "ops@example.com",
                    "password": "hunter2",
                    "first-name": "Ops",
                    "last-name": "Admin",
                },
            )
        assert "not yet connectable" in exc_info.value.message
    finally:
        harness.cleanup()


def test_status_active_when_no_admin(harness, monkeypatch):
    monkeypatch.setattr(N8nK8sCharm, "_probe_owner_setup", lambda self: False)
    _fully_ready(harness)
    container = harness.charm.unit.get_container(CONTAINER)

    class _Check:
        status = CheckStatus.UP

    monkeypatch.setattr(container, "get_check", lambda _name: _Check())
    harness.charm.on.update_status.emit()
    assert harness.charm.unit.status == ActiveStatus(STATUS_BINARY_DATA_FALLBACK)


def test_status_active_when_probe_inconclusive(harness, monkeypatch):
    monkeypatch.setattr(N8nK8sCharm, "_probe_owner_setup", lambda self: None)
    _fully_ready(harness)
    container = harness.charm.unit.get_container(CONTAINER)

    class _Check:
        status = CheckStatus.UP

    monkeypatch.setattr(container, "get_check", lambda _name: _Check())
    harness.charm.on.update_status.emit()
    assert harness.charm.unit.status == ActiveStatus(STATUS_BINARY_DATA_FALLBACK)


def test_create_admin_action_fails_when_probe_finds_admin(harness, monkeypatch):
    monkeypatch.setattr(N8nK8sCharm, "_probe_owner_setup", lambda self: True)
    _fully_ready(harness)
    with pytest.raises(ActionFailed) as exc_info:
        harness.run_action(
            "create-admin",
            params={
                "email": "ops@example.com",
                "password": "hunter2",
                "first-name": "Ops",
                "last-name": "Admin",
            },
        )
    assert exc_info.value.message == ERR_ALREADY_BOOTSTRAPPED


def test_create_admin_action_fails_when_probe_inconclusive(harness, monkeypatch):
    monkeypatch.setattr(N8nK8sCharm, "_probe_owner_setup", lambda self: None)
    _fully_ready(harness)
    with pytest.raises(ActionFailed) as exc_info:
        harness.run_action(
            "create-admin",
            params={
                "email": "ops@example.com",
                "password": "hunter2",
                "first-name": "Ops",
                "last-name": "Admin",
            },
        )
    assert exc_info.value.message == ERR_ALREADY_BOOTSTRAPPED


class _MutableCheck:
    """Helper: a Check stand-in whose status flips via the shared dict."""

    def __init__(self, state: dict) -> None:
        self._state = state

    @property
    def status(self) -> CheckStatus:
        return CheckStatus.UP if self._state["up"] else CheckStatus.DOWN


def test_pebble_check_recovered_flips_to_active(harness, monkeypatch):
    monkeypatch.setattr(N8nK8sCharm, "_probe_owner_setup", lambda self: True)
    state = {"up": False}
    from ops.model import Container

    monkeypatch.setattr(Container, "get_check", lambda self, _name: _MutableCheck(state))

    _fully_ready(harness)
    assert harness.charm.unit.status == MaintenanceStatus(STATUS_WAITING_N8N)

    state["up"] = True
    container = harness.charm.unit.get_container(CONTAINER)
    harness.charm.on.n8n_pebble_check_recovered.emit(workload=container, check_name="ready")

    assert harness.charm.unit.status == ActiveStatus(STATUS_BINARY_DATA_FALLBACK)


def test_pebble_check_failed_re_evaluates(harness, monkeypatch):
    monkeypatch.setattr(N8nK8sCharm, "_probe_owner_setup", lambda self: True)
    state = {"up": True}
    from ops.model import Container

    monkeypatch.setattr(Container, "get_check", lambda self, _name: _MutableCheck(state))

    _fully_ready(harness)
    assert harness.charm.unit.status == ActiveStatus(STATUS_BINARY_DATA_FALLBACK)

    state["up"] = False
    container = harness.charm.unit.get_container(CONTAINER)
    harness.charm.on.n8n_pebble_check_failed.emit(workload=container, check_name="ready")

    assert harness.charm.unit.status == MaintenanceStatus(STATUS_WAITING_N8N)


# --- Tier 2 SMTP configs (issue #7) ---


def test_smtp_full_config_with_granted_secret_emits_env(harness):
    _fully_ready(harness)
    secret_id = harness.add_user_secret({"value": "smtp-pw"})
    harness.grant_secret(secret_id, APP_NAME)
    harness.update_config(
        {
            "smtp-host": "smtp.example.com",
            "smtp-port": 2525,
            "smtp-user": "bot",
            "smtp-password": secret_id,
            "smtp-sender": "n8n <bot@x>",
            "smtp-ssl-tls": True,
        }
    )

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_SMTP_HOST"] == "smtp.example.com"
    assert env["N8N_SMTP_PORT"] == "2525"
    assert env["N8N_SMTP_USER"] == "bot"
    assert env["N8N_SMTP_PASSWORD"] == "smtp-pw"
    assert env["N8N_SMTP_SSL"] == "true"
    assert env["N8N_SMTP_SENDER"] == "n8n <bot@x>"


def test_smtp_password_ungranted_secret_blocks(harness):
    _fully_ready(harness)
    secret_id = harness.add_user_secret({"value": "smtp-pw"})
    # Do NOT grant.
    harness.update_config({"smtp-password": secret_id})

    assert harness.charm.unit.status == BlockedStatus("smtp-password secret not granted to app")


def test_smtp_partial_config_blocks(harness):
    _fully_ready(harness)
    harness.update_config({"smtp-host": "foo"})

    assert harness.charm.unit.status == BlockedStatus(
        "smtp-host, smtp-user, and smtp-password must all be set together"
    )


def test_smtp_unconfigured_omits_env(harness):
    _fully_ready(harness)

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    for key in env:
        assert not key.startswith("N8N_SMTP_"), f"unexpected SMTP key: {key}"


def test_status_active_after_action(harness, monkeypatch):
    monkeypatch.setattr(N8nK8sCharm, "_probe_owner_setup", lambda self: False)
    _fully_ready(harness)
    container = harness.charm.unit.get_container(CONTAINER)

    class _Check:
        status = CheckStatus.UP

    monkeypatch.setattr(container, "get_check", lambda _name: _Check())
    harness.run_action(
        "create-admin",
        params={
            "email": "ops@example.com",
            "password": "hunter2",
            "first-name": "Ops",
            "last-name": "Admin",
        },
    )
    harness.charm.on.update_status.emit()
    # No binary-data storage attached in this test → warning message on Active.
    assert harness.charm.unit.status == ActiveStatus(
        "binary data in DB; attach 'binary-data' storage or " "relate s3-integrator for production use"
    )


# --- Binary data storage (issue #9) ---


BINARY_DATA_STORAGE = "binary-data"
STATUS_BINARY_DATA_FALLBACK = (
    "binary data in DB; attach 'binary-data' storage or " "relate s3-integrator for production use"
)


def _mute_chown(harness: Harness, monkeypatch) -> None:
    """Skip the chown exec in unit tests — Harness exec doesn't run chown."""
    # Patch the bound method so reconcile doesn't blow up.
    monkeypatch.setattr(
        harness.charm,
        "_chown_binary_data_mount",
        lambda _container: None,
    )


def test_binary_data_attached_sets_filesystem_mode(harness, monkeypatch):
    storage_id = harness.add_storage(BINARY_DATA_STORAGE, attach=True)[0]
    _fully_ready(harness)
    _mute_chown(harness, monkeypatch)
    harness.charm.on.update_status.emit()

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_DEFAULT_BINARY_DATA_MODE"] == "filesystem"
    assert storage_id is not None


def test_binary_data_unattached_omits_mode_and_warns_via_active_message(harness, monkeypatch):
    _fully_ready(harness)
    _mute_chown(harness, monkeypatch)
    container = harness.charm.unit.get_container(CONTAINER)

    class _Check:
        status = CheckStatus.UP

    monkeypatch.setattr(container, "get_check", lambda _name: _Check())
    harness.charm.on.update_status.emit()

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert "N8N_DEFAULT_BINARY_DATA_MODE" not in env
    assert harness.charm.unit.status == ActiveStatus(STATUS_BINARY_DATA_FALLBACK)


def test_binary_data_attached_yields_plain_active(harness, monkeypatch):
    harness.add_storage(BINARY_DATA_STORAGE, attach=True)
    _fully_ready(harness)
    _mute_chown(harness, monkeypatch)
    container = harness.charm.unit.get_container(CONTAINER)

    class _Check:
        status = CheckStatus.UP

    monkeypatch.setattr(container, "get_check", lambda _name: _Check())
    harness.charm.on.update_status.emit()

    assert harness.charm.unit.status == ActiveStatus()


def test_binary_data_detach_clears_mode_in_storage_detaching_handler(harness, monkeypatch):
    """Detach must rebuild the Pebble layer without N8N_DEFAULT_BINARY_DATA_MODE.

    NOTE: We assert immediately after `detach_storage()` because that is when
    the `storage-detaching` event fires. Harness does not invalidate the
    StorageMapping cache on detach (asymmetric with `attach_storage` which
    does), so a *subsequent* reconcile in the same test would incorrectly see
    the storage as still attached. Real Juju re-queries storage-list each
    reconcile, so this Harness quirk does not exist in production.
    """
    storage_ids = harness.add_storage(BINARY_DATA_STORAGE, attach=True)
    _fully_ready(harness)
    _mute_chown(harness, monkeypatch)
    container = harness.charm.unit.get_container(CONTAINER)

    class _Check:
        status = CheckStatus.UP

    monkeypatch.setattr(container, "get_check", lambda _name: _Check())
    harness.charm.on.update_status.emit()
    assert harness.charm.unit.status == ActiveStatus()
    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_DEFAULT_BINARY_DATA_MODE"] == "filesystem"

    harness.detach_storage(storage_ids[0])

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert "N8N_DEFAULT_BINARY_DATA_MODE" not in env
    assert harness.charm.unit.status == ActiveStatus(STATUS_BINARY_DATA_FALLBACK)


# --- S3 binary-data backing (issue #10) ---

S3_RELATION = "s3"
S3_PROVIDER_APP = "s3-integrator"
S3_CREDS = {
    "endpoint": "http://minio.example:9000",
    "bucket": "n8n-k8s",
    "region": "us-east-1",
    "access-key": "AKIA-SENTINEL",
    "secret-key": "SECRET-SENTINEL",
}

S3_ENV_KEYS = (
    "N8N_EXTERNAL_STORAGE_S3_HOST",
    "N8N_EXTERNAL_STORAGE_S3_BUCKET_NAME",
    "N8N_EXTERNAL_STORAGE_S3_BUCKET_REGION",
    "N8N_EXTERNAL_STORAGE_S3_ACCESS_KEY",
    "N8N_EXTERNAL_STORAGE_S3_ACCESS_SECRET",
)


def _add_s3(harness: Harness, data: dict | None = S3_CREDS) -> int:
    rel_id = harness.add_relation(S3_RELATION, S3_PROVIDER_APP)
    if data:
        harness.update_relation_data(rel_id, S3_PROVIDER_APP, data)
    return rel_id


def _force_check_up(monkeypatch) -> None:
    """Patch Container.get_check so the ready check reports UP across reconciles."""
    from ops.model import Container

    class _Check:
        status = CheckStatus.UP

    monkeypatch.setattr(Container, "get_check", lambda self, _name: _Check())


def test_s3_relation_sets_s3_mode_and_env(harness, monkeypatch):
    _fully_ready(harness)
    _add_s3(harness)
    _force_check_up(monkeypatch)
    harness.charm.on.update_status.emit()

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_DEFAULT_BINARY_DATA_MODE"] == "s3"
    assert env["N8N_AVAILABLE_BINARY_DATA_MODES"] == "filesystem,s3"
    for key in S3_ENV_KEYS:
        assert key in env
    assert harness.charm.unit.status == ActiveStatus()


def test_s3_with_storage_attached_s3_wins_with_idle_mount_status(harness, monkeypatch):
    harness.add_storage(BINARY_DATA_STORAGE, attach=True)
    _fully_ready(harness)
    _mute_chown(harness, monkeypatch)
    _add_s3(harness)
    _force_check_up(monkeypatch)
    harness.charm.on.update_status.emit()

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_DEFAULT_BINARY_DATA_MODE"] == "s3"
    assert harness.charm.unit.status == ActiveStatus("binary data: s3 (storage mount idle)")


def test_s3_relation_departed_reverts_to_filesystem(harness, monkeypatch):
    harness.add_storage(BINARY_DATA_STORAGE, attach=True)
    _fully_ready(harness)
    _mute_chown(harness, monkeypatch)
    rel_id = _add_s3(harness)
    _force_check_up(monkeypatch)
    harness.charm.on.update_status.emit()

    harness.remove_relation(rel_id)
    harness.charm.on.update_status.emit()

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_DEFAULT_BINARY_DATA_MODE"] == "filesystem"
    for key in S3_ENV_KEYS:
        assert key not in env
    assert harness.charm.unit.status == ActiveStatus()


def test_s3_relation_departed_reverts_to_fallback(harness, monkeypatch):
    _fully_ready(harness)
    rel_id = _add_s3(harness)
    _force_check_up(monkeypatch)
    harness.charm.on.update_status.emit()

    harness.remove_relation(rel_id)
    harness.charm.on.update_status.emit()

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert "N8N_DEFAULT_BINARY_DATA_MODE" not in env
    assert harness.charm.unit.status == ActiveStatus(STATUS_BINARY_DATA_FALLBACK)


def test_s3_credentials_not_logged_in_plaintext(harness, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="charm")
    _fully_ready(harness)
    _add_s3(harness)
    _force_check_up(monkeypatch)
    harness.charm.on.update_status.emit()

    assert "AKIA-SENTINEL" not in caplog.text
    assert "SECRET-SENTINEL" not in caplog.text
