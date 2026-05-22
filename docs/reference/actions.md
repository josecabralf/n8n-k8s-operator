# Actions

This page lists every action exposed by the n8n charm, declared in `charmcraft.yaml:206-227`. Each entry cites `charmcraft.yaml` and `src/charm.py`.

---

## `get-encryption-key`

Retrieves the active n8n encryption key. `charmcraft.yaml:206-210`.

- **Description**: Returns the encryption key currently in use by the charm.
- **Parameters**: none
- **Handler**: `_on_get_encryption_key_action` (`src/charm.py:248-253`)
- **Leader-only**: no; the key is stored in an app-owned Juju secret accessible to any unit
- **Idempotent**: yes; no state is mutated
- **Side effects**: none
- **On success**: `event.set_results({"encryption-key": key})` (`src/charm.py:253`)
- **Failure modes**:
  - `event.fail(msg or "encryption key not yet available")` (`src/charm.py:251`) — triggered when `_effective_encryption_key()` returns `(None, msg)`, for example when the peer relation has not yet joined or the leader has not yet generated a key

---

## `create-admin`

Creates the n8n initial owner account. `charmcraft.yaml:211-227`.

- **Description**: `"Create the n8n initial owner. Idempotent: fails if an owner has already been bootstrapped. Must run on the leader."`
- **Parameters** (all required, type `string`):

  | Parameter | Description |
  |-----------|-------------|
  | `email` | Email address for the new owner account |
  | `first-name` | First name of the new owner |
  | `last-name` | Last name of the new owner |
  | `password` | Plaintext password for the new owner. Appears in `juju show-operation` logs until rotated out of action history. (`charmcraft.yaml:221-224`) |

- **Handler**: `_on_create_admin_action` (`src/charm.py:255-299`)
- **Leader-only**: yes, enforced at `src/charm.py:256`
- **Idempotent**: no; the action fails if an owner already exists
- **Side effects**:
  - Probes `http://localhost:5678/rest/settings` via `_probe_owner_setup()` (`src/charm.py:585-596`) to detect an existing owner.
  - Bcrypt-hashes the supplied password with `bcrypt.gensalt(rounds=10)` (`src/charm.py:276`).
  - Applies a transient Pebble layer `n8n-bootstrap` (`src/charm.py:278-296`) containing: `N8N_INSTANCE_OWNER_MANAGED_BY_ENV="true"`, `N8N_INSTANCE_OWNER_EMAIL`, `N8N_INSTANCE_OWNER_FIRST_NAME`, `N8N_INSTANCE_OWNER_LAST_NAME`, `N8N_INSTANCE_OWNER_PASSWORD_HASH`.
  - Calls `container.replan()` (`src/charm.py:297`).
- **On success**: `event.set_results({"created": True, "email": email})` (`src/charm.py:299`)
- **Failure modes** (all via `event.fail`):
  - `"create-admin must run on the leader unit"` (`ERR_NOT_LEADER`, `src/charm.py:71`) — unit is not the Juju leader
  - `"peer relation not yet joined; retry"` (`ERR_PEER_NOT_READY`, `src/charm.py:72`) — peer relation not yet established
  - `"n8n container not yet connectable"` (`ERR_CONTAINER_NOT_READY`, `src/charm.py:73`) — Pebble socket not available
  - `"owner already exists; use n8n UI to manage users"` (`ERR_ALREADY_BOOTSTRAPPED`, `src/charm.py:70`) — `/rest/settings` reports an owner is already present
