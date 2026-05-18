#!/usr/bin/env python3
"""n8n Kubernetes charm — encryption-key + Postgres relation (issue #3)."""

from __future__ import annotations

import json
import logging
import secrets
import urllib.error
import urllib.request

import bcrypt
import ops
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from ops import main, pebble
from ops.charm import CharmBase
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus

from pebble import build_layer, build_tier1_env, build_url_env
from relations.ingress import IngressRelation
from state import PEER_RELATION_NAME, CharmState

logger = logging.getLogger(__name__)

CONTAINER_NAME = "n8n"
SERVICE_NAME = "n8n"
DB_RELATION_NAME = "postgresql"
METRICS_RELATION_NAME = "metrics-endpoint"
DATABASE_NAME = "n8n"
N8N_PORT = 5678

ENCRYPTION_KEY_SECRET_LABEL = "n8n-encryption-key"
ENCRYPTION_KEY_CONFIG = "encryption-key"

OWNER_PROBE_PATH = "/rest/settings"
OWNER_PROBE_TIMEOUT_S = 3

STATUS_AWAITING_OWNER = "awaiting admin: run create-admin action or visit /setup"
ERR_ALREADY_BOOTSTRAPPED = "owner already exists; use n8n UI to manage users"
ERR_NOT_LEADER = "create-admin must run on the leader unit"
ERR_PEER_NOT_READY = "peer relation not yet joined; retry"
ERR_CONTAINER_NOT_READY = "n8n container not yet connectable"


class N8nK8sCharm(CharmBase):
    """Charm: manages Postgres relation, app-owned encryption-key secret, and pebble layer."""

    def __init__(self, *args):
        super().__init__(*args)
        self.database = DatabaseRequires(
            self,
            relation_name=DB_RELATION_NAME,
            database_name=DATABASE_NAME,
        )
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.n8n_pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.secret_changed, self._on_secret_changed)
        self.framework.observe(self.on[PEER_RELATION_NAME].relation_created, self._on_peer_created)
        self.framework.observe(self.on[DB_RELATION_NAME].relation_created, self._on_database_changed)
        self.framework.observe(self.database.on.database_created, self._on_database_changed)
        self.framework.observe(self.database.on.endpoints_changed, self._on_database_changed)
        self.framework.observe(self.on[DB_RELATION_NAME].relation_broken, self._on_database_broken)
        self.framework.observe(self.on.get_encryption_key_action, self._on_get_encryption_key_action)
        self.framework.observe(self.on.create_admin_action, self._on_create_admin_action)
        self._ingress = IngressRelation(self, on_change=self._reconcile)
        self._metrics = MetricsEndpointProvider(
            self,
            relation_name=METRICS_RELATION_NAME,
            jobs=[{"static_configs": [{"targets": [f"*:{N8N_PORT}"]}]}],
            refresh_event=self.on.config_changed,
        )
        self.framework.observe(self.on[METRICS_RELATION_NAME].relation_created, self._on_metrics_changed)
        self.framework.observe(self.on[METRICS_RELATION_NAME].relation_broken, self._on_metrics_changed)

    def _on_install(self, _event) -> None:
        self._reconcile()

    def _on_config_changed(self, _event) -> None:
        self._reconcile()

    def _on_pebble_ready(self, _event) -> None:
        self._reconcile()

    def _on_update_status(self, _event) -> None:
        self._reconcile()

    def _on_secret_changed(self, _event) -> None:
        self._reconcile()

    def _on_peer_created(self, _event) -> None:
        self._reconcile()

    def _on_database_changed(self, _event) -> None:
        self._reconcile()

    def _on_metrics_changed(self, _event) -> None:
        self._reconcile()

    def _on_database_broken(self, _event) -> None:
        container = self.unit.get_container(CONTAINER_NAME)
        if container.can_connect():
            try:
                container.stop(SERVICE_NAME)
            except pebble.Error:
                logger.debug("n8n service was not running on relation-broken")
        self.unit.status = BlockedStatus("waiting for postgresql relation")

    def _on_get_encryption_key_action(self, event: ops.ActionEvent) -> None:
        key, msg = self._effective_encryption_key()
        if key is None:
            event.fail(msg or "encryption key not yet available")
            return
        event.set_results({"encryption-key": key})

    def _on_create_admin_action(self, event: ops.ActionEvent) -> None:
        if not self.unit.is_leader():
            event.fail(ERR_NOT_LEADER)
            return
        state = CharmState(self)
        if state.peer_relation is None:
            event.fail(ERR_PEER_NOT_READY)
            return

        container = self.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            event.fail(ERR_CONTAINER_NOT_READY)
            return

        probed = self._probe_owner_setup()
        if probed is True or (probed is None and state.owner_bootstrapped):
            event.fail(ERR_ALREADY_BOOTSTRAPPED)
            return

        email = event.params["email"]
        first_name = event.params["first-name"]
        last_name = event.params["last-name"]
        password_hash = bcrypt.hashpw(event.params["password"].encode(), bcrypt.gensalt(rounds=10)).decode()

        container.add_layer(
            "n8n-bootstrap",
            {
                "summary": "n8n owner bootstrap",
                "services": {
                    "n8n": {
                        "override": "merge",
                        "environment": {
                            "N8N_INSTANCE_OWNER_MANAGED_BY_ENV": "true",
                            "N8N_INSTANCE_OWNER_EMAIL": email,
                            "N8N_INSTANCE_OWNER_FIRST_NAME": first_name,
                            "N8N_INSTANCE_OWNER_LAST_NAME": last_name,
                            "N8N_INSTANCE_OWNER_PASSWORD_HASH": password_hash,
                        },
                    }
                },
            },
            combine=True,
        )
        container.replan()

        state.owner_bootstrapped = True
        event.set_results({"created": True, "email": email})

    def _effective_encryption_key(self) -> tuple[str | None, str | None]:
        """Return (key, blocked_msg).

        - (key, None): success.
        - (None, msg): terminal Blocked condition.
        - (None, None): not-yet-ready; caller should emit WaitingStatus.
        """
        override = self.config.get(ENCRYPTION_KEY_CONFIG)
        if override:
            try:
                secret = self.model.get_secret(id=override)
                content = secret.get_content(refresh=True)
            except (ops.SecretNotFoundError, ops.ModelError):
                return (None, "encryption-key secret not granted to app")
            value = content.get("value")
            if not value:
                return (None, "encryption-key secret missing 'value' field")
            return (value, None)

        state = CharmState(self)
        if state.peer_relation is None:
            return (None, None)

        if state.encryption_key_secret_id is None:
            if not self.unit.is_leader():
                return (None, None)
            generated = secrets.token_hex(24)
            secret = self.app.add_secret(
                content={"value": generated},
                label=ENCRYPTION_KEY_SECRET_LABEL,
            )
            state.encryption_key_secret_id = secret.id
            return (generated, None)

        try:
            secret = self.model.get_secret(id=state.encryption_key_secret_id)
            content = secret.get_content()
        except (ops.SecretNotFoundError, ops.ModelError):
            return (None, "stored encryption-key secret is missing")
        value = content.get("value")
        if not value:
            return (None, "stored encryption-key secret missing 'value' field")
        return (value, None)

    def _reconcile(self) -> None:
        key, blocked_msg = self._effective_encryption_key()
        if blocked_msg is not None:
            self.unit.status = BlockedStatus(blocked_msg)
            return
        if key is None:
            self.unit.status = WaitingStatus("waiting for encryption key")
            return

        tier1_env, tier1_err = build_tier1_env(self.config)
        if tier1_err is not None:
            self.unit.status = BlockedStatus(tier1_err)
            return

        db_env = self._db_env()
        if db_env is None:
            if self.model.get_relation(DB_RELATION_NAME) is None:
                self.unit.status = BlockedStatus("waiting for postgresql relation")
            else:
                self.unit.status = WaitingStatus("waiting for database credentials")
            return

        if not self._ingress.is_related():
            self.unit.status = BlockedStatus("waiting for ingress relation")
            return
        url = self._ingress.url
        if not url:
            self.unit.status = WaitingStatus("waiting for ingress url")
            return
        self._ingress.publish_route()

        container = self.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            self.unit.status = MaintenanceStatus("waiting for pebble")
            return

        self.unit.status = MaintenanceStatus("starting n8n")
        metrics_env = {"N8N_METRICS": "true"} if self.model.get_relation(METRICS_RELATION_NAME) is not None else None
        container.add_layer(
            CONTAINER_NAME,
            build_layer(
                db_env,
                key,
                url_env=build_url_env(url),
                tier1_env=tier1_env,
                metrics_env=metrics_env,
            ),
            combine=True,
        )
        container.replan()

        state = CharmState(self)
        if state.owner_bootstrapped:
            owner_exists: bool | None = True
        else:
            owner_exists = self._probe_owner_setup()
            if owner_exists is True and state.peer_relation is not None and self.unit.is_leader():
                state.owner_bootstrapped = True

        self.unit.status = ActiveStatus(STATUS_AWAITING_OWNER if owner_exists is False else "")

    def _probe_owner_setup(self) -> bool | None:
        """True → owner exists; False → not yet; None → cannot tell."""
        url = f"http://localhost:{N8N_PORT}{OWNER_PROBE_PATH}"
        try:
            with urllib.request.urlopen(url, timeout=OWNER_PROBE_TIMEOUT_S) as r:
                payload = json.loads(r.read().decode("utf-8"))
            data = payload.get("data", payload)
            show_setup = data["userManagement"]["showSetupOnFirstLoad"]
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
            logger.debug("owner-setup probe inconclusive: %s", exc)
            return None
        return not bool(show_setup)

    def _db_env(self) -> dict | None:
        """Return the Postgres env-var dict for n8n, or None if not ready."""
        rel = self.model.get_relation(DB_RELATION_NAME)
        if rel is None:
            return None
        per_rel = self.database.fetch_relation_data().get(rel.id, {})
        endpoints = per_rel.get("endpoints")
        username = per_rel.get("username")
        password = per_rel.get("password")
        if not endpoints or not username or not password:
            return None
        host, _, port = endpoints.split(",")[0].partition(":")
        return {
            "DB_TYPE": "postgresdb",
            "DB_POSTGRESDB_HOST": host,
            "DB_POSTGRESDB_PORT": port or "5432",
            "DB_POSTGRESDB_DATABASE": per_rel.get("database") or DATABASE_NAME,
            "DB_POSTGRESDB_USER": username,
            "DB_POSTGRESDB_PASSWORD": password,
        }


if __name__ == "__main__":  # pragma: no cover
    main(N8nK8sCharm)
