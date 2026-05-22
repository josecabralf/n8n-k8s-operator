# Relations

All endpoints are declared in `charmcraft.yaml`.

---

## Requires

### `postgresql`

**postgresql** (required, interface `postgresql_client`, limit 1). PostgreSQL is mandatory. The charm reads `endpoints`, `username`, `password`, and `database` from the relation and exports `DB_TYPE="postgresdb"`, `DB_POSTGRESDB_HOST`, `DB_POSTGRESDB_PORT`, `DB_POSTGRESDB_DATABASE`, `DB_POSTGRESDB_USER`, and `DB_POSTGRESDB_PASSWORD` to n8n.

- **Interface**: `postgresql_client`
- **Limit**: 1
- **Optional**: no
- **When absent**: unit blocks with `"waiting for postgresql relation"`
- **When relation present but credentials not yet available**: unit waits with `"waiting for database credentials"`

---

### `traefik-route`

**traefik-route** (required, interface `traefik_route`, limit 1). The charm requires ingress to publish the n8n URL and configure Traefik routing rules. The charm reads `external_host` and `scheme` from the relation and publishes a Traefik router config with router name `juju-<model>-<app>`, host rule `Host(\`<hostname>\`)`, and backend service URL `http://<app>-endpoints.<model>.svc.cluster.local:5678`. The external URL is `<scheme>://<hostname>/`; the hostname falls back to the application name when `external_host` is empty.

- **Interface**: `traefik_route`
- **Limit**: 1
- **Optional**: no
- **When absent**: unit blocks with `"waiting for ingress relation"`

---

### `s3`

**s3** (optional, interface `s3`, limit 1). Stores binary workflow data in S3-compatible object storage. When absent the charm falls back to in-database storage. The charm reads `bucket`, `endpoint`, `region`, `access-key`, and `secret-key` from the relation and exports `N8N_EXTERNAL_STORAGE_S3_HOST`, `N8N_EXTERNAL_STORAGE_S3_BUCKET_NAME`, `N8N_EXTERNAL_STORAGE_S3_BUCKET_REGION`, `N8N_EXTERNAL_STORAGE_S3_ACCESS_KEY`, `N8N_EXTERNAL_STORAGE_S3_ACCESS_SECRET`, `N8N_AVAILABLE_BINARY_DATA_MODES="filesystem,s3"`, and `N8N_DEFAULT_BINARY_DATA_MODE="s3"` to n8n.

- **Interface**: `s3`
- **Limit**: 1
- **Optional**: yes
- **When absent**: no BlockedStatus; when neither S3 nor a `binary-data` storage mount is present, the unit reaches ActiveStatus with the message `"binary data in DB; attach 'binary-data' storage or relate s3-integrator for production use"`

---

### `logging`

**logging** (optional, interface `loki_push_api`, limit 1). Forwards container service logs to Loki. When joined, stdout and stderr from all services are forwarded to the related Loki endpoint automatically.

- **Interface**: `loki_push_api`
- **Limit**: 1
- **Optional**: yes (declared `optional: true` in `charmcraft.yaml`)
- **When absent**: no BlockedStatus; logging goes to the container's stdout only

---

### `vault-k8s`

**vault-k8s** (optional, interface `vault-kv`, limit 1). Required when the `environment` config contains one or more `vault:` entries. The charm reads `vault_url`, `ca_certificate`, and `credentials` from the relation; the credentials Juju secret contains `role-id` and `role-secret-id`. The charm publishes a unit nonce and egress subnets (including the pod-interface subnet) to request AppRole credentials. The Vault mount name follows the pattern `charm-<app-name>-n8n`.

- **Interface**: `vault-kv`
- **Limit**: 1
- **Optional**: yes (declared `optional: true` in `charmcraft.yaml`)
- **When absent but vault entries present**: unit blocks with `"environment vault entry '<name>': vault-k8s relation not joined"`
- **When joined but credentials not ready**: unit blocks with `"environment vault entry '<name>': vault credentials not ready"`

---

## Provides

### `metrics-endpoint`

**metrics-endpoint** (interface `prometheus_scrape`). Exposes Prometheus scrape targets for the n8n process. Publishes `[{"static_configs": [{"targets": ["*:5678"]}]}]`.

- **Interface**: `prometheus_scrape`

---

### `grafana-dashboard`

**grafana-dashboard** (interface `grafana_dashboard`). Publishes a pre-built Grafana dashboard for n8n metrics when related to Grafana.

- **Interface**: `grafana_dashboard`

---

## Peers

### `n8n-peers`

**n8n-peers** (interface `n8n_peers`). The peer relation used to coordinate state between units. The leader writes the encryption key secret ID to the peer databag; follower units read it from there.

- **Interface**: `n8n_peers`
- **When not yet joined**: the `create-admin` action fails with `"peer relation not yet joined; retry"`; on follower units the charm waits with `"waiting for encryption key"` until the leader publishes the secret ID
