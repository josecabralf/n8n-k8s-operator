# Configuration options

All keys are declared in `charmcraft.yaml`.

---

## `encryption-key`

The Juju secret URI holding the AES encryption key n8n uses to encrypt stored credentials. Declared in `charmcraft.yaml`.

- **Type**: `secret`
- **Default**: `""` (charm auto-generates a key on first start and stores it in a peer-relation secret)
- **Env var**: `N8N_ENCRYPTION_KEY`
- **Validation**: The referenced Juju secret must be granted to the application and must contain a field named `value`.
- **BlockedStatus on invalid**:
  - `"<config-name> secret not granted to app"`
  - `"<config-name> secret missing 'value' field"`
- **Note**: Secret rotation is not supported in v1.

---

## `log-level`

The verbosity level for the n8n application log. Declared in `charmcraft.yaml`.

- **Type**: `string`
- **Default**: `info`
- **Env var**: `N8N_LOG_LEVEL`
- **Validation**: must be one of `debug`, `info`, `warn`, `error`
- **BlockedStatus on invalid**: `"invalid log-level '<value>'; must be one of: debug, info, warn, error"`

---

## `timezone`

The IANA timezone name passed to n8n for scheduling and display. Declared in `charmcraft.yaml`.

- **Type**: `string`
- **Default**: `UTC`
- **Env vars**: `GENERIC_TIMEZONE` and `TZ`
- **Validation**: must be non-empty
- **BlockedStatus on invalid**: `"timezone must not be empty"`

---

## `executions-data-prune`

Enables automatic deletion of old execution records. Declared in `charmcraft.yaml`.

- **Type**: `boolean`
- **Default**: `false`
- **Env var**: `EXECUTIONS_DATA_PRUNE` (coerced to `"true"` or `"false"`)
- **Validation**: none beyond type coercion
- **BlockedStatus on invalid**: none

---

## `executions-data-max-age-hours`

Maximum age in hours before execution records are pruned. Effective only when `executions-data-prune` is `true`. Declared in `charmcraft.yaml`.

- **Type**: `int`
- **Default**: `336`
- **Env var**: `EXECUTIONS_DATA_MAX_AGE`
- **Validation**: must be `>= 0`
- **BlockedStatus on invalid**: `"executions-data-max-age-hours must be >= 0"`

---

## `executions-data-save-on-error`

Controls which failed executions are persisted to the database. Declared in `charmcraft.yaml`.

- **Type**: `string`
- **Default**: `all`
- **Env var**: `EXECUTIONS_DATA_SAVE_ON_ERROR`
- **Validation**: must be `"all"` or `"none"`
- **BlockedStatus on invalid**: `"invalid executions-data-save-on-error '<value>'; must be 'all' or 'none'"`

---

## `executions-data-save-on-success`

Controls which successful executions are persisted to the database. Declared in `charmcraft.yaml`.

- **Type**: `string`
- **Default**: `all`
- **Env var**: `EXECUTIONS_DATA_SAVE_ON_SUCCESS`
- **Validation**: must be `"all"` or `"none"`
- **BlockedStatus on invalid**: `"invalid executions-data-save-on-success '<value>'; must be 'all' or 'none'"`

---

## `executions-data-save-on-progress`

Controls whether in-progress execution data is written to the database. Declared in `charmcraft.yaml`.

- **Type**: `boolean`
- **Default**: `false`
- **Env var**: `EXECUTIONS_DATA_SAVE_ON_PROGRESS` (coerced to `"true"` or `"false"`)
- **Validation**: none beyond type coercion
- **BlockedStatus on invalid**: none

---

## `disable-user-registration`

Prevents new users from self-registering via the n8n UI. Declared in `charmcraft.yaml`.

- **Type**: `boolean`
- **Default**: `false`
- **Env var**: `N8N_USER_MANAGEMENT_DISABLED` (coerced to `"true"` or `"false"`)
- **Validation**: none beyond type coercion
- **BlockedStatus on invalid**: none

---

## SMTP options

The six SMTP keys configure outbound email for workflow notifications and user invitations. All are declared in `charmcraft.yaml`. `smtp-host`, `smtp-user`, and `smtp-password` must be set together or all left empty; setting any subset blocks the unit.

### `smtp-host`

- **Type**: `string`
- **Default**: `""`
- **Env var**: `N8N_SMTP_HOST`
- **Validation**: must be set together with `smtp-user` and `smtp-password`
- **BlockedStatus on invalid**: `"smtp-host, smtp-user, and smtp-password must all be set together"`

### `smtp-port`

- **Type**: `int`
- **Default**: `587`
- **Env var**: `N8N_SMTP_PORT`
- **Validation**: `1 <= port <= 65535`
- **BlockedStatus on invalid**: `"invalid smtp-port '<value>'; must be 1–65535"`

### `smtp-user`

- **Type**: `string`
- **Default**: `""`
- **Env var**: `N8N_SMTP_USER`
- **Validation**: same trio rule as `smtp-host`
- **BlockedStatus on invalid**: `"smtp-host, smtp-user, and smtp-password must all be set together"`

### `smtp-password`

- **Type**: `secret`
- **Default**: `""`
- **Env var**: `N8N_SMTP_PASSWORD`
- **Validation**: same secret-resolution checks as `encryption-key` — the referenced Juju secret must be granted to the application and must contain a field named `value`
- **BlockedStatus on invalid**:
  - `"<config-name> secret not granted to app"`
  - `"<config-name> secret missing 'value' field"`

### `smtp-sender`

- **Type**: `string`
- **Default**: `""`
- **Env var**: `N8N_SMTP_SENDER`
- **Validation**: none; omitted from the container environment when empty
- **BlockedStatus on invalid**: none

### `smtp-ssl-tls`

- **Type**: `boolean`
- **Default**: `false`
- **Env var**: `N8N_SMTP_SSL` (coerced to `"true"` or `"false"`)
- **Validation**: none beyond type coercion
- **BlockedStatus on invalid**: none

---

## `environment`

An escape-hatch for injecting arbitrary environment variables into the n8n container. Declared in `charmcraft.yaml`. The value is a YAML string with up to three sub-keys: `env` (static key/value pairs), `juju` (values sourced from Juju secrets), and `vault` (values sourced from Vault KV). The `vault` sub-key requires the `vault-k8s` relation.

- **Type**: `string`
- **Default**: `""`
- **Env vars**: all keys listed under `env`, `juju`, and `vault` are injected directly into the container environment
- **Validation**: parse-time and runtime checks on the YAML structure and secret references
- **BlockedStatus on invalid**: see [`../how-to/use-environment-escape-hatch.md`](../how-to/use-environment-escape-hatch.md) for the full list of parse errors and runtime failure messages
