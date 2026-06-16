# Statuses

This page lists every unit status message produced by the n8n charm.

---

## BlockedStatus

The unit requires operator intervention before it can proceed.

### Config and secret errors

- **`"<config-name> secret not granted to app"`** — the named config key (`encryption-key` or `smtp-password`) contains a Juju secret URI but the secret has not been granted to the application. Run `juju grant-secret <secret-id> n8n` to resolve.

- **`"<config-name> secret missing 'value' field"`** — the Juju secret referenced by `encryption-key` or `smtp-password` does not contain a field named `value` in the current revision.

- **`"stored encryption-key secret is missing"`** — the charm previously stored an auto-generated encryption key in a Juju secret, but that secret no longer exists (for example, it was deleted manually).

- **`"stored encryption-key secret missing 'value' field"`** — the auto-generated encryption key secret exists but the current revision has no `value` field.

- **`"invalid log-level '<value>'; must be one of: debug, info, warn, error"`** — `log-level` is set to a value other than `debug`, `info`, `warn`, or `error`.

- **`"timezone must not be empty"`** — `timezone` is set to an empty string.

- **`"invalid executions-data-save-on-error '<value>'; must be 'all' or 'none'"`** — `executions-data-save-on-error` is set to a value other than `all` or `none`.

- **`"invalid executions-data-save-on-success '<value>'; must be 'all' or 'none'"`** — `executions-data-save-on-success` is set to a value other than `all` or `none`.

- **`"executions-data-max-age-hours must be >= 0"`** — `executions-data-max-age-hours` is set to a negative integer.

### SMTP errors

- **`"smtp-host, smtp-user, and smtp-password must all be set together"`** — exactly one or two of `smtp-host`, `smtp-user`, `smtp-password` are non-empty. All three must be set or all three must be empty.

- **`"invalid smtp-port '<port>'; must be 1–65535"`** — `smtp-port` is outside the range 1 to 65535 inclusive.

### Relation errors

- **`"waiting for postgresql relation"`** — no `postgresql` relation is joined. Resolve by running `juju integrate n8n postgresql-k8s`.

- **`"waiting for ingress relation"`** — no `ingress` relation is joined. Resolve by running `juju integrate n8n:ingress traefik-k8s`.

### `environment` config parse errors

See [`../how-to/use-environment-escape-hatch.md`](../how-to/use-environment-escape-hatch.md) for the complete list of parse-time BlockedStatus messages for malformed `environment` config YAML.

### `environment` config Juju secret errors

- **`"environment juju entry '<name>': secret not granted"`** — an `environment.juju` entry references a Juju secret that has not been granted to the application.

- **`"environment juju entry '<name>': key '<key>' not in secret"`** — an `environment.juju` entry references a key that does not exist in the secret revision.

### `environment` config Vault errors

- **`"environment vault entry '<name>': vault-k8s relation not joined"`** — the `environment` config contains a `vault:` entry but the `vault-k8s` relation is not joined. Resolve by running `juju integrate n8n vault-k8s`.

- **`"environment vault entry '<name>': vault credentials not ready"`** — the `vault-k8s` relation is joined but the credentials Juju secret is not yet available.

- **`"environment vault entry '<name>': vault login failed (<short-error>)"`** — AppRole authentication against Vault failed. `<short-error>` is a truncated error message. Check that the unit's egress subnets are included in the Vault KV CIDR list.

- **`"environment vault entry '<name>': path '<path>' not found"`** — the KV path referenced in the `vault:` entry does not exist in the Vault mount.

- **`"environment vault entry '<name>': vault read failed (<short-error>)"`** — the Vault KV read returned an unexpected error.

- **`"environment vault entry '<name>': key '<key>' not in path '<path>'"`** — the KV path exists but the specified key is absent from the secret data.

---

## WaitingStatus

The unit is healthy but waiting for an external dependency.

- **`"waiting for encryption key"`** — emitted on follower units before the leader has written the encryption key secret ID to the peer databag, or while the peer relation itself is still joining.

- **`"waiting for database credentials"`** — the `postgresql` relation is joined but connection credentials have not yet been populated in the relation data.

- **`"waiting for ingress URL"`** — the `ingress` relation is joined but no external URL is currently published. `_reconcile` sets this whenever the provider's published URL is empty (`src/charm.py`), covering both the initial wait before the provider first publishes a URL and the case where the provider later *withdraws* one (for example, clearing `external_hostname` on a `traefik-k8s` provider in `routing_mode=subdomain` empties the relation databag without breaking the relation). The charm reads the live provider databag directly rather than the requirer's cached `url`, and also reconciles on `ingress-relation-changed`, so a withdrawn URL drops the unit out of `active` to this status instead of going unnoticed. The workload keeps running with its previous env and recovers automatically when a URL is republished.

---

## MaintenanceStatus

The unit is performing an operation and is temporarily unavailable.

- **`"waiting for pebble"`** — the Pebble socket is not yet ready.

- **`"starting n8n"`** — the Pebble layer has been applied and the service replanned, but the readiness probe has not yet been checked.

- **`"waiting for n8n to start"`** — Pebble is connected and the layer is active, but the HTTP readiness probe at `http://localhost:5678/healthz/readiness` has not yet returned a successful response.

- **`"restarting n8n"`** — transient status shown while the `restart` action cycles the workload service. The charm re-runs its reconcile path afterward to restore status.

---

## ActiveStatus

The unit is running normally. The status message is assembled from optional parts joined by `" | "` (space-pipe-space). When no parts apply, the message is an empty string.

### Part assembly

Parts are appended in this order:

1. **Conflict warning**: appended when the `environment` config sets one or more keys that the charm also manages (for example, `DB_TYPE`). Format: `"ignoring user env overrides: <key1>, <key2>, ... (charm-managed; see juju debug-log)"`.

2. **S3 and storage conflict**: appended when both the `s3` relation is active and a `binary-data` storage volume is attached. The storage mount is unused because S3 takes precedence. Message: `"binary data: s3 (storage mount idle)"`.

3. **Binary data fallback**: appended when neither the `s3` relation is active nor a `binary-data` storage mount is attached; binary workflow data is stored in the PostgreSQL database. Message: `"binary data in DB; attach 'binary-data' storage or relate s3-integrator for production use"`.

### Examples

| Conditions | Resulting status message |
|------------|--------------------------|
| No conflicts, S3 related, no storage | `""` (empty, no parts) |
| No conflicts, no S3, no storage | `"binary data in DB; attach 'binary-data' storage or relate s3-integrator for production use"` |
| No conflicts, S3 related, storage attached | `"binary data: s3 (storage mount idle)"` |
| `DB_TYPE` in `environment` config, no S3, no storage | `"ignoring user env overrides: DB_TYPE (charm-managed; see juju debug-log) \| binary data in DB; attach 'binary-data' storage or relate s3-integrator for production use"` |
