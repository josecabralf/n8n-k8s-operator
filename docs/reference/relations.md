# Relations

This page lists every relation endpoint exposed by the n8n charm, declared in `charmcraft.yaml:35-72`. Each entry cites `charmcraft.yaml` and `src/charm.py`.

---

## Requires

### `postgresql`

The charm requires a PostgreSQL database to persist workflow state. `charmcraft.yaml:54-56`.

- **Interface**: `postgresql_client`
- **Limit**: 1
- **Optional**: no
- **Library**: `charms.data_platform_libs.v0.data_interfaces.DatabaseRequires` (`src/charm.py:17`), constructed at `src/charm.py:81-85`
- **Data read** (`_db_env`, `src/charm.py:667-686`): `endpoints`, `username`, `password`, `database` (defaults to `"n8n"`)
- **Env vars set**: `DB_TYPE="postgresdb"`, `DB_POSTGRESDB_HOST`, `DB_POSTGRESDB_PORT`, `DB_POSTGRESDB_DATABASE`, `DB_POSTGRESDB_USER`, `DB_POSTGRESDB_PASSWORD`
- **When absent**: unit blocks with `"waiting for postgresql relation"` (`src/charm.py:246`, `src/charm.py:512`)
- **When relation present but credentials not yet available**: unit waits with `"waiting for database credentials"` (`src/charm.py:514`)

---

### `traefik-route`

The charm requires an ingress relation to publish the n8n URL and configure Traefik routing rules. `charmcraft.yaml:57-59`.

- **Interface**: `traefik_route`
- **Limit**: 1
- **Optional**: no
- **Library**: `charms.traefik_k8s.v0.traefik_route.TraefikRouteRequirer` (`src/charm.py:22`), constructed at `src/charm.py:105-107`, `226-228`
- **Data read**: `external_host`, `scheme` (`src/charm.py:598-602`)
- **Data published** (`_publish_traefik_route`, `src/charm.py:604-632`): Traefik router config with router name `juju-<model>-<app>`, host rule `Host(\`<hostname>\`)`, backend service URL `http://<app>-endpoints.<model>.svc.cluster.local:5678`
- **URL derivation**: external URL is `<scheme>://<hostname>/`; hostname falls back to `self.app.name` when `external_host` is empty (`src/charm.py:521-523`)
- **When absent**: unit blocks with `"waiting for ingress relation"` (`src/charm.py:518`)

---

### `s3`

An optional relation for storing binary workflow data in S3-compatible object storage. When absent the charm falls back to filesystem or in-database storage. `charmcraft.yaml:60-62`.

- **Interface**: `s3`
- **Limit**: 1
- **Optional**: yes (no explicit `optional:` flag in `charmcraft.yaml`, but absence does not block the unit)
- **Library**: `charms.data_platform_libs.v0.s3.S3Requirer` (`src/charm.py:18`), constructed at `src/charm.py:118`
- **Data read** (`_s3_creds`, `src/charm.py:657-665`): `bucket`, `endpoint`, `region`, `access-key`, `secret-key`
- **Env vars set when joined**: `N8N_EXTERNAL_STORAGE_S3_HOST`, `N8N_EXTERNAL_STORAGE_S3_BUCKET_NAME`, `N8N_EXTERNAL_STORAGE_S3_BUCKET_REGION`, `N8N_EXTERNAL_STORAGE_S3_ACCESS_KEY`, `N8N_EXTERNAL_STORAGE_S3_ACCESS_SECRET`, `N8N_AVAILABLE_BINARY_DATA_MODES="filesystem,s3"`, `N8N_DEFAULT_BINARY_DATA_MODE="s3"`
- **When absent**: no BlockedStatus; the unit reaches ActiveStatus with the message `"binary data in DB; attach 'binary-data' storage or relate s3-integrator for production use"` appended to the status parts when neither S3 credentials nor a `binary-data` storage mount is present (`src/charm.py:581-582`)

---

### `logging`

An optional relation for forwarding Pebble service logs to Loki. `charmcraft.yaml:50-53`.

- **Interface**: `loki_push_api`
- **Limit**: 1
- **Optional**: yes (`optional: true`, `charmcraft.yaml:53`)
- **Library**: `charms.loki_k8s.v1.loki_push_api.LogForwarder` (`src/charm.py:20`), constructed at `src/charm.py:115`
- **Behavior**: when joined, forwards all Pebble services' stdout and stderr to the related Loki endpoint automatically
- **When absent**: no BlockedStatus; logging goes to the container's stdout only

---

### `vault-k8s`

An optional relation for resolving `vault:` entries in the `environment` config key. `charmcraft.yaml:63-66`.

- **Interface**: `vault-kv`
- **Limit**: 1
- **Optional**: yes (`optional: true`, `charmcraft.yaml:66`)
- **Library**: `charms.vault_k8s.v0.vault_kv.VaultKvRequires` (`src/charm.py:23`), constructed at `src/charm.py:121`
- **Required when**: the `environment` config contains one or more `vault:` entries
- **Mount name pattern**: `charm-<app-name>-n8n` via `mount_suffix="n8n"`
- **Data read**: `vault_url`, `ca_certificate`, `credentials` (`src/charm.py:392-394`); the credentials Juju secret contains `role-id` and `role-secret-id`
- **Data published** (`_request_vault_credentials`, `src/charm.py:182-202`): unit nonce, egress subnets, and the pod-interface subnet
- **When absent but vault entries present**: unit blocks with `"environment vault entry '<name>': vault-k8s relation not joined"` (`src/charm.py:430`)
- **When joined but credentials not ready**: unit blocks with `"environment vault entry '<name>': vault credentials not ready"` (`src/charm.py:432-442`)

---

## Provides

### `metrics-endpoint`

Exposes Prometheus scrape targets for the n8n process. `charmcraft.yaml:69-70`.

- **Interface**: `prometheus_scrape`
- **Library**: `MetricsEndpointProvider` (`src/charm.py:21`), constructed at `src/charm.py:108-113`
- **Data published**: `[{"static_configs": [{"targets": ["*:5678"]}]}]`

---

### `grafana-dashboard`

Publishes a pre-built Grafana dashboard for n8n metrics. `charmcraft.yaml:71-72`.

- **Interface**: `grafana_dashboard`
- **Library**: `GrafanaDashboardProvider` (`src/charm.py:19`), constructed at `src/charm.py:114`
- **Dashboard source**: `src/grafana_dashboards/n8n.json`, auto-published by the library

---

## Peers

### `n8n-peers`

The peer relation used to coordinate state between units, primarily for sharing the encryption key secret ID. `charmcraft.yaml:35-37`.

- **Interface**: `n8n_peers`
- **State management**: `CharmState` in `src/state.py:12-43` wraps the peer databag
- **Stored key**: `"encryption-key-secret-id"` (`src/state.py:9`), written by the leader at `src/charm.py:346`
- **When not yet joined**: the `create-admin` action fails with `"peer relation not yet joined; retry"` (`ERR_PEER_NOT_READY`, `src/charm.py:72`); on follower units the charm waits with `"waiting for encryption key"` until the leader publishes the secret ID
