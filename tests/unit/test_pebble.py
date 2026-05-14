"""Unit tests for the Pebble layer builder."""

from __future__ import annotations

from pebble import build_layer, build_url_env

DB_ENV = {
    "DB_TYPE": "postgresdb",
    "DB_POSTGRESDB_HOST": "postgres.example",
    "DB_POSTGRESDB_PORT": "5432",
    "DB_POSTGRESDB_DATABASE": "n8n",
    "DB_POSTGRESDB_USER": "n8n",
    "DB_POSTGRESDB_PASSWORD": "secret",
}


def test_build_layer_returns_n8n_service_with_six_db_env_vars():
    layer = build_layer(DB_ENV)

    service = layer["services"]["n8n"]
    assert service["command"] == "n8n start"
    assert service["environment"] == DB_ENV
    assert len(service["environment"]) == 6


def test_build_layer_environment_is_copied_not_aliased():
    db_env = dict(DB_ENV)
    layer = build_layer(db_env)

    layer["services"]["n8n"]["environment"]["DB_POSTGRESDB_PASSWORD"] = "tampered"

    assert db_env["DB_POSTGRESDB_PASSWORD"] == "secret"


def test_build_layer_has_live_http_check_on_healthz():
    layer = build_layer(DB_ENV)

    live = layer["checks"]["live"]
    assert live["http"]["url"] == "http://localhost:5678/healthz"
    assert live["level"] == "alive"
    assert live["period"] == "30s"


def test_build_layer_has_ready_http_check_on_readiness_endpoint_with_threshold_3():
    layer = build_layer(DB_ENV)

    ready = layer["checks"]["ready"]
    assert ready["http"]["url"] == "http://localhost:5678/healthz/readiness"
    assert ready["level"] == "ready"
    assert ready["period"] == "10s"
    assert ready["threshold"] == 3


def test_build_layer_service_has_replace_override():
    layer = build_layer(DB_ENV)

    assert layer["services"]["n8n"]["override"] == "replace"
    assert layer["checks"]["live"]["override"] == "replace"
    assert layer["checks"]["ready"]["override"] == "replace"


def test_build_url_env_returns_empty_for_none():
    assert build_url_env(None) == {}


def test_build_url_env_returns_empty_for_empty_string():
    assert build_url_env("") == {}


def test_build_url_env_extracts_host_protocol_port():
    env = build_url_env("http://n8n.example.com/")

    assert env["N8N_HOST"] == "n8n.example.com"
    assert env["N8N_PROTOCOL"] == "http"
    assert env["N8N_PORT"] == "5678"


def test_build_url_env_normalises_trailing_slash():
    without_slash = build_url_env("http://n8n.example.com")
    with_slash = build_url_env("http://n8n.example.com/")

    assert without_slash["WEBHOOK_URL"] == "http://n8n.example.com/"
    assert without_slash["N8N_EDITOR_BASE_URL"] == "http://n8n.example.com/"
    assert with_slash["WEBHOOK_URL"] == "http://n8n.example.com/"
    assert with_slash["N8N_EDITOR_BASE_URL"] == "http://n8n.example.com/"


def test_build_url_env_returns_all_five_keys():
    env = build_url_env("http://n8n.example.com/")

    assert set(env.keys()) == {
        "N8N_HOST",
        "N8N_PROTOCOL",
        "N8N_PORT",
        "WEBHOOK_URL",
        "N8N_EDITOR_BASE_URL",
    }


def test_build_layer_takes_merged_env():
    layer = build_layer({"FOO": "bar"})

    assert layer["services"]["n8n"]["environment"] == {"FOO": "bar"}
