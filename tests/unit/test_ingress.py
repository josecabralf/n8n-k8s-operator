"""Unit tests for the ingress (traefik-route) relation wiring."""

from __future__ import annotations

import yaml
from ops.model import BlockedStatus
from ops.testing import Harness

from charm import N8nK8sCharm

DB_RELATION = "postgresql"
PEER_RELATION = "n8n-peers"
INGRESS_RELATION = "traefik-route"
CONTAINER = "n8n"
APP_NAME = "n8n"
TRAEFIK_APP = "traefik-k8s"

DB_DATA = {
    "endpoints": "10.1.2.3:5432",
    "username": "n8n_user",
    "password": "s3cret",
    "database": "n8n",
}


def _begin(harness: Harness) -> None:
    harness.add_relation(PEER_RELATION, APP_NAME)
    harness.begin_with_initial_hooks()


def _add_postgres(harness: Harness) -> int:
    rel_id = harness.add_relation(DB_RELATION, "postgresql-k8s")
    harness.update_relation_data(rel_id, "postgresql-k8s", DB_DATA)
    return rel_id


def test_blocked_without_ingress_even_with_postgres(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_postgres(harness)
    assert harness.charm.unit.status == BlockedStatus("waiting for ingress relation")


def test_publishes_route_with_app_name_fallback_when_host_not_yet_set(harness, monkeypatch):
    # With no external_host published yet, the route is still submitted using
    # app.name as a fallback host so the workload starts immediately.
    monkeypatch.setattr(N8nK8sCharm, "_probe_owner_setup", lambda self: True)
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_postgres(harness)
    rel_id = harness.add_relation(INGRESS_RELATION, TRAEFIK_APP)

    app_data = harness.get_relation_data(rel_id, APP_NAME)
    assert "config" in app_data and app_data["config"]
    parsed = yaml.safe_load(app_data["config"])
    router = next(iter(parsed["http"]["routers"].values()))
    assert f"Host(`{APP_NAME}`)" in router["rule"]


def test_pebble_env_uses_app_name_fallback_when_host_not_yet_set(harness, monkeypatch):
    monkeypatch.setattr(N8nK8sCharm, "_probe_owner_setup", lambda self: True)
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_postgres(harness)
    harness.add_relation(INGRESS_RELATION, TRAEFIK_APP)

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_HOST"] == APP_NAME
    assert env["WEBHOOK_URL"] == f"http://{APP_NAME}/"
    assert env["N8N_EDITOR_BASE_URL"] == f"http://{APP_NAME}/"


def test_url_arrives_later_replans_with_real_host(harness, monkeypatch):
    monkeypatch.setattr(N8nK8sCharm, "_probe_owner_setup", lambda self: True)
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_postgres(harness)
    rel_id = harness.add_relation(INGRESS_RELATION, TRAEFIK_APP)

    harness.update_relation_data(rel_id, TRAEFIK_APP, {"external_host": "traefik.local", "scheme": "http"})

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_HOST"] == "traefik.local"
    assert env["WEBHOOK_URL"] == "http://traefik.local/"
    assert env["N8N_EDITOR_BASE_URL"] == "http://traefik.local/"


def test_active_when_host_and_scheme_published_env_vars_in_plan(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_postgres(harness)
    rel_id = harness.add_relation(INGRESS_RELATION, TRAEFIK_APP)
    harness.update_relation_data(rel_id, TRAEFIK_APP, {"external_host": "traefik.local", "scheme": "http"})

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_HOST"] == "traefik.local"
    assert env["N8N_PROTOCOL"] == "http"
    assert env["N8N_PORT"] == "5678"
    assert env["WEBHOOK_URL"] == "http://traefik.local/"
    assert env["N8N_EDITOR_BASE_URL"] == "http://traefik.local/"


def test_active_when_host_and_scheme_published_probes_target_localhost(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_postgres(harness)
    rel_id = harness.add_relation(INGRESS_RELATION, TRAEFIK_APP)
    harness.update_relation_data(rel_id, TRAEFIK_APP, {"external_host": "traefik.local", "scheme": "http"})

    plan = harness.get_container_pebble_plan(CONTAINER).to_dict()
    assert "localhost:5678" in plan["checks"]["live"]["http"]["url"]
    assert "localhost:5678" in plan["checks"]["ready"]["http"]["url"]


def test_leader_publishes_host_routed_config(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_postgres(harness)
    rel_id = harness.add_relation(INGRESS_RELATION, TRAEFIK_APP)
    harness.update_relation_data(rel_id, TRAEFIK_APP, {"external_host": "traefik.local", "scheme": "http"})

    app_data = harness.get_relation_data(rel_id, APP_NAME)
    assert "config" in app_data and app_data["config"]
    parsed = yaml.safe_load(app_data["config"])

    routers = parsed["http"]["routers"]
    assert len(routers) == 1
    router = next(iter(routers.values()))
    assert "Host(`traefik.local`)" in router["rule"]

    services = parsed["http"]["services"]
    service = next(iter(services.values()))
    server_url = service["loadBalancer"]["servers"][0]["url"]
    model = harness.charm.model.name
    assert f"{APP_NAME}-endpoints.{model}.svc.cluster.local:5678" in server_url


def test_non_leader_does_not_publish(harness):
    # Begin as leader so the encryption-key secret is minted and stored.
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_postgres(harness)

    # Demote to follower BEFORE the ingress relation is wired so the
    # reconcile triggered by ingress events runs as non-leader.
    harness.set_leader(False)
    rel_id = harness.add_relation(INGRESS_RELATION, TRAEFIK_APP)
    harness.update_relation_data(rel_id, TRAEFIK_APP, {"external_host": "traefik.local", "scheme": "http"})

    app_data = harness.get_relation_data(rel_id, APP_NAME)
    assert not app_data.get("config")


def test_url_change_replans_with_new_host(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_postgres(harness)
    rel_id = harness.add_relation(INGRESS_RELATION, TRAEFIK_APP)
    harness.update_relation_data(rel_id, TRAEFIK_APP, {"external_host": "traefik.local", "scheme": "http"})
    harness.update_relation_data(rel_id, TRAEFIK_APP, {"external_host": "new.example.com", "scheme": "http"})

    env = harness.get_container_pebble_plan(CONTAINER).to_dict()["services"]["n8n"]["environment"]
    assert env["N8N_HOST"] == "new.example.com"
    assert env["WEBHOOK_URL"] == "http://new.example.com/"
    assert env["N8N_EDITOR_BASE_URL"] == "http://new.example.com/"


def test_relation_broken_returns_to_blocked(harness):
    _begin(harness)
    harness.container_pebble_ready(CONTAINER)
    _add_postgres(harness)
    rel_id = harness.add_relation(INGRESS_RELATION, TRAEFIK_APP)
    harness.update_relation_data(rel_id, TRAEFIK_APP, {"external_host": "traefik.local", "scheme": "http"})

    harness.remove_relation(rel_id)
    assert harness.charm.unit.status == BlockedStatus("waiting for ingress relation")
