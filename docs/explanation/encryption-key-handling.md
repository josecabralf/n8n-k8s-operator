# Encryption-key handling

n8n stores every credential it manages (API tokens, OAuth secrets, database
passwords used inside workflows) encrypted with a single symmetric key passed
via the environment variable `N8N_ENCRYPTION_KEY`. The key is required at
startup and is applied uniformly to every credential row in the database. Losing
this key makes every credential row unreadable. The workflows themselves and
execution history are not encrypted with this key; only the stored-credential
rows are affected.

The charm owns the lifecycle of this key: generating it on first boot,
persisting it across pod restarts and unit churn, and surfacing it to operators
on demand.

## Two sources for the key

The charm checks the `encryption-key` config first and falls back to auto-generation when that config is unset.

**Override.** If the `encryption-key` config key (declared in `charmcraft.yaml`) is set to a Juju user-secret URI of the form `secret:<id>`, the charm reads the key from that secret instead of generating one. The referenced secret must contain a field named `value` and must be granted to the application before the config is applied. This path exists for migrations from an existing n8n install where the encryption key is already known; supplying the old key ensures the existing credential rows remain readable after the charm takes over.

**Auto-generate.** When no override is configured, the charm generates the key itself. Only the leader unit runs the generator, producing a 48-character hex string. The value is stored in a Juju app-owned secret labelled `n8n-encryption-key`. The Juju secret ID is then written to the peer-relation app databag. Non-leader units wait until the peer databag carries this ID before they can read the key.

On every subsequent event the charm reads the secret ID from the peer databag and fetches the corresponding Juju secret. If the secret is missing or its `value` field is empty, the unit transitions to `BlockedStatus`.

## Persistence model

The key value lives in a Juju app-owned secret managed by the Juju controller.
The peer databag carries only the secret ID, not the value. App-owned secrets
survive pod restarts, container image upgrades, and the addition or removal of
units. Because the secret is app-scoped, all units in the application can read
it without each unit needing its own copy.

This model does not survive Juju controller loss. If the controller is
destroyed without a backup, the app-owned secret is gone and the key cannot
be recovered from the peer databag or from n8n's database. Back up the key
separately using the `get-encryption-key` action described below.

## Reading the key

The `get-encryption-key` action (declared in `charmcraft.yaml`) returns the current key in the `encryption-key` field of the action output. The action does not require the unit to be the leader because the Juju secret is app-owned and readable by any unit.

Run this action after the first deployment and store the result offsite. The
action description in `charmcraft.yaml` states: "Store this offsite for
disaster recovery — losing this key bricks every credential stored in n8n's
database."

For guidance on incorporating the key retrieval into a backup procedure, see
`../how-to/backup-and-restore.md`.

## Why no rotation in v1

The `encryption-key` config description in `charmcraft.yaml` states:
"Rotation is NOT supported in v1 — changing this after deploy bricks every
credential stored by n8n."

The reason is structural. n8n does not provide an in-place re-encryption tool.
Every credential row in the database is encrypted with the key that was active
when the credential was saved. Changing `N8N_ENCRYPTION_KEY` at runtime does
not decrypt the existing rows and re-encrypt them with the new key; it simply
makes the existing rows unreadable. A charm implementation of rotation would
need to decrypt every credential row under the old key, re-encrypt each row
under the new key, commit atomically, and then restart n8n with the new key.
n8n exposes no API for this operation. Rather than ship a partially working
rotation path, the charm documents the constraint explicitly and defers
rotation to a future version when a safe migration path exists.

## Loss recovery

There is no in-product recovery path from key loss. If the key is lost and
no offsite backup exists, any credential stored in n8n is permanently
unreadable. The recovery procedure is to deploy a fresh install with a new
key and re-enter every credential manually. Workflows are not encrypted with
this key and survive intact; only the credential rows are unreadable.
Execution history is also unaffected.

The only mitigation is to retrieve and store the key before it is needed.
