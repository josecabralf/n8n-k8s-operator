"""Unit tests for the logging (loki_push_api) relation wiring."""

from __future__ import annotations

from ops.model import ActiveStatus
from ops.pebble import CheckStatus
from ops.testing import Harness

from charms.loki_k8s.v1.loki_push_api import LogForwarder

DB_RELATION = "postgresql"
PEER_RELATION = "n8n-peers"
INGRESS_RELATION = "traefik-route"
LOGGING_RELATION = "logging"
CONTAINER = "n8n"
APP_NAME = "n8n-k8s"
TRAEFIK_APP = "traefik-k8s"
LOKI_APP = "loki-k8s"

DB_DATA = {
    "endpoints": "10.1.2.3:5432",
    "username": "n8n_user",
    "password": "s3cret",
    "database": "n8n",
}
INGRESS_DATA = {"external_host": "traefik.local", "scheme": "http"}


def _begin(harness: Harness) -> None:
    harness.add_relation(PEER_RELATION, APP_NAME)
    harness.begin_with_initial_hooks()


def _add_postgres(harness: Harness) -> int:
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)
    return rel_id


def _add_ingress(harness: Harness) -> int:
    rel_id = harness.add_relation(INGRESS_RELATION, TRAEFIK_APP)
    harness.update_relation_data(rel_id, TRAEFIK_APP, INGRESS_DATA)
    return rel_id


def _fully_ready(harness: Harness) -> None:
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_ingress(harness)
    _add_postgres(harness)


def _force_active(harness: Harness, monkeypatch) -> None:
    """Drive the charm to ActiveStatus by faking the Pebble check as UP."""
    _fully_ready(harness)
    container = harness.charm.unit.get_container(CONTAINER)

    class _Check:
        status = CheckStatus.UP

    monkeypatch.setattr(container, "get_check", lambda _name: _Check())
    harness.charm.on.update_status.emit()


def test_logging_relation_declared(harness):
    harness.begin()
    requires = harness.charm.meta.requires
    assert LOGGING_RELATION in requires
    logging_rel = requires[LOGGING_RELATION]
    assert logging_rel.interface_name == "loki_push_api"
    assert logging_rel.limit == 1


def test_log_forwarder_initialized(harness):
    harness.begin()
    assert hasattr(harness.charm, "_log_forwarder")
    assert isinstance(harness.charm._log_forwarder, LogForwarder)


def test_charm_active_without_logging_relation(harness, monkeypatch):
    _force_active(harness, monkeypatch)
    assert isinstance(harness.charm.unit.status, ActiveStatus)


def test_logging_relation_joined_keeps_active(harness, monkeypatch):
    _force_active(harness, monkeypatch)
    assert isinstance(harness.charm.unit.status, ActiveStatus)

    rel_id = harness.add_relation(LOGGING_RELATION, LOKI_APP)
    harness.add_relation_unit(rel_id, f"{LOKI_APP}/0")
    harness.charm.on.update_status.emit()

    assert isinstance(harness.charm.unit.status, ActiveStatus)


def test_logging_relation_broken_keeps_active(harness, monkeypatch):
    _force_active(harness, monkeypatch)

    rel_id = harness.add_relation(LOGGING_RELATION, LOKI_APP)
    harness.add_relation_unit(rel_id, f"{LOKI_APP}/0")
    harness.remove_relation(rel_id)
    harness.charm.on.update_status.emit()

    assert isinstance(harness.charm.unit.status, ActiveStatus)
