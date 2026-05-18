"""Unit tests for the metrics-endpoint (prometheus_scrape) relation wiring."""

from __future__ import annotations

import json

from ops.testing import Harness

DB_RELATION = "postgresql"
PEER_RELATION = "n8n-peers"
INGRESS_RELATION = "traefik-route"
METRICS_RELATION = "metrics-endpoint"
CONTAINER = "n8n"
APP_NAME = "n8n-k8s"
TRAEFIK_APP = "traefik-k8s"
PROMETHEUS_APP = "prometheus-k8s"

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


def _env(harness: Harness) -> dict[str, str]:
    return harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]


def test_active_path_without_metrics_relation_omits_n8n_metrics(harness):
    _fully_ready(harness)
    assert "N8N_METRICS" not in _env(harness)


def test_metrics_relation_joined_sets_n8n_metrics_true(harness):
    _fully_ready(harness)
    harness.add_relation(METRICS_RELATION, PROMETHEUS_APP)
    assert _env(harness)["N8N_METRICS"] == "true"


def test_metrics_relation_broken_removes_n8n_metrics(harness):
    _fully_ready(harness)
    rel_id = harness.add_relation(METRICS_RELATION, PROMETHEUS_APP)
    assert _env(harness)["N8N_METRICS"] == "true"

    harness.remove_relation(rel_id)
    assert "N8N_METRICS" not in _env(harness)


def test_scrape_jobs_published_to_relation_data(harness):
    _fully_ready(harness)
    rel_id = harness.add_relation(METRICS_RELATION, PROMETHEUS_APP)
    harness.add_relation_unit(rel_id, f"{PROMETHEUS_APP}/0")

    app_data = harness.get_relation_data(rel_id, APP_NAME)
    assert "scrape_jobs" in app_data
    jobs = json.loads(app_data["scrape_jobs"])
    assert isinstance(jobs, list) and jobs
    assert jobs[0]["static_configs"][0]["targets"] == ["*:5678"]


def test_reaches_active_without_metrics_relation(harness, monkeypatch):
    from ops.model import ActiveStatus
    from ops.pebble import CheckStatus

    _fully_ready(harness)
    container = harness.charm.unit.get_container(CONTAINER)

    class _Check:
        status = CheckStatus.UP

    monkeypatch.setattr(container, "get_check", lambda _name: _Check())
    harness.charm.on.update_status.emit()
    assert harness.charm.unit.status == ActiveStatus()
