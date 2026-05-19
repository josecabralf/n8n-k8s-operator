"""Unit tests for the grafana-dashboard provider relation."""

from __future__ import annotations

import json
from pathlib import Path

from ops.testing import Harness

DB_RELATION = "postgresql"
PEER_RELATION = "n8n-peers"
INGRESS_RELATION = "traefik-route"
CONTAINER = "n8n"
APP_NAME = "n8n-k8s"
TRAEFIK_APP = "traefik-k8s"
GRAFANA_RELATION = "grafana-dashboard"
GRAFANA_APP = "grafana-k8s"

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


def test_dashboard_json_is_valid():
    dashboard_path = Path(__file__).resolve().parents[2] / "src" / "grafana_dashboards" / "n8n.json"
    data = json.loads(dashboard_path.read_text())
    assert "panels" in data
    assert len(data["panels"]) >= 3
    assert data["schemaVersion"] == 35


def test_grafana_dashboard_relation_publishes_dashboard(harness):
    _fully_ready(harness)
    rel_id = harness.add_relation(GRAFANA_RELATION, GRAFANA_APP)
    harness.add_relation_unit(rel_id, f"{GRAFANA_APP}/0")

    app_data = harness.get_relation_data(rel_id, APP_NAME)
    assert app_data
    assert "dashboards" in app_data or "templates" in app_data
