# Statuses

This page lists every unit status message produced by the n8n charm. Each entry cites `src/charm.py` or `src/pebble.py`.

---

## BlockedStatus

The unit requires operator intervention before it can proceed.

### Config and secret errors

- `"<config-name> secret not granted to app"` (`src/charm.py:315`)
  Condition: `_resolve_secret_uri()` found a secret URI in the named config key but the Juju secret has not been granted to the application. Affects `encryption-key` and `smtp-password`.

- `"<config-name> secret missing 'value' field"` (`src/charm.py:318`)
  Condition: `_resolve_secret_uri()` retrieved the secret but the secret revision does not contain a field named `value`. Affects `encryption-key` and `smtp-password`.

- `"stored encryption-key secret is missing"` (`src/charm.py:353`)
  Condition: the leader previously stored a Juju secret ID for the auto-generated encryption key in the peer databag, but the secret no longer exists (for example, it was deleted manually).

- `"stored encryption-key secret missing 'value' field"` (`src/charm.py:356`)
  Condition: the auto-generated encryption key secret exists but the current revision has no `value` field.

- `"invalid log-level '<value>'; must be one of: debug, info, warn, error"` (`src/pebble.py:302`)
  Condition: `log-level` is set to a value not in `VALID_LOG_LEVELS` (`src/pebble.py:19`).

- `"timezone must not be empty"` (`src/pebble.py:307`)
  Condition: `timezone` is set to an empty string.

- `"invalid executions-data-save-on-error '<value>'; must be 'all' or 'none'"` (`src/pebble.py:313`)
  Condition: `executions-data-save-on-error` is set to a value not in `VALID_SAVE_MODES` (`src/pebble.py:20`).

- `"invalid executions-data-save-on-success '<value>'; must be 'all' or 'none'"` (`src/pebble.py:320`)
  Condition: `executions-data-save-on-success` is set to a value not in `VALID_SAVE_MODES` (`src/pebble.py:20`).

- `"executions-data-max-age-hours must be >= 0"` (`src/pebble.py:325`)
  Condition: `executions-data-max-age-hours` is set to a negative integer.

### SMTP errors

- `"smtp-host, smtp-user, and smtp-password must all be set together"` (`src/pebble.py:386`)
  Condition: exactly one or two of `smtp-host`, `smtp-user`, `smtp-password` are non-empty; all three must be set or all three must be empty.

- `"invalid smtp-port '<port>'; must be 1–65535"` (`src/pebble.py:390`)
  Condition: `smtp-port` is outside the range 1 to 65535 inclusive (`src/pebble.py:388-390`).

### Relation errors

- `"waiting for postgresql relation"` (`src/charm.py:246`, `src/charm.py:512`)
  Condition: no `postgresql` relation is joined. Set at `relation_broken` (`src/charm.py:246`) and during reconcile when no relation exists (`src/charm.py:512`).

- `"waiting for ingress relation"` (`src/charm.py:518`)
  Condition: no `traefik-route` relation is joined during reconcile.

### `environment` config parse errors

The full set of parse-time BlockedStatus messages for malformed `environment` config YAML is in `src/pebble.py:143-222`. See [`../how-to/use-environment-escape-hatch.md`](../how-to/use-environment-escape-hatch.md) for the complete list.

### `environment` config Juju secret errors

- `"environment juju entry '<name>': secret not granted"` (`src/charm.py:373`)
  Condition: an `environment.juju` entry references a Juju secret that has not been granted to the application.

- `"environment juju entry '<name>': key '<key>' not in secret"` (`src/charm.py:378`)
  Condition: an `environment.juju` entry references a key that does not exist in the secret revision.

### `environment` config Vault errors

- `"environment vault entry '<name>': vault-k8s relation not joined"` (`src/charm.py:430`)
  Condition: the `environment` config contains a `vault:` entry but the `vault-k8s` relation is not joined.

- `"environment vault entry '<name>': vault credentials not ready"` (`src/charm.py:432-442`)
  Condition: the `vault-k8s` relation is joined but the credentials Juju secret is not yet available.

- `"environment vault entry '<name>': vault login failed (<short-error>)"` (`src/charm.py:440`)
  Condition: AppRole authentication against Vault failed; `<short-error>` is a truncated exception message.

- `"environment vault entry '<name>': path '<path>' not found"` (`src/charm.py:454`)
  Condition: the KV path referenced in the `vault:` entry does not exist in the Vault mount.

- `"environment vault entry '<name>': vault read failed (<short-error>)"` (`src/charm.py:456`)
  Condition: the Vault KV read returned an unexpected error.

- `"environment vault entry '<name>': key '<key>' not in path '<path>'"` (`src/charm.py:459`)
  Condition: the KV path exists but the specified key is absent from the secret data.

---

## WaitingStatus

The unit is healthy but waiting for an external dependency.

- `"waiting for encryption key"` (`src/charm.py:469`)
  Condition: `_effective_encryption_key()` returned `(None, None)`. This occurs on follower units before the leader has written the encryption key secret ID to the peer databag, or while the peer relation itself is still joining.

- `"waiting for database credentials"` (`src/charm.py:514`)
  Condition: the `postgresql` relation is joined but `_db_env()` returned `None`, meaning the relation data has not yet been populated with connection credentials.

---

## MaintenanceStatus

The unit is performing an operation and is temporarily unavailable.

- `"waiting for pebble"` (`src/charm.py:528`)
  Condition: `container.can_connect()` returned `False`; the Pebble socket is not yet ready.

- `"starting n8n"` (`src/charm.py:531`)
  Condition: the Pebble layer has been applied and `container.replan()` called, but the readiness probe has not yet been checked.

- `"waiting for n8n to start"` (`STATUS_WAITING_N8N`, `src/charm.py:66`, `src/charm.py:567`)
  Condition: Pebble is connected and the layer is active, but the n8n readiness check (`_probe_owner_setup()` or equivalent HTTP probe at `http://localhost:5678`) has not returned a successful response yet.

---

## ActiveStatus

The unit is running normally. The status message is assembled from a list of optional parts joined by `" | "` (space-pipe-space) at `src/charm.py:574-583`. When no parts apply, the message is an empty string.

### Part assembly

Parts are appended to `status_parts: list[str]` in this order (`src/charm.py:574-582`):

1. **Conflict warning** (`src/charm.py:575-578`): appended when `conflict_keys` is non-empty.
   Format: `"ignoring user env overrides: <key1>, <key2>, ... (charm-managed; see juju debug-log)"`
   Condition: the `environment` config sets one or more keys that the charm also manages (for example, `DB_TYPE`). The keys are listed in `conflict_keys`.

2. **S3 and storage conflict** (`src/charm.py:579-580`): appended when both `s3_creds` is present and a `binary-data` storage mount is attached.
   Message: `"binary data: s3 (storage mount idle)"`
   Condition: S3 is configured via the `s3` relation and a `binary-data` Juju storage volume is also attached; the storage mount is unused because S3 takes precedence.

3. **Binary data fallback** (`src/charm.py:581-582`): appended when neither `s3_creds` nor `binary_data_attached` is true.
   Message: `"binary data in DB; attach 'binary-data' storage or relate s3-integrator for production use"` (`STATUS_BINARY_DATA_FALLBACK`, `src/charm.py:67-69`)
   Condition: no S3 relation and no `binary-data` storage mount; binary workflow data is stored in the PostgreSQL database.

### Examples

| Conditions | Resulting status message |
|------------|--------------------------|
| No conflicts, S3 related, no storage | `""` (empty, no parts) |
| No conflicts, no S3, no storage | `"binary data in DB; attach 'binary-data' storage or relate s3-integrator for production use"` |
| No conflicts, S3 related, storage attached | `"binary data: s3 (storage mount idle)"` |
| `DB_TYPE` in `environment` config, no S3, no storage | `"ignoring user env overrides: DB_TYPE (charm-managed; see juju debug-log) \| binary data in DB; attach 'binary-data' storage or relate s3-integrator for production use"` |
