#!/usr/bin/env python3
"""n8n Kubernetes charm — encryption-key + Postgres relation (issue #3)."""

from __future__ import annotations

import logging
import secrets

import ops
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from ops import main, pebble
from ops.charm import CharmBase
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus

from pebble import build_layer, build_url_env
from relations.ingress import IngressRelation
from state import PEER_RELATION_NAME, CharmState

logger = logging.getLogger(__name__)

CONTAINER_NAME = "n8n"
SERVICE_NAME = "n8n"
DB_RELATION_NAME = "postgresql"
DATABASE_NAME = "n8n"
N8N_PORT = 5678

ENCRYPTION_KEY_SECRET_LABEL = "n8n-encryption-key"
ENCRYPTION_KEY_CONFIG = "encryption-key"


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
        self._ingress = IngressRelation(self, on_change=self._reconcile)

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
        container.add_layer(
            CONTAINER_NAME,
            build_layer(db_env, key, url_env=build_url_env(url)),
            combine=True,
        )
        container.replan()

        try:
            ready = container.get_check("ready")
            if ready.status == pebble.CheckStatus.UP:
                self.unit.status = ActiveStatus()
        except pebble.Error:
            logger.debug("ready check not yet registered")

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
