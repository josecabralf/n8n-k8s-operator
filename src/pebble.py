"""Pebble layer builder for the n8n container."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, NamedTuple
from urllib.parse import urlparse

import yaml
from ops.pebble import LayerDict

logger = logging.getLogger(__name__)

N8N_URL = "http://localhost:5678"

VALID_LOG_LEVELS = frozenset({"debug", "info", "warn", "error"})
VALID_SAVE_MODES = frozenset({"all", "none"})

ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")

# Maps each charm-managed env var to operator remediation text. Used when a
# user-supplied `environment` entry collides with a charm-managed env: the
# value is dropped, status surfaces the conflict, and one warning per dropped
# key is logged. Adding a new charm-managed env means adding a row here too;
# otherwise the conflict warning falls back to a generic message.
CHARM_MANAGED_ENV_ORIGIN: dict[str, str] = {
    # Ingress-derived.
    "N8N_HOST": "set by ingress relation",
    "N8N_PROTOCOL": "set by ingress relation",
    "N8N_PORT": "set by ingress relation",
    "N8N_PROXY_HOPS": "set by ingress relation",
    "WEBHOOK_URL": "set by ingress relation",
    "N8N_EDITOR_BASE_URL": "set by ingress relation",
    # Postgres-derived (postgresql relation).
    "DB_TYPE": "set by postgresql relation",
    "DB_POSTGRESDB_HOST": "set by postgresql relation",
    "DB_POSTGRESDB_PORT": "set by postgresql relation",
    "DB_POSTGRESDB_DATABASE": "set by postgresql relation",
    "DB_POSTGRESDB_USER": "set by postgresql relation",
    "DB_POSTGRESDB_PASSWORD": "set by postgresql relation",
    # Encryption key (auto-generated app secret / encryption-key config).
    "N8N_ENCRYPTION_KEY": "managed by charm; use 'encryption-key' config to override",
    # Metrics relation.
    "N8N_METRICS": "set by metrics-endpoint relation",
    # Binary-data + S3 (s3 relation / binary-data storage).
    "N8N_DEFAULT_BINARY_DATA_MODE": "set by s3 relation or binary-data storage",
    "N8N_AVAILABLE_BINARY_DATA_MODES": "set by s3 relation",
    "N8N_EXTERNAL_STORAGE_S3_HOST": "set by s3 relation",
    "N8N_EXTERNAL_STORAGE_S3_BUCKET_NAME": "set by s3 relation",
    "N8N_EXTERNAL_STORAGE_S3_BUCKET_REGION": "set by s3 relation",
    "N8N_EXTERNAL_STORAGE_S3_ACCESS_KEY": "set by s3 relation",
    "N8N_EXTERNAL_STORAGE_S3_ACCESS_SECRET": "set by s3 relation",
    # Tier 1 typed configs.
    "N8N_LOG_LEVEL": "use 'juju config n8n-k8s log-level=...' instead",
    "GENERIC_TIMEZONE": "use 'juju config n8n-k8s timezone=...' instead",
    "TZ": "use 'juju config n8n-k8s timezone=...' instead",
    "EXECUTIONS_DATA_PRUNE": "use 'juju config n8n-k8s executions-data-prune=...' instead",
    "EXECUTIONS_DATA_MAX_AGE": "use 'juju config n8n-k8s executions-data-max-age-hours=...' instead",
    "EXECUTIONS_DATA_SAVE_ON_ERROR": "use 'juju config n8n-k8s executions-data-save-on-error=...' instead",
    "EXECUTIONS_DATA_SAVE_ON_SUCCESS": "use 'juju config n8n-k8s executions-data-save-on-success=...' instead",
    "EXECUTIONS_DATA_SAVE_ON_PROGRESS": "use 'juju config n8n-k8s executions-data-save-on-progress=...' instead",
    "N8N_USER_MANAGEMENT_DISABLED": "use 'juju config n8n-k8s disable-user-registration=...' instead",
    # Tier 2 typed configs (SMTP).
    "N8N_SMTP_HOST": "use 'juju config n8n-k8s smtp-host=...' instead",
    "N8N_SMTP_PORT": "use 'juju config n8n-k8s smtp-port=...' instead",
    "N8N_SMTP_USER": "use 'juju config n8n-k8s smtp-user=...' instead",
    "N8N_SMTP_PASSWORD": "use 'juju config n8n-k8s smtp-password=...' instead",
    "N8N_SMTP_SSL": "use 'juju config n8n-k8s smtp-ssl-tls=...' instead",
    "N8N_SMTP_SENDER": "use 'juju config n8n-k8s smtp-sender=...' instead",
    # Task runner.
    "N8N_RUNNERS_ENABLED": "use 'juju config n8n-k8s task-runner=...' instead",
    "N8N_RUNNERS_MAX_CONCURRENCY": "use 'juju config n8n-k8s runner-max-concurrency=...' instead",
    "N8N_RUNNERS_TASK_TIMEOUT": "use 'juju config n8n-k8s runner-process-timeout=...' instead",
}


class EnvEntry(NamedTuple):
    name: str
    value: str


class JujuEntry(NamedTuple):
    secret_id: str
    name: str
    key: str


class VaultEntry(NamedTuple):
    path: str
    name: str
    key: str


@dataclass(frozen=True)
class ParsedEnvironment:
    """Parsed shape of the `environment` config option (issue #8).

    `vault` entries are resolved at reconcile time by the charm via
    `hvac` over the `vault-k8s` relation (issue #30).
    """

    env: list[EnvEntry] = field(default_factory=list)
    juju: list[JujuEntry] = field(default_factory=list)
    vault: list[VaultEntry] = field(default_factory=list)


_ALLOWED_TOP_KEYS = ("env", "juju", "vault")


def _require_str(value: Any, field_name: str, entry_label: str) -> tuple[str | None, str | None]:
    if not isinstance(value, str) or not value:
        return (None, f"{entry_label} '{field_name}' must be a non-empty string")
    return (value, None)


def _validate_name(name_value: Any, entry_label: str) -> tuple[str | None, str | None]:
    if not isinstance(name_value, str) or not ENV_NAME_RE.match(name_value):
        return (
            None,
            f"{entry_label} 'name' must match [A-Z_][A-Z0-9_]* (got {name_value!r})",
        )
    return (name_value, None)


def parse_environment_config(yaml_str: str) -> tuple[ParsedEnvironment | None, str | None]:
    """Parse the `environment` config option into a ParsedEnvironment.

    Empty input parses to an empty ParsedEnvironment. On schema failure
    returns (None, msg); the caller surfaces ``msg`` as a BlockedStatus.

    `env:` entries: ``{name: str, value: str}``. ``value`` coerced via ``str()``.
    `juju:` entries: ``{secret-id: str, name: str, key: str}``.
    `vault:` entries: ``{path: str, name: str, key: str}``.
    `name` must match ``[A-Z_][A-Z0-9_]*``. Duplicate ``name`` within the
    same source is a parse error (always a typo); cross-source collisions
    are allowed and resolved by precedence in ``build_environment_user_env``.
    """
    text = (yaml_str or "").strip()
    if not text:
        return (ParsedEnvironment(), None)

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return (None, f"environment config: malformed YAML ({exc.__class__.__name__})")

    if not isinstance(raw, Mapping):
        return (None, "environment config: top-level YAML must be a mapping")

    unknown = [k for k in raw if k not in _ALLOWED_TOP_KEYS]
    if unknown:
        return (
            None,
            f"environment config: unsupported top-level key(s) {unknown!r}; " f"allowed: {list(_ALLOWED_TOP_KEYS)}",
        )

    env_entries: list[EnvEntry] = []
    juju_entries: list[JujuEntry] = []
    vault_entries: list[VaultEntry] = []

    if "env" in raw:
        items = raw["env"]
        if not isinstance(items, list):
            return (None, "environment config: 'env' must be a list of mappings")
        seen: set[str] = set()
        for idx, item in enumerate(items):
            label = f"environment config: env[{idx}]"
            if not isinstance(item, Mapping):
                return (None, f"{label} must be a mapping with 'name' and 'value'")
            name, err = _validate_name(item.get("name"), label)
            if err is not None:
                return (None, f"environment config: {err}")
            if "value" not in item:
                return (None, f"{label} missing required field 'value'")
            value = str(item["value"])
            if name in seen:
                return (None, f"environment config: duplicate env entry name '{name}'")
            seen.add(name)
            env_entries.append(EnvEntry(name=name, value=value))

    if "juju" in raw:
        items = raw["juju"]
        if not isinstance(items, list):
            return (None, "environment config: 'juju' must be a list of mappings")
        seen = set()
        for idx, item in enumerate(items):
            label = f"environment config: juju[{idx}]"
            if not isinstance(item, Mapping):
                return (None, f"{label} must be a mapping with 'secret-id', 'name', 'key'")
            secret_id, err = _require_str(item.get("secret-id"), "secret-id", label)
            if err is not None:
                return (None, f"environment config: {err}")
            name, err = _validate_name(item.get("name"), label)
            if err is not None:
                return (None, f"environment config: {err}")
            key, err = _require_str(item.get("key"), "key", label)
            if err is not None:
                return (None, f"environment config: {err}")
            if name in seen:
                return (None, f"environment config: duplicate juju entry name '{name}'")
            seen.add(name)
            juju_entries.append(JujuEntry(secret_id=secret_id, name=name, key=key))

    if "vault" in raw:
        items = raw["vault"]
        if not isinstance(items, list):
            return (None, "environment config: 'vault' must be a list of mappings")
        seen = set()
        for idx, item in enumerate(items):
            label = f"environment config: vault[{idx}]"
            if not isinstance(item, Mapping):
                return (None, f"{label} must be a mapping with 'path', 'name', 'key'")
            path, err = _require_str(item.get("path"), "path", label)
            if err is not None:
                return (None, f"environment config: {err}")
            name, err = _validate_name(item.get("name"), label)
            if err is not None:
                return (None, f"environment config: {err}")
            key, err = _require_str(item.get("key"), "key", label)
            if err is not None:
                return (None, f"environment config: {err}")
            if name in seen:
                return (None, f"environment config: duplicate vault entry name '{name}'")
            seen.add(name)
            vault_entries.append(VaultEntry(path=path, name=name, key=key))

    return (
        ParsedEnvironment(env=env_entries, juju=juju_entries, vault=vault_entries),
        None,
    )


def build_environment_user_env(
    parsed: ParsedEnvironment,
    resolved_juju: Mapping[str, str],
    resolved_vault: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Merge user-supplied env entries into a flat {name: value} dict.

    Precedence within user-supplied entries (highest wins): vault > juju > env.
    Rationale: more-deliberate / more-secret sources override less-deliberate
    ones, so operators can migrate an `env:` plaintext entry to a `juju:`
    secret (or a `vault:` entry) by adding the new entry without deleting
    the old one in the same step.

    Duplicates within the same source are already rejected at parse time
    (see ``parse_environment_config``).
    """
    resolved_vault = resolved_vault or {}
    result: dict[str, str] = {}
    sources: dict[str, str] = {}

    def _set(name: str, value: str, source: str) -> None:
        if name in result:
            logger.debug(
                "environment: '%s' from %s overrides earlier entry from %s",
                name,
                source,
                sources[name],
            )
        result[name] = value
        sources[name] = source

    for entry in parsed.env:
        _set(entry.name, entry.value, "env")
    for name, value in resolved_juju.items():
        _set(name, value, "juju")
    for name, value in resolved_vault.items():
        _set(name, value, "vault")

    return result


def build_url_env(external_url: str) -> dict[str, str]:
    """Return n8n env vars derived from an external URL.

    N8N_PROTOCOL follows the URL scheme so n8n generates https links
    when TLS terminates at the ingress proxy; n8n itself still listens
    plaintext in-pod (N8N_PORT stays the listen port, 5678).
    N8N_PROXY_HOPS=1 makes n8n trust X-Forwarded-* headers from the
    single fronting proxy. N8N_PATH is deliberately not set: routing is
    host-based (app served at the root of a subdomain), per n8n's
    reverse-proxy guidance.
    """
    parsed = urlparse(external_url)
    return {
        "N8N_HOST": parsed.hostname or "",
        "N8N_PROTOCOL": parsed.scheme or "http",
        "N8N_PORT": "5678",
        "N8N_PROXY_HOPS": "1",
        "WEBHOOK_URL": external_url,
        "N8N_EDITOR_BASE_URL": external_url,
    }


def build_tier1_env(
    config: Mapping[str, Any],
) -> tuple[dict[str, str] | None, str | None]:
    """Translate Tier 1 charm configs into n8n env vars.

    Returns (env, None) on success or (None, msg) when a value is invalid;
    the caller surfaces ``msg`` as a BlockedStatus. This is the single
    convention for Tier 1 config→env translation (issues #7 and #8 extend
    the same pattern).
    """
    log_level = str(config.get("log-level", "info"))
    if log_level not in VALID_LOG_LEVELS:
        return (
            None,
            f"invalid log-level '{log_level}'; must be one of: debug, info, warn, error",
        )

    timezone = str(config.get("timezone", "UTC"))
    if not timezone:
        return (None, "timezone must not be empty")

    save_on_error = str(config.get("executions-data-save-on-error", "all"))
    if save_on_error not in VALID_SAVE_MODES:
        return (
            None,
            f"invalid executions-data-save-on-error '{save_on_error}'; must be 'all' or 'none'",
        )

    save_on_success = str(config.get("executions-data-save-on-success", "all"))
    if save_on_success not in VALID_SAVE_MODES:
        return (
            None,
            f"invalid executions-data-save-on-success '{save_on_success}'; must be 'all' or 'none'",
        )

    max_age = int(config.get("executions-data-max-age-hours", 336))
    if max_age < 0:
        return (None, "executions-data-max-age-hours must be >= 0")

    prune = bool(config.get("executions-data-prune", False))
    save_on_progress = bool(config.get("executions-data-save-on-progress", False))
    disable_user_reg = bool(config.get("disable-user-registration", False))

    env = {
        "N8N_LOG_LEVEL": log_level,
        "GENERIC_TIMEZONE": timezone,
        "TZ": timezone,
        "EXECUTIONS_DATA_PRUNE": "true" if prune else "false",
        "EXECUTIONS_DATA_MAX_AGE": str(max_age),
        "EXECUTIONS_DATA_SAVE_ON_ERROR": save_on_error,
        "EXECUTIONS_DATA_SAVE_ON_SUCCESS": save_on_success,
        "EXECUTIONS_DATA_SAVE_ON_PROGRESS": "true" if save_on_progress else "false",
        "N8N_USER_MANAGEMENT_DISABLED": "true" if disable_user_reg else "false",
    }
    return (env, None)


def build_runner_env(
    config: Mapping[str, Any],
) -> tuple[dict[str, str] | None, str | None]:
    """Translate the internal task-runner configs into n8n env vars.

    Returns ({}, None) when task-runner is disabled (no N8N_RUNNERS_* vars);
    (env, None) when enabled; (None, msg) when a value is invalid.
    """
    if not bool(config.get("task-runner", False)):
        return ({}, None)
    max_concurrency = int(config.get("runner-max-concurrency", 5))
    if max_concurrency < 1:
        return (None, "runner-max-concurrency must be >= 1")
    task_timeout = int(config.get("runner-process-timeout", 300))
    if task_timeout < 1:
        return (None, "runner-process-timeout must be >= 1")
    return (
        {
            "N8N_RUNNERS_ENABLED": "true",
            "N8N_RUNNERS_MAX_CONCURRENCY": str(max_concurrency),
            "N8N_RUNNERS_TASK_TIMEOUT": str(task_timeout),
        },
        None,
    )


S3_REQUIRED_KEYS = ("endpoint", "bucket", "region", "access-key", "secret-key")


def build_s3_env(creds: Mapping[str, str]) -> dict[str, str]:
    """Translate S3Requirer credentials into n8n env vars.

    Returns ``{}`` when any of the five required keys is missing or
    empty — the caller treats that as "S3 not yet ready" and skips
    binary-data mode ``s3``. No validation beyond presence; the
    s3-integrator provides what it has.
    """
    for key in S3_REQUIRED_KEYS:
        if not creds.get(key):
            return {}
    return {
        "N8N_AVAILABLE_BINARY_DATA_MODES": "filesystem,s3",
        "N8N_EXTERNAL_STORAGE_S3_HOST": creds["endpoint"],
        "N8N_EXTERNAL_STORAGE_S3_BUCKET_NAME": creds["bucket"],
        "N8N_EXTERNAL_STORAGE_S3_BUCKET_REGION": creds["region"],
        "N8N_EXTERNAL_STORAGE_S3_ACCESS_KEY": creds["access-key"],
        "N8N_EXTERNAL_STORAGE_S3_ACCESS_SECRET": creds["secret-key"],
    }


def build_smtp_env(
    config: Mapping[str, Any],
    smtp_password: str | None,
) -> tuple[dict[str, str] | None, str | None]:
    """Translate Tier 2 SMTP configs into n8n env vars.

    Returns ({}, None) when SMTP is unconfigured (all of host/user/password
    empty); (env, None) when fully configured; (None, msg) when the
    config is invalid (partial trio, port out of range).
    """
    host = str(config.get("smtp-host", "")).strip()
    user = str(config.get("smtp-user", "")).strip()
    pw_set = bool(smtp_password)

    if not (host or user or pw_set):
        return ({}, None)
    if not (host and user and pw_set):
        return (None, "smtp-host, smtp-user, and smtp-password must all be set together")

    port = int(config.get("smtp-port", 587))
    if not 1 <= port <= 65535:
        return (None, f"invalid smtp-port '{port}'; must be 1–65535")

    env = {
        "N8N_SMTP_HOST": host,
        "N8N_SMTP_PORT": str(port),
        "N8N_SMTP_USER": user,
        "N8N_SMTP_PASSWORD": smtp_password,
        "N8N_SMTP_SSL": "true" if bool(config.get("smtp-ssl-tls", False)) else "false",
    }
    sender = str(config.get("smtp-sender", "")).strip()
    if sender:
        env["N8N_SMTP_SENDER"] = sender
    return (env, None)


def build_layer(
    db_env: Mapping[str, str],
    encryption_key: str = "",
    url_env: Mapping[str, str] | None = None,
    tier1_env: Mapping[str, str] | None = None,
    runner_env: Mapping[str, str] | None = None,
    smtp_env: Mapping[str, str] | None = None,
    metrics_env: Mapping[str, str] | None = None,
    s3_env: Mapping[str, str] | None = None,
    binary_data_mode: str | None = None,
    user_env: Mapping[str, str] | None = None,
) -> tuple[LayerDict, list[str]]:
    """Return a Pebble layer dict that runs n8n with the given DB env vars.

    Args:
        db_env: Mapping of n8n Postgres env-var names to values. Must
            contain at minimum the six DB_* variables n8n needs to talk
            to PostgreSQL (DB_TYPE, DB_POSTGRESDB_HOST, _PORT,
            _DATABASE, _USER, _PASSWORD).
        encryption_key: Value to inject as ``N8N_ENCRYPTION_KEY`` in the
            n8n service environment. The caller is responsible for
            supplying a non-empty key in production. When the default
            empty string is passed the variable is omitted from the
            layer entirely; this default exists only to keep the
            signature backwards-compatible for callers that have not
            yet been updated.
        url_env: Optional mapping of ingress-derived env vars
            (``N8N_HOST``, ``N8N_PROTOCOL``, ``N8N_PORT``,
            ``N8N_PROXY_HOPS``, ``WEBHOOK_URL``, ``N8N_EDITOR_BASE_URL``).
        tier1_env: Optional mapping of Tier 1 n8n env vars derived from
            charm config (logging, timezone, executions retention,
            user-management toggle).
        runner_env: Optional mapping of internal task-runner env vars
            (``N8N_RUNNERS_ENABLED``, ``N8N_RUNNERS_MAX_CONCURRENCY``,
            ``N8N_RUNNERS_TASK_TIMEOUT``) derived from the ``task-runner``
            charm config. Empty/omitted when the task runner is disabled.
        smtp_env: Optional mapping of Tier 2 SMTP env vars (``N8N_SMTP_HOST``,
            ``N8N_SMTP_PORT``, ``N8N_SMTP_USER``, ``N8N_SMTP_PASSWORD``,
            ``N8N_SMTP_SSL`` and optionally ``N8N_SMTP_SENDER``). Merged
            after ``tier1_env`` and before ``url_env`` so url-derived vars
            still win on collision.
        metrics_env: Optional mapping of metrics env vars, typically
            ``{"N8N_METRICS": "true"}`` when the ``metrics-endpoint``
            relation is present. Omit to leave n8n metrics disabled
            (n8n default — ``/metrics`` returns 404).
        s3_env: Optional mapping of n8n S3 env vars produced by
            ``build_s3_env`` from the ``s3`` relation. When set the
            caller should also pass ``binary_data_mode="s3"``; an empty
            mapping is treated as "S3 not yet ready" and omitted.
        binary_data_mode: If set, written as
            ``N8N_DEFAULT_BINARY_DATA_MODE``. Use ``"filesystem"`` when
            the binary-data storage is attached, ``"s3"`` when the s3
            relation is wired up. When ``None``, the variable is omitted
            and n8n falls back to in-DB storage.

        user_env: Optional mapping of user-supplied env vars from the
            Tier 3 ``environment`` config (issue #8). Applied **first**
            so all subsequent charm-managed envs (DB, tier1/2, ingress,
            metrics, S3, encryption key, binary-data) naturally override
            on collision. Conflicting keys are returned in the second
            tuple element so the caller can surface a status warning.

    Returns:
        A tuple of (LayerDict, conflict_keys). The LayerDict carries one
        service (``n8n``) plus an alive HTTP check on /healthz and a
        ready HTTP check on /healthz/readiness. ``conflict_keys`` is the
        sorted list of user_env keys that were overridden by charm-managed
        envs; empty when there's no conflict (or no user_env).
    """
    charm_managed: dict[str, str] = dict(db_env)
    if tier1_env:
        charm_managed.update(tier1_env)
    if runner_env:
        charm_managed.update(runner_env)
    if smtp_env:
        charm_managed.update(smtp_env)
    if url_env:
        charm_managed.update(url_env)
    if metrics_env:
        charm_managed.update(metrics_env)
    if s3_env:
        charm_managed.update(s3_env)
    if encryption_key:
        charm_managed["N8N_ENCRYPTION_KEY"] = encryption_key
    if binary_data_mode:
        charm_managed["N8N_DEFAULT_BINARY_DATA_MODE"] = binary_data_mode

    # user_env applied first so charm-managed envs naturally override on
    # collision; conflicts = keys that appear in both regardless of value.
    environment: dict[str, str] = dict(user_env) if user_env else {}
    environment.update(charm_managed)
    conflicts = sorted(set(user_env or {}).intersection(charm_managed))

    layer: LayerDict = {
        "summary": "n8n workload layer",
        "description": "Runs n8n against the related PostgreSQL.",
        "services": {
            "n8n": {
                "override": "replace",
                "summary": "n8n",
                "command": "n8n start",
                "startup": "enabled",
                "environment": environment,
            }
        },
        "checks": {
            "live": {
                "override": "replace",
                "level": "alive",
                "period": "30s",
                "http": {"url": f"{N8N_URL}/healthz"},
            },
            "ready": {
                "override": "replace",
                "level": "ready",
                "period": "10s",
                "threshold": 3,
                "http": {"url": f"{N8N_URL}/healthz/readiness"},
            },
        },
    }
    return layer, conflicts
