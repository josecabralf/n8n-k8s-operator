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


def test_build_url_env_returns_five_keys():
    url_env = build_url_env("http://traefik.local/")

    assert set(url_env.keys()) == {
        "N8N_HOST",
        "N8N_PROTOCOL",
        "N8N_PORT",
        "WEBHOOK_URL",
        "N8N_EDITOR_BASE_URL",
    }
    assert url_env["N8N_HOST"] == "traefik.local"
    assert url_env["N8N_PROTOCOL"] == "http"
    assert url_env["N8N_PORT"] == "5678"
    assert url_env["WEBHOOK_URL"] == "http://traefik.local/"
    assert url_env["N8N_EDITOR_BASE_URL"] == "http://traefik.local/"


def test_build_url_env_handles_https_scheme():
    url_env = build_url_env("https://n8n.example.com/")

    assert url_env["N8N_HOST"] == "n8n.example.com"
    assert url_env["N8N_PROTOCOL"] == "http"
    assert url_env["WEBHOOK_URL"] == "https://n8n.example.com/"
    assert url_env["N8N_EDITOR_BASE_URL"] == "https://n8n.example.com/"


def test_build_layer_without_url_env_is_unchanged():
    layer = build_layer({"DB_TYPE": "postgresdb"}, encryption_key="k")

    environment = layer["services"]["n8n"]["environment"]
    assert environment["DB_TYPE"] == "postgresdb"
    assert environment["N8N_ENCRYPTION_KEY"] == "k"
    for key in ("N8N_HOST", "N8N_PROTOCOL", "N8N_PORT", "WEBHOOK_URL", "N8N_EDITOR_BASE_URL"):
        assert key not in environment


def test_build_layer_with_url_env_merges_into_environment():
    layer = build_layer(
        {"DB_TYPE": "postgresdb"},
        encryption_key="k",
        url_env=build_url_env("http://traefik.local/"),
    )

    environment = layer["services"]["n8n"]["environment"]
    assert environment["DB_TYPE"] == "postgresdb"
    assert environment["N8N_ENCRYPTION_KEY"] == "k"
    assert environment["N8N_HOST"] == "traefik.local"
    assert environment["N8N_PROTOCOL"] == "http"
    assert environment["N8N_PORT"] == "5678"
    assert environment["WEBHOOK_URL"] == "http://traefik.local/"
    assert environment["N8N_EDITOR_BASE_URL"] == "http://traefik.local/"


def test_build_layer_includes_binary_data_mode_when_set():
    layer = build_layer(DB_ENV, binary_data_mode="filesystem")

    env = layer["services"]["n8n"]["environment"]
    assert env["N8N_DEFAULT_BINARY_DATA_MODE"] == "filesystem"


def test_build_layer_omits_binary_data_mode_by_default():
    layer = build_layer(DB_ENV)

    env = layer["services"]["n8n"]["environment"]
    assert "N8N_DEFAULT_BINARY_DATA_MODE" not in env


def test_build_layer_pebble_checks_still_target_localhost():
    layer_no_url = build_layer(DB_ENV, encryption_key="k")
    layer_with_url = build_layer(
        DB_ENV,
        encryption_key="k",
        url_env=build_url_env("http://traefik.local/"),
    )

    for layer in (layer_no_url, layer_with_url):
        assert "localhost:5678" in layer["checks"]["live"]["http"]["url"]
        assert "localhost:5678" in layer["checks"]["ready"]["http"]["url"]
