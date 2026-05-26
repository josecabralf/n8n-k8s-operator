#!/usr/bin/env python3
"""n8n Kubernetes charm — encryption-key + Postgres relation (issue #3)."""

from __future__ import annotations

import json
import logging
import secrets
import urllib.error
import urllib.request

import bcrypt
import hvac
import hvac.exceptions
import ops
import requests.exceptions
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.data_platform_libs.v0.s3 import S3Requirer
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.traefik_k8s.v0.traefik_route import TraefikRouteRequirer
from charms.vault_k8s.v0 import vault_kv
from ops import main, pebble
from ops.charm import CharmBase
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus

from pebble import (
    CHARM_MANAGED_ENV_ORIGIN,
    build_environment_user_env,
    build_layer,
    build_runner_env,
    build_s3_env,
    build_smtp_env,
    build_tier1_env,
    build_url_env,
    parse_environment_config,
)
from state import PEER_RELATION_NAME, CharmState

logger = logging.getLogger(__name__)

CONTAINER_NAME = "n8n"
SERVICE_NAME = "n8n"
DB_RELATION_NAME = "postgresql"
METRICS_RELATION_NAME = "metrics-endpoint"
INGRESS_RELATION_NAME = "traefik-route"
S3_RELATION_NAME = "s3"
DATABASE_NAME = "n8n"
N8N_PORT = 5678

ENCRYPTION_KEY_SECRET_LABEL = "n8n-encryption-key"
ENCRYPTION_KEY_CONFIG = "encryption-key"
ENVIRONMENT_CONFIG = "environment"

VAULT_RELATION_NAME = "vault-k8s"
VAULT_NONCE_SECRET_LABEL = "vault-kv-nonce"
VAULT_CA_PATH = "/tmp/vault-ca.pem"  # noqa: S108
VAULT_MOUNT_SUFFIX = "n8n"

BINARY_DATA_STORAGE_NAME = "binary-data"
BINARY_DATA_MOUNT_PATH = "/home/node/.n8n/binaryData"

OWNER_PROBE_PATH = "/rest/settings"
OWNER_PROBE_TIMEOUT_S = 3

STATUS_WAITING_N8N = "waiting for n8n to start"
STATUS_BINARY_DATA_FALLBACK = (
    "binary data in DB; attach 'binary-data' storage or " "relate s3-integrator for production use"
)
ERR_ALREADY_BOOTSTRAPPED = "owner already exists; use n8n UI to manage users"
ERR_NOT_LEADER = "create-admin must run on the leader unit"
ERR_PEER_NOT_READY = "peer relation not yet joined; retry"
ERR_CONTAINER_NOT_READY = "n8n container not yet connectable"
STATUS_RESTARTING = "restarting n8n"
ERR_SERVICE_NOT_CONFIGURED = "n8n service not configured yet; nothing to restart"


class N8nK8sCharm(CharmBase):
    """Charm: manages Postgres relation, app-owned encryption-key secret, and pebble layer."""

    def __init__(self, *args):
        super().__init__(*args)
        self.database = DatabaseRequires(
            self,
            relation_name=DB_RELATION_NAME,
            database_name=DATABASE_NAME,
        )
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.n8n_pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.n8n_pebble_check_recovered, self._on_pebble_check_recovered)
        self.framework.observe(self.on.n8n_pebble_check_failed, self._on_pebble_check_failed)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.secret_changed, self._on_secret_changed)
        self.framework.observe(self.on[PEER_RELATION_NAME].relation_created, self._on_peer_created)
        self.framework.observe(self.on[DB_RELATION_NAME].relation_created, self._on_database_changed)
        self.framework.observe(self.database.on.database_created, self._on_database_changed)
        self.framework.observe(self.database.on.endpoints_changed, self._on_database_changed)
        self.framework.observe(self.on[DB_RELATION_NAME].relation_broken, self._on_database_broken)
        self.framework.observe(self.on.get_encryption_key_action, self._on_get_encryption_key_action)
        self.framework.observe(self.on.create_admin_action, self._on_create_admin_action)
        self.framework.observe(self.on.restart_action, self._on_restart_action)
        self.framework.observe(self.on[INGRESS_RELATION_NAME].relation_created, self._on_ingress_changed)
        self.framework.observe(self.on[INGRESS_RELATION_NAME].relation_changed, self._on_ingress_changed)
        self.framework.observe(self.on[INGRESS_RELATION_NAME].relation_broken, self._on_ingress_changed)
        self.framework.observe(self.on[BINARY_DATA_STORAGE_NAME].storage_attached, self._on_storage_attached)
        self.framework.observe(self.on[BINARY_DATA_STORAGE_NAME].storage_detaching, self._on_storage_detaching)
        ingress_relation = self.model.get_relation(INGRESS_RELATION_NAME)
        if ingress_relation is not None:
            self._traefik_route = TraefikRouteRequirer(self, ingress_relation, INGRESS_RELATION_NAME)
        self._metrics = MetricsEndpointProvider(
            self,
            relation_name=METRICS_RELATION_NAME,
            jobs=[{"static_configs": [{"targets": [f"*:{N8N_PORT}"]}]}],
            refresh_event=self.on.config_changed,
        )
        self._grafana_dashboards = GrafanaDashboardProvider(self)
        self._log_forwarder = LogForwarder(self, relation_name="logging")
        self.framework.observe(self.on[METRICS_RELATION_NAME].relation_created, self._on_metrics_changed)
        self.framework.observe(self.on[METRICS_RELATION_NAME].relation_broken, self._on_metrics_changed)
        self._s3 = S3Requirer(self, S3_RELATION_NAME, bucket_name=self.app.name)
        self.framework.observe(self._s3.on.credentials_changed, self._on_s3_credentials_changed)
        self.framework.observe(self._s3.on.credentials_gone, self._on_s3_credentials_gone)
        self._vault_kv = vault_kv.VaultKvRequires(self, VAULT_RELATION_NAME, VAULT_MOUNT_SUFFIX)
        self.framework.observe(self._vault_kv.on.connected, self._on_vault_kv_connected)
        self.framework.observe(self._vault_kv.on.ready, self._on_vault_kv_ready)
        self.framework.observe(self._vault_kv.on.gone_away, self._on_vault_kv_gone_away)

    def _on_install(self, _event) -> None:
        self._ensure_vault_nonce()
        self._reconcile()

    def _on_config_changed(self, _event) -> None:
        self._reconcile()

    def _on_pebble_ready(self, _event) -> None:
        self._reconcile()

    def _on_pebble_check_recovered(self, _event) -> None:
        self._reconcile()

    def _on_pebble_check_failed(self, _event) -> None:
        self._reconcile()

    def _on_update_status(self, _event) -> None:
        relation = self.model.get_relation(VAULT_RELATION_NAME)
        if relation is not None:
            self._request_vault_credentials(relation)
        self._reconcile()

    def _on_vault_kv_connected(self, event: vault_kv.VaultKvConnectedEvent) -> None:
        relation = self.model.get_relation(event.relation_name, event.relation_id)
        if relation is not None:
            self._request_vault_credentials(relation)
        self._reconcile()

    def _on_vault_kv_ready(self, _event) -> None:
        self._reconcile()

    def _on_vault_kv_gone_away(self, _event) -> None:
        self._reconcile()

    def _ensure_vault_nonce(self) -> None:
        """Create a per-unit Juju secret holding the vault-kv nonce (idempotent)."""
        try:
            self.model.get_secret(label=VAULT_NONCE_SECRET_LABEL)
            return
        except ops.SecretNotFoundError:
            pass
        self.unit.add_secret(
            {"nonce": secrets.token_hex(16)},
            label=VAULT_NONCE_SECRET_LABEL,
            description="Nonce for vault-kv relation",
        )

    def _get_vault_nonce(self) -> str | None:
        """Return the persisted vault-kv nonce, or None if missing."""
        try:
            secret = self.model.get_secret(label=VAULT_NONCE_SECRET_LABEL)
            content = secret.get_content(refresh=True)
        except (ops.SecretNotFoundError, ops.ModelError):
            return None
        return content.get("nonce")

    def _request_vault_credentials(self, relation: ops.Relation) -> None:
        """Publish egress subnets + nonce on the vault-kv relation.

        Best-effort: model errors (e.g. binding not yet available) are
        logged and swallowed so the handler doesn't crash.
        """
        nonce = self._get_vault_nonce()
        if nonce is None:
            logger.debug("vault-kv nonce not yet created; skipping credential request")
            return
        try:
            binding = self.model.get_binding(relation)
            if binding is None or binding.network is None:
                logger.debug("vault-kv binding not yet available")
                return
            subnets = [str(subnet) for subnet in binding.network.egress_subnets]
            if binding.network.interfaces:
                subnets.append(str(binding.network.interfaces[0].subnet))
            self._vault_kv.request_credentials(relation, subnets, nonce)
        except ops.ModelError as exc:
            logger.debug("vault-kv credential request skipped: %s", exc)

    def _on_secret_changed(self, _event) -> None:
        self._reconcile()

    def _on_peer_created(self, _event) -> None:
        self._reconcile()

    def _on_database_changed(self, _event) -> None:
        self._reconcile()

    def _on_metrics_changed(self, _event) -> None:
        self._reconcile()

    def _on_s3_credentials_changed(self, _event) -> None:
        logger.info("S3 credentials available")
        self._reconcile()

    def _on_s3_credentials_gone(self, _event) -> None:
        logger.info("S3 relation departed")
        self._reconcile()

    def _on_ingress_changed(self, _event) -> None:
        if not hasattr(self, "_traefik_route"):
            ingress_relation = self.model.get_relation(INGRESS_RELATION_NAME)
            if ingress_relation is not None:
                self._traefik_route = TraefikRouteRequirer(self, ingress_relation, INGRESS_RELATION_NAME)
        self._reconcile()

    def _on_storage_attached(self, _event) -> None:
        self._reconcile()

    def _on_storage_detaching(self, _event) -> None:
        # During storage-detaching the storage may still appear in
        # self.model.storages, so force the reconcile to treat it as gone.
        self._reconcile(binary_data_detaching=True)

    def _on_database_broken(self, _event) -> None:
        container = self.unit.get_container(CONTAINER_NAME)
        if container.can_connect():
            try:
                container.stop(SERVICE_NAME)
            except pebble.Error:
                logger.debug("n8n service was not running on relation-broken")
        self.unit.status = BlockedStatus("waiting for postgresql relation")

    def _on_get_encryption_key_action(self, event: ops.ActionEvent) -> None:
        key, msg = self._effective_encryption_key()
        if key is None:
            event.fail(msg or "encryption key not yet available")
            return
        event.set_results({"encryption-key": key})

    def _on_create_admin_action(self, event: ops.ActionEvent) -> None:
        if not self.unit.is_leader():
            event.fail(ERR_NOT_LEADER)
            return
        state = CharmState(self)
        if state.peer_relation is None:
            event.fail(ERR_PEER_NOT_READY)
            return

        container = self.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            event.fail(ERR_CONTAINER_NOT_READY)
            return

        if self._probe_owner_setup() is not False:
            event.fail(ERR_ALREADY_BOOTSTRAPPED)
            return

        email = event.params["email"]
        first_name = event.params["first-name"]
        last_name = event.params["last-name"]
        password_hash = bcrypt.hashpw(event.params["password"].encode(), bcrypt.gensalt(rounds=10)).decode()

        container.add_layer(
            "n8n-bootstrap",
            {
                "summary": "n8n owner bootstrap",
                "services": {
                    "n8n": {
                        "override": "merge",
                        "environment": {
                            "N8N_INSTANCE_OWNER_MANAGED_BY_ENV": "true",
                            "N8N_INSTANCE_OWNER_EMAIL": email,
                            "N8N_INSTANCE_OWNER_FIRST_NAME": first_name,
                            "N8N_INSTANCE_OWNER_LAST_NAME": last_name,
                            "N8N_INSTANCE_OWNER_PASSWORD_HASH": password_hash,
                        },
                    }
                },
            },
            combine=True,
        )
        container.replan()

        event.set_results({"created": True, "email": email})

    def _on_restart_action(self, event: ops.ActionEvent) -> None:
        container = self.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            event.fail(ERR_CONTAINER_NOT_READY)
            return
        if SERVICE_NAME not in container.get_plan().services:
            event.fail(ERR_SERVICE_NOT_CONFIGURED)
            return
        self.unit.status = MaintenanceStatus(STATUS_RESTARTING)
        try:
            container.restart(SERVICE_NAME)
        except pebble.Error as exc:
            event.fail(f"failed to restart n8n: {exc}")
            return
        self._reconcile()
        event.set_results({"restarted": True})

    def _resolve_secret_uri(self, config_name: str) -> tuple[str | None, str | None]:
        """Look up a Juju secret referenced by a config option.

        Returns (value, None) when the secret is present and exposes a 'value'
        field; (None, blocked_msg) when the URI is set but not granted or
        malformed; (None, None) when the config is empty.
        """
        uri = self.config.get(config_name)
        if not uri:
            return (None, None)
        try:
            secret = self.model.get_secret(id=uri)
            content = secret.get_content(refresh=True)
        except (ops.SecretNotFoundError, ops.ModelError):
            return (None, f"{config_name} secret not granted to app")
        value = content.get("value")
        if not value:
            return (None, f"{config_name} secret missing 'value' field")
        return (value, None)

    def _effective_encryption_key(self) -> tuple[str | None, str | None]:
        """Return (key, blocked_msg).

        - (key, None): success.
        - (None, msg): terminal Blocked condition.
        - (None, None): not-yet-ready; caller should emit WaitingStatus.
        """
        override, blocked_msg = self._resolve_secret_uri(ENCRYPTION_KEY_CONFIG)
        if blocked_msg is not None:
            return (None, blocked_msg)
        if override is not None:
            return (override, None)

        state = CharmState(self)
        if state.peer_relation is None:
            return (None, None)

        if state.encryption_key_secret_id is None:
            if not self.unit.is_leader():
                return (None, None)
            generated = secrets.token_hex(24)
            secret = self.app.add_secret(
                content={"value": generated},
                label=ENCRYPTION_KEY_SECRET_LABEL,
            )
            state.encryption_key_secret_id = secret.id
            return (generated, None)

        try:
            secret = self.model.get_secret(id=state.encryption_key_secret_id)
            content = secret.get_content()
        except (ops.SecretNotFoundError, ops.ModelError):
            return (None, "stored encryption-key secret is missing")
        value = content.get("value")
        if not value:
            return (None, "stored encryption-key secret missing 'value' field")
        return (value, None)

    def _resolve_juju_entries(self, entries) -> tuple[dict[str, str] | None, str | None]:
        """Resolve each environment.juju entry into a flat {name: value} dict.

        Atomic: any single failure returns (None, msg) and the caller
        skips user_env entirely so the workload still runs on
        charm-managed envs while the unit sits in BlockedStatus.
        """
        resolved: dict[str, str] = {}
        for entry in entries:
            try:
                secret = self.model.get_secret(id=entry.secret_id)
                content = secret.get_content(refresh=True)
            except (ops.SecretNotFoundError, ops.ModelError):
                return (
                    None,
                    f"environment juju entry '{entry.name}': secret not granted",
                )
            if entry.key not in content:
                return (
                    None,
                    f"environment juju entry '{entry.name}': key '{entry.key}' not in secret",
                )
            resolved[entry.name] = content[entry.key]
        return (resolved, None)

    def _vault_client_for(self, relation: ops.Relation) -> hvac.Client:
        """Construct and authenticate an hvac.Client for the given vault-kv relation.

        Test seam: subclass or monkeypatch to bypass the real Vault. Raises
        ``hvac.exceptions.VaultError`` or ``requests.exceptions.RequestException``
        on connectivity / login failure. Raises ``RuntimeError`` if relation
        data is missing the brokered credentials Juju secret.
        """
        vault_url = self._vault_kv.get_vault_url(relation)
        ca_cert = self._vault_kv.get_ca_certificate(relation)
        cred_secret_id = self._vault_kv.get_unit_credentials(relation)
        if cred_secret_id is None:
            raise RuntimeError("brokered credentials secret not yet available")
        secret = self.model.get_secret(id=cred_secret_id)
        content = secret.get_content(refresh=True)
        role_id = content.get("role-id") or content.get("role_id")
        role_secret_id = content.get("role-secret-id") or content.get("role_secret_id")
        if ca_cert:
            with open(VAULT_CA_PATH, "w", encoding="utf-8") as fh:
                fh.write(ca_cert)
            verify: bool | str = VAULT_CA_PATH
        else:
            verify = False
        client = hvac.Client(url=vault_url, verify=verify)
        client.auth.approle.login(role_id=role_id, secret_id=role_secret_id)
        return client

    def _resolve_vault_entries(self, entries) -> tuple[dict[str, str] | None, str | None]:
        """Resolve each environment.vault entry into a flat {name: value} dict.

        Atomic, like ``_resolve_juju_entries``: any single failure returns
        ``(None, msg)`` and the caller skips ``user_env`` entirely. Never
        raises; vault errors are caught and reported via the message.
        Secret values (role-id, role-secret-id, resolved values) are never
        logged.
        """

        def _err(entry_name: str, reason: str) -> tuple[None, str]:
            return (None, f"environment vault entry '{entry_name}': {reason}")

        def _short(exc: BaseException) -> str:
            text = str(exc).strip().splitlines()
            return text[0] if text else exc.__class__.__name__

        relation = self.model.get_relation(VAULT_RELATION_NAME)
        if relation is None or relation.app is None or not dict(relation.data[relation.app]):
            return _err(entries[0].name, "vault-k8s relation not joined")

        if self._vault_kv.get_unit_credentials(relation) is None:
            return _err(entries[0].name, "vault credentials not ready")
        if not self._vault_kv.get_vault_url(relation) or not self._vault_kv.get_mount(relation):
            return _err(entries[0].name, "vault credentials not ready")

        try:
            client = self._vault_client_for(relation)
        except (hvac.exceptions.VaultError, requests.exceptions.RequestException) as exc:
            return _err(entries[0].name, f"vault login failed ({_short(exc)})")
        except (ops.SecretNotFoundError, ops.ModelError, RuntimeError):
            return _err(entries[0].name, "vault credentials not ready")

        mount = self._vault_kv.get_mount(relation)
        resolved: dict[str, str] = {}
        for entry in entries:
            try:
                response = client.secrets.kv.v2.read_secret_version(
                    path=entry.path,
                    mount_point=mount,
                    raise_on_deleted_version=True,
                )
            except hvac.exceptions.InvalidPath:
                return _err(entry.name, f"path '{entry.path}' not found")
            except (hvac.exceptions.VaultError, requests.exceptions.RequestException) as exc:
                return _err(entry.name, f"vault read failed ({_short(exc)})")
            blob = response.get("data", {}).get("data", {}) if isinstance(response, dict) else {}
            if entry.key not in blob:
                return _err(entry.name, f"key '{entry.key}' not in path '{entry.path}'")
            resolved[entry.name] = blob[entry.key]
        return (resolved, None)

    def _reconcile(self, *, binary_data_detaching: bool = False) -> None:
        key, blocked_msg = self._effective_encryption_key()
        if blocked_msg is not None:
            self.unit.status = BlockedStatus(blocked_msg)
            return
        if key is None:
            self.unit.status = WaitingStatus("waiting for encryption key")
            return

        tier1_env, tier1_err = build_tier1_env(self.config)
        if tier1_err is not None:
            self.unit.status = BlockedStatus(tier1_err)
            return

        runner_env, runner_err = build_runner_env(self.config)
        if runner_err is not None:
            self.unit.status = BlockedStatus(runner_err)
            return

        smtp_pw, smtp_pw_err = self._resolve_secret_uri("smtp-password")
        if smtp_pw_err is not None:
            self.unit.status = BlockedStatus(smtp_pw_err)
            return

        smtp_env, smtp_err = build_smtp_env(self.config, smtp_pw)
        if smtp_err is not None:
            self.unit.status = BlockedStatus(smtp_err)
            return

        parsed_env, env_err = parse_environment_config(str(self.config.get(ENVIRONMENT_CONFIG, "")))
        if env_err is not None:
            self.unit.status = BlockedStatus(env_err)
            return
        assert parsed_env is not None  # for type narrowing
        resolved_juju, juju_err = self._resolve_juju_entries(parsed_env.juju)
        if parsed_env.vault:
            resolved_vault, vault_err = self._resolve_vault_entries(parsed_env.vault)
        else:
            resolved_vault, vault_err = None, None
        user_env: dict[str, str] | None
        if juju_err is not None:
            user_env_blocked_msg = juju_err
            user_env = None
        elif vault_err is not None:
            user_env_blocked_msg = vault_err
            user_env = None
        else:
            user_env_blocked_msg = None
            assert resolved_juju is not None
            user_env = build_environment_user_env(parsed_env, resolved_juju, resolved_vault)

        db_env = self._db_env()
        if db_env is None:
            if self.model.get_relation(DB_RELATION_NAME) is None:
                self.unit.status = BlockedStatus("waiting for postgresql relation")
            else:
                self.unit.status = WaitingStatus("waiting for database credentials")
            return

        if self.model.get_relation(INGRESS_RELATION_NAME) is None:
            self.unit.status = BlockedStatus("waiting for ingress relation")
            return
        external_host = self._external_host()
        hostname = external_host or self.app.name
        scheme = self._scheme() or "http"
        url = f"{scheme}://{hostname}/"
        self._publish_traefik_route(hostname)

        container = self.unit.get_container(CONTAINER_NAME)
        if not container.can_connect():
            self.unit.status = MaintenanceStatus("waiting for pebble")
            return

        self.unit.status = MaintenanceStatus("starting n8n")
        s3_creds = self._s3_creds()
        s3_env = build_s3_env(s3_creds) if s3_creds else None
        binary_data_attached = not binary_data_detaching and self._binary_data_attached()
        if s3_creds:
            binary_data_mode = "s3"
        elif binary_data_attached:
            binary_data_mode = "filesystem"
        else:
            binary_data_mode = None
        if binary_data_attached:
            self._chown_binary_data_mount(container)
        metrics_env = {"N8N_METRICS": "true"} if self.model.get_relation(METRICS_RELATION_NAME) is not None else None
        layer, conflict_keys = build_layer(
            db_env,
            key,
            url_env=build_url_env(url),
            tier1_env=tier1_env,
            runner_env=runner_env,
            smtp_env=smtp_env,
            metrics_env=metrics_env,
            s3_env=s3_env,
            binary_data_mode=binary_data_mode,
            user_env=user_env,
        )
        container.add_layer(CONTAINER_NAME, layer, combine=True)
        container.replan()

        for k in conflict_keys:
            origin = CHARM_MANAGED_ENV_ORIGIN.get(k, "charm-managed")
            logger.warning("environment: dropping %s (%s)", k, origin)

        try:
            ready = container.get_check("ready").status == pebble.CheckStatus.UP
        except pebble.Error:
            ready = False
        if not ready:
            self.unit.status = MaintenanceStatus(STATUS_WAITING_N8N)
            return

        if user_env_blocked_msg is not None:
            self.unit.status = BlockedStatus(user_env_blocked_msg)
            return

        status_parts: list[str] = []
        if conflict_keys:
            status_parts.append(
                f"ignoring user env overrides: {', '.join(conflict_keys)} " "(charm-managed; see juju debug-log)"
            )
        if s3_creds and binary_data_attached:
            status_parts.append("binary data: s3 (storage mount idle)")
        elif not s3_creds and not binary_data_attached:
            status_parts.append(STATUS_BINARY_DATA_FALLBACK)
        self.unit.status = ActiveStatus(" | ".join(status_parts))

    def _probe_owner_setup(self) -> bool | None:
        """True → owner exists; False → not yet; None → cannot tell."""
        url = f"http://localhost:{N8N_PORT}{OWNER_PROBE_PATH}"
        try:
            with urllib.request.urlopen(url, timeout=OWNER_PROBE_TIMEOUT_S) as r:
                payload = json.loads(r.read().decode("utf-8"))
            data = payload.get("data", payload)
            show_setup = data["userManagement"]["showSetupOnFirstLoad"]
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
            logger.debug("owner-setup probe inconclusive: %s", exc)
            return None
        return not bool(show_setup)

    def _external_host(self) -> str:
        return self._traefik_route.external_host if hasattr(self, "_traefik_route") else ""

    def _scheme(self) -> str:
        return self._traefik_route.scheme if hasattr(self, "_traefik_route") else ""

    def _publish_traefik_route(self, hostname: str) -> None:
        if not hasattr(self, "_traefik_route") or not self.unit.is_leader() or not self._traefik_route.is_ready():
            return
        router_name = f"juju-{self.model.name}-{self.app.name}"
        service_name = f"{router_name}-service"
        self._traefik_route.submit_to_traefik(
            config={
                "http": {
                    "routers": {
                        router_name: {
                            "entryPoints": ["web"],
                            "rule": f"Host(`{hostname}`)",
                            "service": service_name,
                        },
                    },
                    "services": {
                        service_name: {
                            "loadBalancer": {
                                "servers": [
                                    {
                                        "url": f"http://{self.app.name}-endpoints.{self.model.name}.svc.cluster.local:{N8N_PORT}"
                                    }
                                ],
                            },
                        },
                    },
                },
            },
        )

    def _binary_data_attached(self) -> bool:
        """True iff the binary-data filesystem storage is attached to this unit."""
        storages = self.model.storages.get(BINARY_DATA_STORAGE_NAME, [])
        return any(getattr(s, "location", None) for s in storages)

    def _chown_binary_data_mount(self, container: ops.Container) -> None:
        """Ensure the n8n `node` user owns the mounted binary-data dir.

        Idempotent and best-effort: logs a warning if the chown fails so
        we don't stall reconcile on workload images that don't ship
        chown, or storage classes that already mount with the right uid.
        """
        try:
            container.exec(
                ["chown", "-R", "node:node", BINARY_DATA_MOUNT_PATH],
                timeout=10,
            ).wait()
        except (pebble.Error, ops.pebble.ExecError):
            logger.warning(
                "chown of %s failed; n8n may be unable to write attachments",
                BINARY_DATA_MOUNT_PATH,
            )

    def _s3_creds(self) -> dict | None:
        """Return the 5-key S3 creds dict, or None if any key is missing/empty.

        Keys: bucket, endpoint, region, access-key, secret-key. Never logs values.
        """
        info = self._s3.get_s3_connection_info()
        keys = ("bucket", "endpoint", "region", "access-key", "secret-key")
        creds = {k: info.get(k, "") for k in keys}
        return creds if all(creds.values()) else None

    def _db_env(self) -> dict | None:
        """Return the Postgres env-var dict for n8n, or None if not ready."""
        rel = self.model.get_relation(DB_RELATION_NAME)
        if rel is None:
            return None
        per_rel = self.database.fetch_relation_data().get(rel.id, {})
        endpoints = per_rel.get("endpoints")
        username = per_rel.get("username")
        password = per_rel.get("password")
        if not endpoints or not username or not password:
            return None
        host, _, port = endpoints.split(",")[0].partition(":")
        return {
            "DB_TYPE": "postgresdb",
            "DB_POSTGRESDB_HOST": host,
            "DB_POSTGRESDB_PORT": port or "5432",
            "DB_POSTGRESDB_DATABASE": per_rel.get("database") or DATABASE_NAME,
            "DB_POSTGRESDB_USER": username,
            "DB_POSTGRESDB_PASSWORD": password,
        }


if __name__ == "__main__":  # pragma: no cover
    main(N8nK8sCharm)
