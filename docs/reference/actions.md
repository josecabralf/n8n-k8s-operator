# Actions

All actions are declared in `charmcraft.yaml`.

---

## `get-encryption-key`

Retrieves the active n8n encryption key. Declared in `charmcraft.yaml`.

- **Description**: Returns the encryption key currently in use by the charm.
- **Parameters**: none
- **Leader-only**: no; the key is stored in an app-owned Juju secret accessible to any unit
- **Idempotent**: yes; no state is mutated
- **Side effects**: none
- **On success**: returns `{"encryption-key": <key>}`
- **Failure modes**:
  - `"encryption key not yet available"` — the peer relation has not yet joined or the leader has not yet generated a key

---

## `create-admin`

Creates the n8n initial owner account. Declared in `charmcraft.yaml`.

- **Description**: Create the n8n initial owner. Fails if an owner has already been bootstrapped. Must run on the leader.
- **Parameters** (all required, type `string`):

  | Parameter | Description |
  |-----------|-------------|
  | `email` | Email address for the new owner account |
  | `first-name` | First name of the new owner |
  | `last-name` | Last name of the new owner |
  | `password` | Plaintext password for the new owner. Appears in `juju show-operation` logs until rotated out of action history. |

- **Leader-only**: yes
- **Idempotent**: no; the action fails if an owner already exists
- **Side effects**:
  - Probes `http://localhost:5678/rest/settings` to detect an existing owner.
  - Bcrypt-hashes the supplied password.
  - Applies a transient bootstrap environment to the container with the owner credentials, then replans the service.
- **On success**: returns `{"created": true, "email": <email>}`
- **Failure modes**:
  - `"create-admin must run on the leader unit"` — unit is not the Juju leader
  - `"peer relation not yet joined; retry"` — peer relation not yet established
  - `"n8n container not yet connectable"` — Pebble socket not available
  - `"owner already exists; use n8n UI to manage users"` — an owner is already present

---

## `restart`

Stops and restarts the n8n workload service. Declared in `charmcraft.yaml`.

- **Description**: Cycles the `n8n` service in the Pebble plan. The unit is not reconfigured; config is not re-read and relations are not re-resolved beyond the reconcile that runs afterward to restore status.
- **Parameters**: none
- **Leader-only**: no; runs per unit
- **Idempotent**: yes; the running process is cycled, no state is mutated
- **Side effects**:
  - Stops and restarts the `n8n` Pebble service. Any in-flight workflow executions are interrupted.
  - Sets `MaintenanceStatus("restarting n8n")` while the service cycles, then re-runs the reconcile path to restore status (typically `ActiveStatus`).
- **Failure modes**:
  - `"n8n container not yet connectable"` — Pebble socket not available
  - `"n8n service not configured yet; nothing to restart"` — the `n8n` service is not yet in the Pebble plan (for example, required relations are not satisfied)
