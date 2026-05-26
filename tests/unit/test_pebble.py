"""Unit tests for the Pebble layer builder."""

from __future__ import annotations

import pytest

from pebble import (
    EnvEntry,
    JujuEntry,
    ParsedEnvironment,
    VaultEntry,
    build_environment_user_env,
    build_layer,
    build_s3_env,
    build_smtp_env,
    build_tier1_env,
    build_url_env,
    parse_environment_config,
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


def test_build_layer_n8n_service_runs_n8n_start():
    layer, _ = build_layer(DB_ENV, encryption_key="testkey")

    assert layer["services"]["n8n"]["command"] == "n8n start"


def test_build_layer_n8n_service_carries_db_env():
    layer, _ = build_layer(DB_ENV, encryption_key="testkey")

    environment = layer["services"]["n8n"]["environment"]
    for key, value in DB_ENV.items():
        assert environment[key] == value


def test_build_layer_environment_is_copied_not_aliased():
    db_env = dict(DB_ENV)
    layer, _ = build_layer(db_env, encryption_key="testkey")

    layer["services"]["n8n"]["environment"]["DB_POSTGRESDB_PASSWORD"] = "tampered"

    assert db_env["DB_POSTGRESDB_PASSWORD"] == "secret"


def test_build_layer_has_live_http_check_on_healthz():
    layer, _ = build_layer(DB_ENV, encryption_key="testkey")

    live = layer["checks"]["live"]
    assert live["http"]["url"] == "http://localhost:5678/healthz"
    assert live["level"] == "alive"
    assert live["period"] == "30s"


def test_build_layer_has_ready_http_check_on_readiness_endpoint_with_threshold_3():
    layer, _ = build_layer(DB_ENV, encryption_key="testkey")

    ready = layer["checks"]["ready"]
    assert ready["http"]["url"] == "http://localhost:5678/healthz/readiness"
    assert ready["level"] == "ready"
    assert ready["period"] == "10s"
    assert ready["threshold"] == 3


def test_build_layer_service_has_replace_override():
    layer, _ = build_layer(DB_ENV, encryption_key="testkey")

    assert layer["services"]["n8n"]["override"] == "replace"
    assert layer["checks"]["live"]["override"] == "replace"
    assert layer["checks"]["ready"]["override"] == "replace"


def test_build_layer_injects_n8n_encryption_key():
    layer, _ = build_layer(DB_ENV, encryption_key="testkey")

    environment = layer["services"]["n8n"]["environment"]
    assert environment["N8N_ENCRYPTION_KEY"] == "testkey"


def test_build_url_env_extracts_host_from_url():
    url_env = build_url_env("http://traefik.local/")

    assert url_env["N8N_HOST"] == "traefik.local"


def test_build_url_env_returns_expected_keys():
    url_env = build_url_env("http://traefik.local/")

    assert url_env["N8N_PROTOCOL"] == "http"
    assert url_env["N8N_PORT"] == "5678"
    assert url_env["N8N_PATH"] == "/"
    assert url_env["WEBHOOK_URL"] == "http://traefik.local/"
    assert url_env["N8N_EDITOR_BASE_URL"] == "http://traefik.local/"


def test_build_url_env_subpath_sets_n8n_path():
    url_env = build_url_env("http://traefik.local/my-model-n8n")

    assert url_env["N8N_HOST"] == "traefik.local"
    assert url_env["N8N_PATH"] == "/my-model-n8n/"


def test_build_url_env_handles_https_scheme():
    url_env = build_url_env("https://n8n.example.com/")

    assert url_env["N8N_HOST"] == "n8n.example.com"
    assert url_env["N8N_PROTOCOL"] == "http"
    assert url_env["WEBHOOK_URL"] == "https://n8n.example.com/"
    assert url_env["N8N_EDITOR_BASE_URL"] == "https://n8n.example.com/"


def test_build_layer_without_url_env_is_unchanged():
    layer, _ = build_layer({"DB_TYPE": "postgresdb"}, encryption_key="k")

    environment = layer["services"]["n8n"]["environment"]
    assert environment["DB_TYPE"] == "postgresdb"
    assert environment["N8N_ENCRYPTION_KEY"] == "k"
    for key in ("N8N_HOST", "N8N_PROTOCOL", "N8N_PORT", "N8N_PATH", "WEBHOOK_URL", "N8N_EDITOR_BASE_URL"):
        assert key not in environment


def test_build_layer_with_url_env_merges_into_environment():
    url_env = build_url_env("http://traefik.local/")
    layer, _ = build_layer(
        {"DB_TYPE": "postgresdb"},
        encryption_key="k",
        url_env=url_env,
    )

    environment = layer["services"]["n8n"]["environment"]
    assert environment.items() >= url_env.items()


def test_build_layer_with_metrics_env_sets_n8n_metrics():
    layer, _ = build_layer(
        {"DB_TYPE": "postgresdb"},
        encryption_key="k",
        metrics_env={"N8N_METRICS": "true"},
    )

    assert layer["services"]["n8n"]["environment"]["N8N_METRICS"] == "true"


def test_build_layer_without_metrics_env_omits_n8n_metrics():
    layer, _ = build_layer({"DB_TYPE": "postgresdb"}, encryption_key="k")

    assert "N8N_METRICS" not in layer["services"]["n8n"]["environment"]


def test_build_layer_includes_binary_data_mode_when_set():
    layer, _ = build_layer(DB_ENV, binary_data_mode="filesystem")

    env = layer["services"]["n8n"]["environment"]
    assert env["N8N_DEFAULT_BINARY_DATA_MODE"] == "filesystem"


def test_build_layer_omits_binary_data_mode_by_default():
    layer, _ = build_layer(DB_ENV)

    env = layer["services"]["n8n"]["environment"]
    assert "N8N_DEFAULT_BINARY_DATA_MODE" not in env


def test_build_layer_pebble_checks_still_target_localhost():
    layer_no_url, _ = build_layer(DB_ENV, encryption_key="k")
    layer_with_url, _ = build_layer(
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
    layer, _ = build_layer(DB_ENV, tier1_env={"N8N_LOG_LEVEL": "debug"})

    assert layer["services"]["n8n"]["environment"]["N8N_LOG_LEVEL"] == "debug"


def test_build_s3_env_returns_expected_n8n_env_vars():
    env = build_s3_env(S3_CREDS)

    assert env == {
        "N8N_AVAILABLE_BINARY_DATA_MODES": "filesystem,s3",
        "N8N_EXTERNAL_STORAGE_S3_HOST": "http://minio.example:9000",
        "N8N_EXTERNAL_STORAGE_S3_BUCKET_NAME": "n8n",
        "N8N_EXTERNAL_STORAGE_S3_BUCKET_REGION": "us-east-1",
        "N8N_EXTERNAL_STORAGE_S3_ACCESS_KEY": "AKIAEXAMPLE",
        "N8N_EXTERNAL_STORAGE_S3_ACCESS_SECRET": "sssecret",
    }


@pytest.mark.parametrize("missing_key", ["endpoint", "bucket", "region", "access-key", "secret-key"])
def test_build_s3_env_returns_empty_when_required_key_missing(missing_key):
    partial = {k: v for k, v in S3_CREDS.items() if k != missing_key}

    assert build_s3_env(partial) == {}


def test_build_s3_env_returns_empty_when_required_key_blank():
    blank_secret = dict(S3_CREDS, **{"secret-key": ""})

    assert build_s3_env(blank_secret) == {}


def test_build_layer_with_s3_env_merges_into_environment():
    s3_env = build_s3_env(S3_CREDS)

    layer, _ = build_layer(
        DB_ENV,
        encryption_key="k",
        s3_env=s3_env,
        binary_data_mode="s3",
    )

    env = layer["services"]["n8n"]["environment"]
    assert env.items() >= s3_env.items()
    assert env["N8N_DEFAULT_BINARY_DATA_MODE"] == "s3"


def test_build_layer_without_s3_env_omits_s3_keys():
    layer, _ = build_layer(DB_ENV, encryption_key="k")

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


@pytest.mark.parametrize("bad_port", [0, 65536])
def test_build_smtp_env_port_out_of_range_blocks(bad_port):
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
    layer, _ = build_layer(DB_ENV, smtp_env=smtp_env)

    environment = layer["services"]["n8n"]["environment"]
    for k, v in smtp_env.items():
        assert environment[k] == v


# --- Tier 3 environment config (issue #8) ---


def test_parse_environment_config_empty_returns_empty_parsed():
    parsed, err = parse_environment_config("")

    assert err is None
    assert parsed == ParsedEnvironment()


def test_parse_environment_config_whitespace_only_returns_empty_parsed():
    parsed, err = parse_environment_config("   \n   ")

    assert err is None
    assert parsed == ParsedEnvironment()


def test_parse_environment_config_env_only():
    parsed, err = parse_environment_config(
        "env:\n  - name: N8N_FOO\n    value: bar\n  - name: N8N_BAZ\n    value: '42'\n"
    )

    assert err is None
    assert parsed is not None
    assert parsed.env == [EnvEntry("N8N_FOO", "bar"), EnvEntry("N8N_BAZ", "42")]
    assert parsed.juju == []
    assert parsed.vault == []


def test_parse_environment_config_coerces_env_value_to_str():
    parsed, err = parse_environment_config("env:\n  - name: N8N_PORT_HINT\n    value: 5678\n")

    assert err is None
    assert parsed is not None
    assert parsed.env == [EnvEntry("N8N_PORT_HINT", "5678")]


def test_parse_environment_config_juju_only():
    parsed, err = parse_environment_config(
        "juju:\n  - secret-id: secret:abc\n    name: N8N_API_TOKEN\n    key: token\n"
    )

    assert err is None
    assert parsed is not None
    assert parsed.juju == [JujuEntry(secret_id="secret:abc", name="N8N_API_TOKEN", key="token")]


def test_parse_environment_config_vault_only_schema_validated():
    parsed, err = parse_environment_config("vault:\n  - path: kv/n8n\n    name: N8N_SECRET\n    key: token\n")

    assert err is None
    assert parsed is not None
    assert parsed.vault == [VaultEntry(path="kv/n8n", name="N8N_SECRET", key="token")]


def test_parse_environment_config_all_three_subkeys():
    parsed, err = parse_environment_config(
        "env:\n  - {name: A, value: x}\n"
        "juju:\n  - {secret-id: secret:1, name: B, key: k}\n"
        "vault:\n  - {path: kv/x, name: C, key: k}\n"
    )

    assert err is None
    assert parsed is not None
    assert [e.name for e in parsed.env] == ["A"]
    assert [j.name for j in parsed.juju] == ["B"]
    assert [v.name for v in parsed.vault] == ["C"]


def test_parse_environment_config_malformed_yaml_returns_error():
    parsed, err = parse_environment_config("env: [unclosed")

    assert parsed is None
    assert err is not None
    assert "malformed YAML" in err


def test_parse_environment_config_non_mapping_root_returns_error():
    parsed, err = parse_environment_config("- just\n- a\n- list\n")

    assert parsed is None
    assert err is not None
    assert "mapping" in err


def test_parse_environment_config_unsupported_top_level_key_returns_error():
    parsed, err = parse_environment_config("random:\n  - x\n")

    assert parsed is None
    assert err is not None
    assert "unsupported top-level key" in err
    assert "random" in err


def test_parse_environment_config_env_missing_value_returns_error():
    parsed, err = parse_environment_config("env:\n  - name: N8N_X\n")

    assert parsed is None
    assert err is not None
    assert "value" in err


def test_parse_environment_config_env_invalid_lowercase_name_returns_error():
    parsed, err = parse_environment_config("env:\n  - name: n8n_foo\n    value: bar\n")

    assert parsed is None
    assert err is not None
    assert "must match" in err


def test_parse_environment_config_env_invalid_leading_digit_returns_error():
    parsed, err = parse_environment_config("env:\n  - name: 1FOO\n    value: bar\n")

    assert parsed is None
    assert err is not None
    assert "must match" in err


def test_parse_environment_config_env_not_a_list_returns_error():
    parsed, err = parse_environment_config("env:\n  name: N8N_FOO\n")

    assert parsed is None
    assert err is not None
    assert "must be a list" in err


def test_parse_environment_config_juju_not_a_list_returns_error():
    parsed, err = parse_environment_config("juju:\n  name: N8N_FOO\n")

    assert parsed is None
    assert err is not None
    assert "must be a list" in err


def test_parse_environment_config_vault_not_a_list_returns_error():
    parsed, err = parse_environment_config("vault:\n  name: N8N_FOO\n")

    assert parsed is None
    assert err is not None
    assert "must be a list" in err


def test_parse_environment_config_juju_missing_secret_id_returns_error():
    parsed, err = parse_environment_config("juju:\n  - {name: N8N_X, key: k}\n")

    assert parsed is None
    assert err is not None
    assert "secret-id" in err


def test_parse_environment_config_vault_missing_path_returns_error():
    parsed, err = parse_environment_config("vault:\n  - {name: N8N_X, key: k}\n")

    assert parsed is None
    assert err is not None
    assert "path" in err


def test_parse_environment_config_duplicate_env_name_returns_error():
    parsed, err = parse_environment_config("env:\n  - {name: N8N_X, value: a}\n  - {name: N8N_X, value: b}\n")

    assert parsed is None
    assert err is not None
    assert "duplicate env entry name 'N8N_X'" in err


def test_parse_environment_config_duplicate_juju_name_returns_error():
    parsed, err = parse_environment_config(
        "juju:\n" "  - {secret-id: secret:1, name: N8N_X, key: k}\n" "  - {secret-id: secret:2, name: N8N_X, key: k}\n"
    )

    assert parsed is None
    assert err is not None
    assert "duplicate juju entry name 'N8N_X'" in err


def test_parse_environment_config_cross_source_collision_is_allowed():
    """Same name in env and juju is allowed; resolved later by precedence."""
    parsed, err = parse_environment_config(
        "env:\n  - {name: N8N_X, value: a}\n" "juju:\n  - {secret-id: secret:1, name: N8N_X, key: k}\n"
    )

    assert err is None
    assert parsed is not None
    assert parsed.env == [EnvEntry("N8N_X", "a")]
    assert parsed.juju == [JujuEntry(secret_id="secret:1", name="N8N_X", key="k")]


def test_build_environment_user_env_env_only():
    parsed = ParsedEnvironment(env=[EnvEntry("N8N_FOO", "bar")])

    result = build_environment_user_env(parsed, {})

    assert result == {"N8N_FOO": "bar"}


def test_build_environment_user_env_juju_only():
    parsed = ParsedEnvironment(juju=[JujuEntry(secret_id="secret:1", name="N8N_TOKEN", key="t")])

    result = build_environment_user_env(parsed, {"N8N_TOKEN": "resolved-value"})

    assert result == {"N8N_TOKEN": "resolved-value"}


def test_build_environment_user_env_juju_overrides_env_on_collision():
    parsed = ParsedEnvironment(
        env=[EnvEntry("N8N_X", "from-env")],
        juju=[JujuEntry(secret_id="secret:1", name="N8N_X", key="k")],
    )

    result = build_environment_user_env(parsed, {"N8N_X": "from-juju"})

    assert result == {"N8N_X": "from-juju"}


def test_build_environment_user_env_vault_overrides_juju_and_env():
    """Vault > juju > env precedence (sibling-issue forward compat)."""
    parsed = ParsedEnvironment(
        env=[EnvEntry("N8N_X", "from-env")],
        juju=[JujuEntry(secret_id="secret:1", name="N8N_X", key="k")],
        vault=[VaultEntry(path="kv/x", name="N8N_X", key="k")],
    )

    result = build_environment_user_env(
        parsed,
        resolved_juju={"N8N_X": "from-juju"},
        resolved_vault={"N8N_X": "from-vault"},
    )

    assert result == {"N8N_X": "from-vault"}


def test_build_environment_user_env_combines_non_colliding_sources():
    parsed = ParsedEnvironment(
        env=[EnvEntry("N8N_A", "a")],
        juju=[JujuEntry(secret_id="secret:1", name="N8N_B", key="k")],
    )

    result = build_environment_user_env(parsed, {"N8N_B": "b"})

    assert result == {"N8N_A": "a", "N8N_B": "b"}


def test_build_layer_user_env_present_in_environment():
    layer, conflicts = build_layer(DB_ENV, encryption_key="k", user_env={"N8N_PUSH_BACKEND": "websocket"})

    env = layer["services"]["n8n"]["environment"]
    assert env["N8N_PUSH_BACKEND"] == "websocket"
    assert conflicts == []


def test_build_layer_user_env_overridden_by_charm_managed():
    """A user_env key collision with db_env / url_env / encryption_key etc. is dropped."""
    layer, conflicts = build_layer(
        DB_ENV,
        encryption_key="k",
        url_env=build_url_env("http://traefik.local/"),
        user_env={"N8N_HOST": "hacked", "N8N_ENCRYPTION_KEY": "bogus", "OK_KEY": "v"},
    )

    env = layer["services"]["n8n"]["environment"]
    assert env["N8N_HOST"] == "traefik.local"
    assert env["N8N_ENCRYPTION_KEY"] == "k"
    assert env["OK_KEY"] == "v"
    assert conflicts == ["N8N_ENCRYPTION_KEY", "N8N_HOST"]


def test_build_layer_conflicts_reported_even_when_values_match():
    """Operator intent was overridden — flag regardless of value parity."""
    layer, conflicts = build_layer(
        DB_ENV,
        encryption_key="k",
        url_env=build_url_env("http://traefik.local/"),
        user_env={"N8N_HOST": "traefik.local"},
    )

    assert conflicts == ["N8N_HOST"]


def test_build_layer_user_env_none_returns_empty_conflicts():
    layer, conflicts = build_layer(DB_ENV, encryption_key="k")

    assert conflicts == []
