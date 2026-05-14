#!/usr/bin/env python3
"""n8n Kubernetes charm — skeleton (issue #2)."""

from __future__ import annotations

import logging

from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops import main, pebble
from ops.charm import CharmBase
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus

from pebble import build_layer, build_url_env

logger = logging.getLogger(__name__)

CONTAINER_NAME = "n8n"
SERVICE_NAME = "n8n"
DB_RELATION_NAME = "postgresql"
INGRESS_RELATION_NAME = "ingress"
PEER_RELATION_NAME = "n8n-peers"
DATABASE_NAME = "n8n"
N8N_PORT = 5678


class N8nK8sCharm(CharmBase):
    """Skeleton charm: blocked until Postgres relation is joined."""

    def __init__(self, *args):
        super().__init__(*args)
        self.database = DatabaseRequires(
            self,
            relation_name=DB_RELATION_NAME,
            database_name=DATABASE_NAME,
        )
        self.ingress = IngressPerAppRequirer(
            self,
            relation_name=INGRESS_RELATION_NAME,
            port=N8N_PORT,
            strip_prefix=False,
        )
        self.framework.observe(self.ingress.on.ready, self._on_ingress_changed)
        self.framework.observe(self.ingress.on.revoked, self._on_ingress_changed)
        self.framework.observe(
            self.on[INGRESS_RELATION_NAME].relation_broken, self._on_ingress_changed
        )
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.n8n_pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on[DB_RELATION_NAME].relation_created, self._on_database_changed)
        self.framework.observe(self.database.on.database_created, self._on_database_changed)
        self.framework.observe(self.database.on.endpoints_changed, self._on_database_changed)
        self.framework.observe(self.on[DB_RELATION_NAME].relation_broken, self._on_database_broken)

    def _on_install(self, _event) -> None:
        self._reconcile()

    def _on_pebble_ready(self, _event) -> None:
        self._reconcile()

    def _on_update_status(self, _event) -> None:
        self._reconcile()

    def _on_database_changed(self, _event) -> None:
        self._reconcile()

    def _on_ingress_changed(self, _event) -> None:
        self._reconcile()

    def _on_database_broken(self, _event) -> None:
        container = self.unit.get_container(CONTAINER_NAME)
        if container.can_connect():
            try:
                container.stop(SERVICE_NAME)
            except pebble.Error:
                logger.debug("n8n service was not running on relation-broken")
        self.unit.status = BlockedStatus("waiting for postgresql relation")

    def _reconcile(self) -> None:
        db_env = self._db_env()
        if db_env is None:
            if self.model.get_relation(DB_RELATION_NAME) is None:
                self.unit.status = BlockedStatus("waiting for postgresql relation")
            else:
                self.unit.status = WaitingStatus("waiting for database credentials")
            return

        url_env = self._url_env()
        if url_env is None:
            if self.model.get_relation(INGRESS_RELATION_NAME) is None:
                self.unit.status = BlockedStatus("waiting for ingress relation")
            else:
                self.unit.status = WaitingStatus("waiting for ingress url")
            return

        container = self.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            self.unit.status = MaintenanceStatus("waiting for pebble")
            return

        self.unit.status = MaintenanceStatus("starting n8n")
        container.add_layer(CONTAINER_NAME, build_layer({**db_env, **url_env}), combine=True)
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

    def _url_env(self) -> dict | None:
        """Return the URL env-var dict for n8n, or None if ingress isn't ready."""
        url = self.ingress.url
        if not url:
            return None
        return build_url_env(url)


if __name__ == "__main__":  # pragma: no cover
    main(N8nK8sCharm)
