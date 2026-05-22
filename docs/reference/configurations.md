# Configuration options

This page lists every configuration key exposed by the n8n charm, declared in `charmcraft.yaml:74-203`. Each entry cites `charmcraft.yaml` or `src/charm.py` / `src/pebble.py`.

---

## `encryption-key`

The Juju secret URI holding the AES encryption key n8n uses to encrypt stored credentials. `charmcraft.yaml:76-86`.

- **Type**: `secret`
- **Default**: `""` (charm auto-generates a key on first start and stores it in a peer-relation secret)
- **Env var**: `N8N_ENCRYPTION_KEY` — resolved via `_effective_encryption_key()` (`src/charm.py:321-357`)
- **Validation**: `_resolve_secret_uri(ENCRYPTION_KEY_CONFIG)` (`src/charm.py:301-319`)
- **BlockedStatus on invalid**:
  - `"<config-name> secret not granted to app"` (`src/charm.py:315`)
  - `"<config-name> secret missing 'value' field"` (`src/charm.py:318`)
- **Note**: Secret rotation is not supported in v1 (`charmcraft.yaml:84-86`).

---

## `log-level`

The verbosity level for the n8n application log. `charmcraft.yaml:87-92`.

- **Type**: `string`
- **Default**: `info`
- **Env var**: `N8N_LOG_LEVEL` (`src/pebble.py:332`)
- **Validation**: must be one of `debug`, `info`, `warn`, `error` (`VALID_LOG_LEVELS`, `src/pebble.py:19`, check at `src/pebble.py:298-303`)
- **BlockedStatus on invalid**: `"invalid log-level '<value>'; must be one of: debug, info, warn, error"` (`src/pebble.py:302`)

---

## `timezone`

The IANA timezone name passed to n8n for scheduling and display. `charmcraft.yaml:93-98`.

- **Type**: `string`
- **Default**: `UTC`
- **Env vars**: `GENERIC_TIMEZONE` and `TZ` (`src/pebble.py:333-334`)
- **Validation**: must be non-empty (`src/pebble.py:305-307`)
- **BlockedStatus on invalid**: `"timezone must not be empty"` (`src/pebble.py:307`)

---

## `executions-data-prune`

Enables automatic deletion of old execution records. `charmcraft.yaml:99-104`.

- **Type**: `boolean`
- **Default**: `false`
- **Env var**: `EXECUTIONS_DATA_PRUNE` (`src/pebble.py:335`), coerced to `"true"` or `"false"`
- **Validation**: none beyond type coercion
- **BlockedStatus on invalid**: none

---

## `executions-data-max-age-hours`

Maximum age in hours before execution records are pruned. Effective only when `executions-data-prune` is `true`. `charmcraft.yaml:105-110`.

- **Type**: `int`
- **Default**: `336`
- **Env var**: `EXECUTIONS_DATA_MAX_AGE` (`src/pebble.py:336`)
- **Validation**: must be `>= 0` (`src/pebble.py:323-325`)
- **BlockedStatus on invalid**: `"executions-data-max-age-hours must be >= 0"` (`src/pebble.py:325`)

---

## `executions-data-save-on-error`

Controls which failed executions are persisted to the database. `charmcraft.yaml:112-117`.

- **Type**: `string`
- **Default**: `all`
- **Env var**: `EXECUTIONS_DATA_SAVE_ON_ERROR` (`src/pebble.py:337`)
- **Validation**: must be `"all"` or `"none"` (`VALID_SAVE_MODES`, `src/pebble.py:20`)
- **BlockedStatus on invalid**: `"invalid executions-data-save-on-error '<value>'; must be 'all' or 'none'"` (`src/pebble.py:313`)

---

## `executions-data-save-on-success`

Controls which successful executions are persisted to the database. `charmcraft.yaml:118-123`.

- **Type**: `string`
- **Default**: `all`
- **Env var**: `EXECUTIONS_DATA_SAVE_ON_SUCCESS` (`src/pebble.py:338`)
- **Validation**: must be `"all"` or `"none"` (`VALID_SAVE_MODES`, `src/pebble.py:20`)
- **BlockedStatus on invalid**: `"invalid executions-data-save-on-success '<value>'; must be 'all' or 'none'"` (`src/pebble.py:320`)

---

## `executions-data-save-on-progress`

Controls whether in-progress execution data is written to the database. `charmcraft.yaml:124-129`.

- **Type**: `boolean`
- **Default**: `false`
- **Env var**: `EXECUTIONS_DATA_SAVE_ON_PROGRESS` (`src/pebble.py:339`), coerced to `"true"` or `"false"`
- **Validation**: none beyond type coercion
- **BlockedStatus on invalid**: none

---

## `disable-user-registration`

Prevents new users from self-registering via the n8n UI. `charmcraft.yaml:130-135`.

- **Type**: `boolean`
- **Default**: `false`
- **Env var**: `N8N_USER_MANAGEMENT_DISABLED` (`src/pebble.py:340`), coerced to `"true"` or `"false"`
- **Validation**: none beyond type coercion
- **BlockedStatus on invalid**: none

---

## SMTP options

The six SMTP keys configure outbound email for workflow notifications and user invitations. All are declared at `charmcraft.yaml:166-203`. `smtp-host`, `smtp-user`, and `smtp-password` must be set together or all left empty; setting any subset blocks the unit.

### `smtp-host`

- **Type**: `string`
- **Default**: `""`
- **Env var**: `N8N_SMTP_HOST` (`src/pebble.py`)
- **Validation**: must be set together with `smtp-user` and `smtp-password` (`src/pebble.py:386`)
- **BlockedStatus on invalid**: `"smtp-host, smtp-user, and smtp-password must all be set together"` (`src/pebble.py:386`)

### `smtp-port`

- **Type**: `int`
- **Default**: `587`
- **Env var**: `N8N_SMTP_PORT` (`src/pebble.py`)
- **Validation**: `1 <= port <= 65535` (`src/pebble.py:388-390`)
- **BlockedStatus on invalid**: `"invalid smtp-port '<value>'; must be 1–65535"` (`src/pebble.py:390`)

### `smtp-user`

- **Type**: `string`
- **Default**: `""`
- **Env var**: `N8N_SMTP_USER` (`src/pebble.py`)
- **Validation**: same trio rule as `smtp-host` (`src/pebble.py:386`)
- **BlockedStatus on invalid**: `"smtp-host, smtp-user, and smtp-password must all be set together"` (`src/pebble.py:386`)

### `smtp-password`

- **Type**: `secret`
- **Default**: `""`
- **Env var**: `N8N_SMTP_PASSWORD`, resolved via `_resolve_secret_uri("smtp-password")` (`src/charm.py:301-319`)
- **Validation**: same secret-resolution checks as `encryption-key`
- **BlockedStatus on invalid**:
  - `"<config-name> secret not granted to app"` (`src/charm.py:315`)
  - `"<config-name> secret missing 'value' field"` (`src/charm.py:318`)

### `smtp-sender`

- **Type**: `string`
- **Default**: `""`
- **Env var**: `N8N_SMTP_SENDER` (`src/pebble.py:399-401`)
- **Validation**: none; omitted from the Pebble layer when empty
- **BlockedStatus on invalid**: none

### `smtp-ssl-tls`

- **Type**: `boolean`
- **Default**: `false`
- **Env var**: `N8N_SMTP_SSL` (`src/pebble.py:397-398`), coerced to `"true"` or `"false"`
- **Validation**: none beyond type coercion
- **BlockedStatus on invalid**: none

---

## `environment`

An escape-hatch for injecting arbitrary environment variables into the n8n container. `charmcraft.yaml:136-165`. The value is a YAML string with up to three sub-keys: `env` (static key/value pairs), `juju` (values sourced from Juju secrets), and `vault` (values sourced from Vault KV). The `vault` sub-key requires the `vault-k8s` relation.

- **Type**: `string`
- **Default**: `""`
- **Env vars**: all keys listed under `env`, `juju`, and `vault` are injected directly into the Pebble layer
- **Validation**: parse-time and runtime checks in `src/pebble.py:143-222` and `src/charm.py`
- **BlockedStatus on invalid**: see [`../how-to/use-environment-escape-hatch.md`](../how-to/use-environment-escape-hatch.md) for the full list of parse errors and runtime failure messages
