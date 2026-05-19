"""Unit tests for the Pebble layer builder."""

from __future__ import annotations

from pebble import (
    build_layer,
    build_s3_env,
    build_smtp_env,
    build_tier1_env,
    build_url_env,
)

S3_CREDS = {
    "endpoint": "http://minio.example:9000",
    "bucket": "n8n",
    "region": "us-east-1",
    "access-key": "AKIAEXAMPLE",
    "secret-key": "sssecret",
}

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


def test_build_layer_with_metrics_env_sets_n8n_metrics():
    layer = build_layer(
        {"DB_TYPE": "postgresdb"},
        encryption_key="k",
        metrics_env={"N8N_METRICS": "true"},
    )

    assert layer["services"]["n8n"]["environment"]["N8N_METRICS"] == "true"


def test_build_layer_without_metrics_env_omits_n8n_metrics():
    layer = build_layer({"DB_TYPE": "postgresdb"}, encryption_key="k")

    assert "N8N_METRICS" not in layer["services"]["n8n"]["environment"]


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


def test_build_tier1_env_defaults_match_n8n_upstream():
    env, err = build_tier1_env({})

    assert err is None
    assert env == {
        "N8N_LOG_LEVEL": "info",
        "GENERIC_TIMEZONE": "UTC",
        "TZ": "UTC",
        "EXECUTIONS_DATA_PRUNE": "false",
        "EXECUTIONS_DATA_MAX_AGE": "336",
        "EXECUTIONS_DATA_SAVE_ON_ERROR": "all",
        "EXECUTIONS_DATA_SAVE_ON_SUCCESS": "all",
        "EXECUTIONS_DATA_SAVE_ON_PROGRESS": "false",
        "N8N_USER_MANAGEMENT_DISABLED": "false",
    }


def test_build_tier1_env_log_level_override():
    env, err = build_tier1_env({"log-level": "debug"})

    assert err is None
    assert env is not None
    assert env["N8N_LOG_LEVEL"] == "debug"


def test_build_tier1_env_timezone_sets_both_env_vars():
    env, err = build_tier1_env({"timezone": "Europe/Madrid"})

    assert err is None
    assert env is not None
    assert env["GENERIC_TIMEZONE"] == "Europe/Madrid"
    assert env["TZ"] == "Europe/Madrid"


def test_build_tier1_env_invalid_log_level_returns_error():
    env, err = build_tier1_env({"log-level": "garbage"})

    assert env is None
    assert err is not None
    assert err.startswith("invalid log-level 'garbage'")


def test_build_tier1_env_invalid_save_on_error_returns_error():
    env, err = build_tier1_env({"executions-data-save-on-error": "maybe"})

    assert env is None
    assert err is not None
    assert "invalid executions-data-save-on-error 'maybe'" in err


def test_build_tier1_env_negative_max_age_returns_error():
    env, err = build_tier1_env({"executions-data-max-age-hours": -1})

    assert env is None
    assert err == "executions-data-max-age-hours must be >= 0"


def test_build_tier1_env_disable_user_registration_true_sets_env():
    env, err = build_tier1_env({"disable-user-registration": True})

    assert err is None
    assert env is not None
    assert env["N8N_USER_MANAGEMENT_DISABLED"] == "true"


def test_build_layer_merges_tier1_env():
    layer = build_layer(DB_ENV, tier1_env={"N8N_LOG_LEVEL": "debug"})

    assert layer["services"]["n8n"]["environment"]["N8N_LOG_LEVEL"] == "debug"


def test_build_s3_env_returns_seven_n8n_env_vars():
    env = build_s3_env(S3_CREDS)

    assert env == {
        "N8N_AVAILABLE_BINARY_DATA_MODES": "filesystem,s3",
        "N8N_EXTERNAL_STORAGE_S3_HOST": "http://minio.example:9000",
        "N8N_EXTERNAL_STORAGE_S3_BUCKET_NAME": "n8n",
        "N8N_EXTERNAL_STORAGE_S3_BUCKET_REGION": "us-east-1",
        "N8N_EXTERNAL_STORAGE_S3_ACCESS_KEY": "AKIAEXAMPLE",
        "N8N_EXTERNAL_STORAGE_S3_ACCESS_SECRET": "sssecret",
    }


def test_build_s3_env_returns_empty_when_any_required_key_missing():
    for key in ("endpoint", "bucket", "region", "access-key", "secret-key"):
        partial = {k: v for k, v in S3_CREDS.items() if k != key}
        assert build_s3_env(partial) == {}, f"missing {key} must return empty"


def test_build_s3_env_returns_empty_when_required_key_blank():
    blank_secret = dict(S3_CREDS, **{"secret-key": ""})

    assert build_s3_env(blank_secret) == {}


def test_build_layer_with_s3_env_merges_into_environment():
    s3_env = build_s3_env(S3_CREDS)

    layer = build_layer(
        DB_ENV,
        encryption_key="k",
        s3_env=s3_env,
        binary_data_mode="s3",
    )

    env = layer["services"]["n8n"]["environment"]
    assert env["N8N_DEFAULT_BINARY_DATA_MODE"] == "s3"
    assert env["N8N_EXTERNAL_STORAGE_S3_HOST"] == "http://minio.example:9000"
    assert env["N8N_EXTERNAL_STORAGE_S3_BUCKET_NAME"] == "n8n"
    assert env["N8N_EXTERNAL_STORAGE_S3_BUCKET_REGION"] == "us-east-1"
    assert env["N8N_EXTERNAL_STORAGE_S3_ACCESS_KEY"] == "AKIAEXAMPLE"
    assert env["N8N_EXTERNAL_STORAGE_S3_ACCESS_SECRET"] == "sssecret"
    assert env["N8N_AVAILABLE_BINARY_DATA_MODES"] == "filesystem,s3"


def test_build_layer_without_s3_env_omits_s3_keys():
    layer = build_layer(DB_ENV, encryption_key="k")

    env = layer["services"]["n8n"]["environment"]
    for key in (
        "N8N_AVAILABLE_BINARY_DATA_MODES",
        "N8N_EXTERNAL_STORAGE_S3_HOST",
        "N8N_EXTERNAL_STORAGE_S3_BUCKET_NAME",
        "N8N_EXTERNAL_STORAGE_S3_BUCKET_REGION",
        "N8N_EXTERNAL_STORAGE_S3_ACCESS_KEY",
        "N8N_EXTERNAL_STORAGE_S3_ACCESS_SECRET",
    ):
        assert key not in env


# --- Tier 2 SMTP env tests (issue #7) ---


SMTP_FULL_CONFIG = {
    "smtp-host": "smtp.example.com",
    "smtp-port": 2525,
    "smtp-user": "bot",
    "smtp-sender": "n8n <bot@example.com>",
    "smtp-ssl-tls": False,
}


def test_build_smtp_env_unconfigured_returns_empty():
    env, err = build_smtp_env({}, None)

    assert err is None
    assert env == {}


def test_build_smtp_env_full_config_emits_all_vars():
    env, err = build_smtp_env(SMTP_FULL_CONFIG, "pw")

    assert err is None
    assert env == {
        "N8N_SMTP_HOST": "smtp.example.com",
        "N8N_SMTP_PORT": "2525",
        "N8N_SMTP_USER": "bot",
        "N8N_SMTP_PASSWORD": "pw",
        "N8N_SMTP_SSL": "false",
        "N8N_SMTP_SENDER": "n8n <bot@example.com>",
    }


def test_build_smtp_env_host_only_blocks():
    env, err = build_smtp_env({"smtp-host": "smtp.example.com"}, None)

    assert env is None
    assert err is not None
    assert "must all be set together" in err


def test_build_smtp_env_user_only_blocks():
    env, err = build_smtp_env({"smtp-user": "bot"}, None)

    assert env is None
    assert err is not None
    assert "must all be set together" in err


def test_build_smtp_env_password_only_blocks():
    env, err = build_smtp_env({}, "pw")

    assert env is None
    assert err is not None
    assert "must all be set together" in err


def test_build_smtp_env_port_out_of_range_blocks():
    for bad_port in (0, 65536):
        env, err = build_smtp_env({**SMTP_FULL_CONFIG, "smtp-port": bad_port}, "pw")

        assert env is None
        assert err is not None
        assert "smtp-port" in err
        assert str(bad_port) in err


def test_build_smtp_env_sender_empty_omits_var():
    env, err = build_smtp_env({**SMTP_FULL_CONFIG, "smtp-sender": ""}, "pw")

    assert err is None
    assert env is not None
    assert "N8N_SMTP_SENDER" not in env


def test_build_smtp_env_ssl_tls_true_sets_true():
    env, err = build_smtp_env({**SMTP_FULL_CONFIG, "smtp-ssl-tls": True}, "pw")

    assert err is None
    assert env is not None
    assert env["N8N_SMTP_SSL"] == "true"


def test_build_layer_includes_smtp_env():
    smtp_env = {
        "N8N_SMTP_HOST": "h",
        "N8N_SMTP_PORT": "2525",
        "N8N_SMTP_USER": "u",
        "N8N_SMTP_PASSWORD": "p",
        "N8N_SMTP_SSL": "false",
    }
    layer = build_layer(DB_ENV, smtp_env=smtp_env)

    environment = layer["services"]["n8n"]["environment"]
    for k, v in smtp_env.items():
        assert environment[k] == v
