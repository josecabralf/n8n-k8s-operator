"""Unit tests for the Pebble layer builder."""

from __future__ import annotations

from pebble import build_layer

DB_ENV = {
    "DB_TYPE": "postgresdb",
    "DB_POSTGRESDB_HOST": "postgres.example",
    "DB_POSTGRESDB_PORT": "5432",
    "DB_POSTGRESDB_DATABASE": "n8n",
    "DB_POSTGRESDB_USER": "n8n",
    "DB_POSTGRESDB_PASSWORD": "secret",
}


def test_build_layer_returns_n8n_service_with_six_db_env_vars():
    layer = build_layer(DB_ENV, encryption_key="testkey")

    service = layer["services"]["n8n"]
    assert service["command"] == "n8n start"
    for key, value in DB_ENV.items():
        assert service["environment"][key] == value
    assert len(service["environment"]) == 7


def test_build_layer_environment_is_copied_not_aliased():
    db_env = dict(DB_ENV)
    layer = build_layer(db_env, encryption_key="testkey")

    layer["services"]["n8n"]["environment"]["DB_POSTGRESDB_PASSWORD"] = "tampered"

    assert db_env["DB_POSTGRESDB_PASSWORD"] == "secret"


def test_build_layer_has_live_http_check_on_healthz():
    layer = build_layer(DB_ENV, encryption_key="testkey")

    live = layer["checks"]["live"]
    assert live["http"]["url"] == "http://localhost:5678/healthz"
    assert live["level"] == "alive"
    assert live["period"] == "30s"


def test_build_layer_has_ready_http_check_on_readiness_endpoint_with_threshold_3():
    layer = build_layer(DB_ENV, encryption_key="testkey")

    ready = layer["checks"]["ready"]
    assert ready["http"]["url"] == "http://localhost:5678/healthz/readiness"
    assert ready["level"] == "ready"
    assert ready["period"] == "10s"
    assert ready["threshold"] == 3


def test_build_layer_service_has_replace_override():
    layer = build_layer(DB_ENV, encryption_key="testkey")

    assert layer["services"]["n8n"]["override"] == "replace"
    assert layer["checks"]["live"]["override"] == "replace"
    assert layer["checks"]["ready"]["override"] == "replace"


def test_build_layer_injects_n8n_encryption_key():
    layer = build_layer(DB_ENV, encryption_key="testkey")

    environment = layer["services"]["n8n"]["environment"]
    assert environment["N8N_ENCRYPTION_KEY"] == "testkey"
