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

### `ingress`

**ingress** (required, interface `ingress`, limit 1). The charm requests ingress through the provider-agnostic `ingress` v2 interface using `charms.traefik_k8s.v2.ingress.IngressPerAppRequirer`. Any v2-compatible provider satisfies it, including `traefik-k8s` and `nginx-ingress-integrator`. The charm publishes its routing requirements (app name, model, port `5678`) and reads the external URL the provider returns. It does not publish provider-specific router or service config.

The charm sets six env vars in `src/pebble.py` from the external URL. `N8N_HOST` is the URL hostname; `WEBHOOK_URL` and `N8N_EDITOR_BASE_URL` are set to the full external URL; `N8N_PROTOCOL` is the URL scheme, so it is `https` when TLS terminates at the proxy. `N8N_PORT` stays `"5678"` regardless of the external URL because it is the port n8n listens on inside the pod. `N8N_PROXY_HOPS` is set to `"1"` so n8n trusts the `X-Forwarded-For`/`X-Forwarded-Host`/`X-Forwarded-Proto` headers added by the single fronting proxy.

The charm expects host-based routing — n8n served at the root of a subdomain, per n8n's reverse-proxy guidance — so it sets no `N8N_PATH` and requests no prefix stripping. Configure the provider accordingly: on `traefik-k8s`, set `routing_mode=subdomain` and `external_hostname`; on `nginx-ingress-integrator`, set `service-hostname`. n8n defaults to `N8N_SECURE_COOKIE=true`, so login requires HTTPS at the proxy; HTTP-only test setups can override it through the `environment` config option.

- **Interface**: `ingress`
- **Limit**: 1
- **Optional**: no
- **When absent**: unit blocks with `"waiting for ingress relation"`
- **When relation present but the provider has not published a URL yet**: unit waits with `"waiting for ingress URL"`

#### Migrating from `traefik-route`

Earlier charm revisions exposed ingress over a `traefik-route` endpoint (interface `traefik_route`). That endpoint no longer exists. After upgrading, the old `traefik-route` relation is gone and the operator must re-relate on `ingress`:

```bash
juju remove-relation n8n:traefik-route traefik-k8s
juju integrate n8n:ingress traefik-k8s
```

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
