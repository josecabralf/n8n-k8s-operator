"""Unit tests for src/charm.py — Postgres relation lifecycle + Pebble layer assembly."""

from __future__ import annotations

import json
import logging

import hvac.exceptions
import pytest
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import CheckStatus
from ops.testing import ActionFailed, Harness

from charm import (
    ERR_ALREADY_BOOTSTRAPPED,
    ERR_CONTAINER_NOT_READY,
    ERR_SERVICE_NOT_CONFIGURED,
    STATUS_RESTARTING,
    STATUS_WAITING_N8N,
    N8nK8sCharm,
)
from state import ENCRYPTION_KEY_SECRET_ID, PEER_RELATION_NAME

DB_RELATION = "postgresql"
PEER_RELATION = "n8n-peers"
INGRESS_RELATION = "traefik-route"
CONTAINER = "n8n"
APP_NAME = "n8n"

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


def test_database_created_writes_db_env_into_plan(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_ingress(harness)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    for k, v in EXPECTED_DB_ENV.items():
        assert env[k] == v


def test_database_created_writes_encryption_key_into_plan(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_ingress(harness)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert "N8N_ENCRYPTION_KEY" in env and env["N8N_ENCRYPTION_KEY"]


def test_database_created_registers_healthz_checks(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_ingress(harness)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)

    plan = harness.get_container_pebble_plan(CONTAINER).to_dict()
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


def test_install_creates_app_secret(harness):
    _begin(harness)

    first_id = _stored_secret_id(harness)
    assert first_id is not None and first_id.startswith("secret:")


def test_install_is_idempotent_across_reinstall(harness):
    _begin(harness)
    first_id = _stored_secret_id(harness)

    harness.charm.on.install.emit()

    assert _stored_secret_id(harness) == first_id


def test_install_is_idempotent_across_update_status(harness):
    _begin(harness)
    first_id = _stored_secret_id(harness)

    harness.charm.on.update_status.emit()

    assert _stored_secret_id(harness) == first_id


def test_pebble_env_contains_encryption_key(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_ingress(harness)
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    value = env.get("N8N_ENCRYPTION_KEY")
    # The auto-minted key is a hex token; reading the secret to compare would
    # be a tautology, so assert structural shape instead.
    assert value and isinstance(value, str) and len(value) >= 32


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


def test_get_encryption_key_action_returns_auto_generated_key(harness):
    _begin(harness)

    output = harness.run_action("get-encryption-key")
    value = output.results["encryption-key"]
    # The auto-minted key is a hex token; assert structural shape rather than
    # echoing the stored secret (which would be a tautology).
    assert value and isinstance(value, str) and len(value) >= 32


def test_get_encryption_key_action_returns_override_value(harness):
    _begin(harness)
    user_secret_id = harness.add_user_secret({"value": "OVERRIDE-VALUE"})
    harness.grant_secret(user_secret_id, APP_NAME)
    harness.update_config({"encryption-key": user_secret_id})

    output = harness.run_action("get-encryption-key")
    assert output.results["encryption-key"] == "OVERRIDE-VALUE"


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


# --- Internal task runner (issue #40) ---


def test_task_runner_disabled_by_default_omits_env(harness):
    _fully_ready(harness)

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert "N8N_RUNNERS_ENABLED" not in env
    assert "N8N_RUNNERS_MAX_CONCURRENCY" not in env
    assert "N8N_RUNNERS_TASK_TIMEOUT" not in env


def test_task_runner_enabled_sets_default_env(harness):
    _fully_ready(harness)
    harness.update_config({"task-runner": True})

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_RUNNERS_ENABLED"] == "true"
    assert env["N8N_RUNNERS_MAX_CONCURRENCY"] == "5"
    assert env["N8N_RUNNERS_TASK_TIMEOUT"] == "300"


def test_task_runner_max_concurrency_override_propagates_to_env(harness):
    _fully_ready(harness)
    harness.update_config({"task-runner": True, "runner-max-concurrency": 4})

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_RUNNERS_MAX_CONCURRENCY"] == "4"


def test_task_runner_invalid_max_concurrency_blocks(harness):
    _fully_ready(harness)
    harness.update_config({"task-runner": True, "runner-max-concurrency": 0})

    assert isinstance(harness.charm.unit.status, BlockedStatus)


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


# --- Restart action (issue #35) ---


def test_restart_action_restarts_service(harness):
    _fully_ready(harness)

    container = harness.charm.unit.get_container(CONTAINER)
    original_restart = container.restart
    calls: list[str] = []

    def _wrapped_restart(name, *args, **kwargs):
        calls.append(name)
        return original_restart(name, *args, **kwargs)

    container.restart = _wrapped_restart

    output = harness.run_action("restart")

    assert output.results == {"restarted": True}
    assert calls == ["n8n"]
    # _reconcile() ran afterwards, so we are no longer in the transient status.
    assert harness.charm.unit.status != MaintenanceStatus(STATUS_RESTARTING)
    # Call-through means the service is actually running again.
    assert harness.charm.unit.get_container(CONTAINER).get_service("n8n").is_running()


def test_restart_action_fails_when_container_not_ready(harness):
    _begin(harness)
    harness.set_can_connect(CONTAINER, False)

    with pytest.raises(ActionFailed) as exc_info:
        harness.run_action("restart")
    assert exc_info.value.message == ERR_CONTAINER_NOT_READY


def test_restart_action_fails_when_service_not_in_plan(harness):
    # Connectable container but no postgres → _reconcile() never adds the n8n
    # service layer (stays Blocked), so the service is absent from the plan.
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)

    with pytest.raises(ActionFailed) as exc_info:
        harness.run_action("restart")
    assert exc_info.value.message == ERR_SERVICE_NOT_CONFIGURED


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


def test_binary_data_unattached_omits_mode_from_env(harness, monkeypatch):
    _fully_ready(harness)
    _mute_chown(harness, monkeypatch)
    _force_check_up(monkeypatch)
    harness.charm.on.update_status.emit()

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert "N8N_DEFAULT_BINARY_DATA_MODE" not in env


def test_binary_data_unattached_status_carries_fallback_warning(harness, monkeypatch):
    _fully_ready(harness)
    _mute_chown(harness, monkeypatch)
    _force_check_up(monkeypatch)
    harness.charm.on.update_status.emit()

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
    # Arrange: attached steady state with filesystem mode set.
    storage_ids = harness.add_storage(BINARY_DATA_STORAGE, attach=True)
    _fully_ready(harness)
    _mute_chown(harness, monkeypatch)
    _force_check_up(monkeypatch)
    harness.charm.on.update_status.emit()

    harness.detach_storage(storage_ids[0])

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert "N8N_DEFAULT_BINARY_DATA_MODE" not in env


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


def test_s3_relation_sets_default_mode_to_s3(harness, monkeypatch):
    _fully_ready(harness)
    _add_s3(harness)
    _force_check_up(monkeypatch)
    harness.charm.on.update_status.emit()

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_DEFAULT_BINARY_DATA_MODE"] == "s3"


def test_s3_relation_publishes_s3_env_keys(harness, monkeypatch):
    _fully_ready(harness)
    _add_s3(harness)
    _force_check_up(monkeypatch)
    harness.charm.on.update_status.emit()

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    for key in S3_ENV_KEYS:
        assert key in env


def test_s3_relation_sets_available_modes_to_filesystem_and_s3(harness, monkeypatch):
    _fully_ready(harness)
    _add_s3(harness)
    _force_check_up(monkeypatch)
    harness.charm.on.update_status.emit()

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_AVAILABLE_BINARY_DATA_MODES"] == "filesystem,s3"


def test_s3_relation_reaches_clean_active(harness, monkeypatch):
    _fully_ready(harness)
    _add_s3(harness)
    _force_check_up(monkeypatch)
    harness.charm.on.update_status.emit()

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


def test_s3_relation_departed_reverts_mode_to_filesystem(harness, monkeypatch):
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
    assert harness.charm.unit.status == ActiveStatus()


def test_s3_relation_departed_removes_s3_env_keys(harness, monkeypatch):
    harness.add_storage(BINARY_DATA_STORAGE, attach=True)
    _fully_ready(harness)
    _mute_chown(harness, monkeypatch)
    rel_id = _add_s3(harness)
    _force_check_up(monkeypatch)
    harness.charm.on.update_status.emit()

    harness.remove_relation(rel_id)
    harness.charm.on.update_status.emit()

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    for key in S3_ENV_KEYS:
        assert key not in env


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


# --- Tier 3 environment config (issue #8) ---


def test_environment_env_entry_present_in_plan(harness):
    _fully_ready(harness)
    harness.update_config({"environment": "env:\n  - name: N8N_PUSH_BACKEND\n    value: websocket\n"})

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_PUSH_BACKEND"] == "websocket"
    assert harness.charm.unit.status == ActiveStatus(STATUS_BINARY_DATA_FALLBACK)


def test_environment_juju_entry_with_granted_secret_resolves(harness):
    _fully_ready(harness)
    secret_id = harness.add_user_secret({"token": "abc123"})
    harness.grant_secret(secret_id, APP_NAME)
    harness.update_config(
        {"environment": ("juju:\n" f"  - secret-id: {secret_id}\n" "    name: N8N_API_TOKEN\n" "    key: token\n")}
    )

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_API_TOKEN"] == "abc123"


def test_environment_atomic_juju_failure_blocks_and_skips_user_env(harness):
    _fully_ready(harness)
    granted_id = harness.add_user_secret({"token": "ok"})
    harness.grant_secret(granted_id, APP_NAME)
    ungranted_id = harness.add_user_secret({"token": "blocked"})
    # Do NOT grant ungranted_id.
    harness.update_config(
        {
            "environment": (
                "juju:\n"
                f"  - secret-id: {granted_id}\n"
                "    name: N8N_GOOD\n"
                "    key: token\n"
                f"  - secret-id: {ungranted_id}\n"
                "    name: N8N_BAD\n"
                "    key: token\n"
            )
        }
    )

    assert harness.charm.unit.status == BlockedStatus("environment juju entry 'N8N_BAD': secret not granted")
    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    # Atomic: even the granted entry is skipped.
    assert "N8N_GOOD" not in env
    assert "N8N_BAD" not in env
    # Workload-side charm-managed envs still applied.
    for k, v in EXPECTED_DB_ENV.items():
        assert env[k] == v


def test_environment_juju_entry_with_missing_key_blocks(harness):
    _fully_ready(harness)
    secret_id = harness.add_user_secret({"other-key": "value"})
    harness.grant_secret(secret_id, APP_NAME)
    harness.update_config(
        {"environment": ("juju:\n" f"  - secret-id: {secret_id}\n" "    name: N8N_X\n" "    key: missing-key\n")}
    )

    assert harness.charm.unit.status == BlockedStatus("environment juju entry 'N8N_X': key 'missing-key' not in secret")


def test_environment_charm_managed_ingress_conflict_keeps_charm_value_in_plan(harness, monkeypatch):
    _fully_ready(harness)
    _force_check_up(monkeypatch)
    harness.update_config({"environment": "env:\n  - name: N8N_HOST\n    value: hacked\n"})

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_HOST"] == "traefik.local"


def test_environment_charm_managed_ingress_conflict_surfaces_in_status(harness, monkeypatch):
    _fully_ready(harness)
    _force_check_up(monkeypatch)
    harness.update_config({"environment": "env:\n  - name: N8N_HOST\n    value: hacked\n"})

    status = harness.charm.unit.status
    assert isinstance(status, ActiveStatus)
    assert "ignoring user env overrides: N8N_HOST" in status.message
    assert "see juju debug-log" in status.message


def test_environment_charm_managed_ingress_conflict_logs_remediation_hint(harness, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="charm")
    _fully_ready(harness)
    _force_check_up(monkeypatch)
    harness.update_config({"environment": "env:\n  - name: N8N_HOST\n    value: hacked\n"})

    assert "N8N_HOST" in caplog.text
    assert "ingress relation" in caplog.text


def test_environment_charm_managed_tier1_conflict_surfaces_in_status(harness, monkeypatch):
    _fully_ready(harness)
    _force_check_up(monkeypatch)
    harness.update_config({"environment": "env:\n  - name: N8N_LOG_LEVEL\n    value: debug\n"})

    status = harness.charm.unit.status
    assert isinstance(status, ActiveStatus)
    assert "ignoring user env overrides: N8N_LOG_LEVEL" in status.message


def test_environment_charm_managed_tier1_conflict_logs_config_hint(harness, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="charm")
    _fully_ready(harness)
    _force_check_up(monkeypatch)
    harness.update_config({"environment": "env:\n  - name: N8N_LOG_LEVEL\n    value: debug\n"})

    assert "N8N_LOG_LEVEL" in caplog.text
    assert "log-level" in caplog.text


def test_environment_removing_conflict_returns_to_clean_active(harness, monkeypatch):
    harness.add_storage(BINARY_DATA_STORAGE, attach=True)
    _fully_ready(harness)
    _mute_chown(harness, monkeypatch)
    _force_check_up(monkeypatch)
    harness.update_config({"environment": "env:\n  - name: N8N_HOST\n    value: hacked\n"})

    status = harness.charm.unit.status
    assert isinstance(status, ActiveStatus)
    assert "ignoring user env overrides" in status.message

    harness.update_config({"environment": ""})
    assert harness.charm.unit.status == ActiveStatus()


def test_environment_invalid_yaml_blocks(harness):
    _fully_ready(harness)
    harness.update_config({"environment": "env: [unclosed"})

    status = harness.charm.unit.status
    assert isinstance(status, BlockedStatus)
    assert "environment config" in status.message
    assert "malformed YAML" in status.message


def test_environment_unsupported_top_level_key_blocks(harness):
    _fully_ready(harness)
    harness.update_config({"environment": "random:\n  - x\n"})

    status = harness.charm.unit.status
    assert isinstance(status, BlockedStatus)
    assert "unsupported top-level key" in status.message


# --- Vault-kv environment entries (issue #30) ---

VAULT_RELATION = "vault-k8s"
VAULT_PROVIDER_APP = "vault-k8s"
VAULT_MOUNT = "charm-n8n-n8n"


class _FakeKvV2:
    """Stub for ``hvac.Client.secrets.kv.v2`` used by the resolver."""

    def __init__(self, blobs=None, raise_path=None, raise_read=None):
        self._blobs = blobs or {}
        self._raise_path = raise_path
        self._raise_read = raise_read

    def read_secret_version(self, path, mount_point, raise_on_deleted_version):
        if self._raise_path is not None:
            raise self._raise_path
        if self._raise_read is not None:
            raise self._raise_read
        if path not in self._blobs:
            raise hvac.exceptions.InvalidPath(f"path {path} not found")
        return {"data": {"data": self._blobs[path]}}


class _FakeVaultClient:
    """Minimal stand-in for ``hvac.Client`` exposing only the surface used."""

    def __init__(self, blobs=None, raise_path=None, raise_read=None):
        kv2 = _FakeKvV2(blobs=blobs, raise_path=raise_path, raise_read=raise_read)
        self.secrets = type("S", (), {"kv": type("KV", (), {"v2": kv2})()})()


def _set_up_vault_relation(
    harness: Harness,
    *,
    vault_url: str = "https://vault.example:8200",
    mount: str = VAULT_MOUNT,
    role_id: str = "role-id-XYZ",
    role_secret_id: str = "role-secret-XYZ",
) -> int:
    """Stand up a vault-k8s relation with provider data + unit nonce + creds secret.

    Returns the relation id. Mirrors the shape of vault_kv: app databag
    carries ``vault_url``, ``mount``, and a JSON ``credentials`` map keyed by
    the unit's ``nonce``; the unit databag carries the matching ``nonce``;
    the credentials map points at a Juju secret holding ``role-id`` and
    ``role-secret-id``.
    """
    # The install hook (fired via begin_with_initial_hooks) has already minted
    # the per-unit vault-kv nonce secret. Read it back so we can echo it into
    # the relation databags.
    nonce_secret = harness.charm.model.get_secret(label="vault-kv-nonce")
    nonce = nonce_secret.get_content(refresh=True)["nonce"]

    cred_secret_id = harness.add_user_secret(
        {"role-id": role_id, "role-secret-id": role_secret_id},
    )
    harness.grant_secret(cred_secret_id, APP_NAME)

    rel_id = harness.add_relation(VAULT_RELATION, VAULT_PROVIDER_APP)
    harness.update_relation_data(
        rel_id,
        VAULT_PROVIDER_APP,
        {
            "vault_url": vault_url,
            "mount": mount,
            "credentials": json.dumps({nonce: cred_secret_id}),
        },
    )
    # Mirror the unit nonce into the relation databag (the install handler
    # would normally publish this via request_credentials, but Harness can't
    # resolve the network binding so we set it directly).
    unit_name = f"{APP_NAME}/0"
    harness.update_relation_data(rel_id, unit_name, {"nonce": nonce})
    return rel_id


def test_environment_vault_entry_resolves_into_plan(harness, monkeypatch):
    _fully_ready(harness)
    _set_up_vault_relation(harness)
    monkeypatch.setattr(
        harness.charm,
        "_vault_client_for",
        lambda _rel: _FakeVaultClient(blobs={"myapp": {"api_token": "hunter2"}}),
    )
    _force_check_up(monkeypatch)
    harness.update_config(
        {"environment": ("vault:\n" "  - path: myapp\n" "    name: N8N_API_TOKEN\n" "    key: api_token\n")}
    )

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_API_TOKEN"] == "hunter2"
    assert isinstance(harness.charm.unit.status, ActiveStatus)


def test_environment_vault_missing_relation_blocks(harness):
    _fully_ready(harness)
    # No vault-k8s relation added.
    harness.update_config(
        {"environment": ("vault:\n" "  - path: myapp\n" "    name: N8N_API_TOKEN\n" "    key: api_token\n")}
    )

    assert harness.charm.unit.status == BlockedStatus(
        "environment vault entry 'N8N_API_TOKEN': vault-k8s relation not joined"
    )


def test_environment_vault_missing_relation_omits_target_env(harness):
    _fully_ready(harness)
    harness.update_config(
        {"environment": ("vault:\n" "  - path: myapp\n" "    name: N8N_API_TOKEN\n" "    key: api_token\n")}
    )

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert "N8N_API_TOKEN" not in env


def test_environment_vault_missing_relation_still_applies_charm_env(harness):
    _fully_ready(harness)
    harness.update_config(
        {"environment": ("vault:\n" "  - path: myapp\n" "    name: N8N_API_TOKEN\n" "    key: api_token\n")}
    )

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    for k, v in EXPECTED_DB_ENV.items():
        assert env[k] == v
    assert "N8N_ENCRYPTION_KEY" in env


def test_environment_vault_key_missing_blocks(harness, monkeypatch):
    _fully_ready(harness)
    _set_up_vault_relation(harness)
    monkeypatch.setattr(
        harness.charm,
        "_vault_client_for",
        lambda _rel: _FakeVaultClient(blobs={"myapp": {"other": "x"}}),
    )
    harness.update_config(
        {"environment": ("vault:\n" "  - path: myapp\n" "    name: N8N_API_TOKEN\n" "    key: api_token\n")}
    )

    assert harness.charm.unit.status == BlockedStatus(
        "environment vault entry 'N8N_API_TOKEN': key 'api_token' not in path 'myapp'"
    )
    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert "N8N_API_TOKEN" not in env


def test_environment_vault_path_missing_blocks(harness, monkeypatch):
    _fully_ready(harness)
    _set_up_vault_relation(harness)
    monkeypatch.setattr(
        harness.charm,
        "_vault_client_for",
        lambda _rel: _FakeVaultClient(raise_path=hvac.exceptions.InvalidPath("nope")),
    )
    harness.update_config(
        {"environment": ("vault:\n" "  - path: myapp\n" "    name: N8N_API_TOKEN\n" "    key: api_token\n")}
    )

    assert harness.charm.unit.status == BlockedStatus("environment vault entry 'N8N_API_TOKEN': path 'myapp' not found")
    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert "N8N_API_TOKEN" not in env


def test_environment_vault_overrides_juju_in_plan(harness, monkeypatch):
    _fully_ready(harness)
    _set_up_vault_relation(harness)
    monkeypatch.setattr(
        harness.charm,
        "_vault_client_for",
        lambda _rel: _FakeVaultClient(blobs={"myapp": {"k": "from-vault"}}),
    )
    _force_check_up(monkeypatch)

    juju_secret_id = harness.add_user_secret({"key1": "from-juju"})
    harness.grant_secret(juju_secret_id, APP_NAME)
    harness.update_config(
        {
            "environment": (
                "juju:\n"
                f"  - secret-id: {juju_secret_id}\n"
                "    name: N8N_X\n"
                "    key: key1\n"
                "vault:\n"
                "  - path: myapp\n"
                "    name: N8N_X\n"
                "    key: k\n"
            )
        }
    )

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_X"] == "from-vault"
    assert isinstance(harness.charm.unit.status, ActiveStatus)


def _vault_atomic_failure_setup(harness, monkeypatch):
    """Arrange: two vault entries where the second's key is missing."""
    _fully_ready(harness)
    _set_up_vault_relation(harness)
    monkeypatch.setattr(
        harness.charm,
        "_vault_client_for",
        lambda _rel: _FakeVaultClient(
            blobs={"path-a": {"k": "v-a"}, "path-b": {"unrelated": "x"}},
        ),
    )
    harness.update_config(
        {
            "environment": (
                "vault:\n"
                "  - path: path-a\n"
                "    name: N8N_GOOD\n"
                "    key: k\n"
                "  - path: path-b\n"
                "    name: N8N_BAD\n"
                "    key: k\n"
            )
        }
    )


def test_environment_vault_atomic_failure_blocks(harness, monkeypatch):
    _vault_atomic_failure_setup(harness, monkeypatch)

    assert harness.charm.unit.status == BlockedStatus("environment vault entry 'N8N_BAD': key 'k' not in path 'path-b'")


def test_environment_vault_atomic_failure_drops_both_entries(harness, monkeypatch):
    _vault_atomic_failure_setup(harness, monkeypatch)

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert "N8N_GOOD" not in env
    assert "N8N_BAD" not in env


def test_environment_vault_atomic_failure_still_applies_charm_env(harness, monkeypatch):
    _vault_atomic_failure_setup(harness, monkeypatch)

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    for k, v in EXPECTED_DB_ENV.items():
        assert env[k] == v
    assert "N8N_ENCRYPTION_KEY" in env


def _fake_binding(egress: list[str], interface_subnet: str | None):
    """Build a fake Binding with the network surface _request_vault_credentials touches.

    Mirrors ``ops.Binding.network.egress_subnets`` (list of ipaddress networks)
    and ``ops.Binding.network.interfaces[0].subnet`` (the pod-interface CIDR
    that K8s charms must include — see vault_kv lib docstring example).
    """
    import ipaddress

    egress_nets = [ipaddress.ip_network(s) for s in egress]
    interfaces = []
    if interface_subnet is not None:
        iface = type("Iface", (), {"subnet": ipaddress.ip_network(interface_subnet)})()
        interfaces = [iface]
    network = type("Net", (), {"egress_subnets": egress_nets, "interfaces": interfaces})()
    return type("Binding", (), {"network": network})()


def test_request_vault_credentials_appends_pod_interface_subnet(harness, monkeypatch):
    """K8s pod-IP fix: subnets sent to vault-kv must include the pod interface CIDR.

    On K8s, ``binding.network.egress_subnets`` returns the application's
    ClusterIP, not the pod IP the workload calls vault from. The charm must
    also append ``binding.network.interfaces[0].subnet`` so vault's AppRole
    CIDR allow-list covers the actual source address. Regression guard for
    issue #30.
    """
    _fully_ready(harness)
    rel_id = _set_up_vault_relation(harness)
    relation = harness.charm.model.get_relation(VAULT_RELATION, rel_id)

    monkeypatch.setattr(
        harness.charm.model,
        "get_binding",
        lambda _rel: _fake_binding(egress=["10.152.183.135/32"], interface_subnet="10.1.95.0/24"),
    )
    captured: dict = {}
    monkeypatch.setattr(
        harness.charm._vault_kv,
        "request_credentials",
        lambda rel, subnets, nonce: captured.update(rel=rel, subnets=subnets, nonce=nonce),
    )

    harness.charm._request_vault_credentials(relation)

    assert captured["subnets"] == ["10.152.183.135/32", "10.1.95.0/24"]


def test_request_vault_credentials_without_interfaces_only_sends_egress(harness, monkeypatch):
    """When the binding has no interfaces (e.g. VM clouds), only egress subnets are sent.

    Guards against an over-eager fix that would crash on bindings whose
    ``network.interfaces`` is empty.
    """
    _fully_ready(harness)
    rel_id = _set_up_vault_relation(harness)
    relation = harness.charm.model.get_relation(VAULT_RELATION, rel_id)

    monkeypatch.setattr(
        harness.charm.model,
        "get_binding",
        lambda _rel: _fake_binding(egress=["192.0.2.0/24"], interface_subnet=None),
    )
    captured: dict = {}
    monkeypatch.setattr(
        harness.charm._vault_kv,
        "request_credentials",
        lambda rel, subnets, nonce: captured.update(rel=rel, subnets=subnets, nonce=nonce),
    )

    harness.charm._request_vault_credentials(relation)

    assert captured["subnets"] == ["192.0.2.0/24"]
