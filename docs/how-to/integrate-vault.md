# Integrate Vault for secret resolution

Vault integration lets `vault:` entries in the `environment` config resolve to live secret values at runtime. Without the `vault-k8s` relation, any `vault:` entry in `environment` causes the unit to enter `BlockedStatus`.

## Prerequisites

- A `vault-k8s` application deployed in the same Juju model and unsealed.
- One or more secrets written to Vault under a KV v2 mount. Refer to the [vault-k8s charm documentation](https://charmhub.io/vault-k8s) for how to initialise, unseal, and write secrets.

## Relate n8n to vault-k8s

```bash
juju integrate n8n vault-k8s
```

The relation uses the `vault-kv` interface, declared as the `vault-k8s` endpoint in `charmcraft.yaml`. The relation is optional: if no `vault:` entries exist in the `environment` config, the unit operates normally without it.

## Mount layout

The charm constructs its KV mount path as `charm-<app-name>-<mount-suffix>`. The suffix is fixed to `"n8n"`, so for an application named `n8n` the mount path is `charm-n8n-n8n`. For an application deployed under a different name, substitute that name in place of `n8n` in the middle segment.

## AppRole and CIDR binding

When the relation is joined, the charm requests AppRole credentials bound to the unit's pod CIDR. It publishes the model egress subnets and the pod-interface subnet to vault-k8s; including the pod-interface subnet ensures that the AppRole CIDR allow-list covers the actual pod source address, not only the ClusterIP. Vault binds the issued AppRole credentials to that combined CIDR list. Once credentials are issued, the charm writes the CA certificate if provided and opens an authenticated session before reading any secrets.

## Reference a Vault secret from `environment`

Set the `environment` config key with one or more `vault:` entries. Each entry names the secret (`name`), the KV path within the mount (`path`), and the field to extract (`key`):

```yaml
environment: |
  N8N_ENCRYPTION_KEY:
    vault:
      name: encryption-key
      path: n8n/credentials
      key: encryption_key
```

`name` becomes the environment variable injected into the n8n container. `path` is relative to the mount root. `key` is the field name inside the KV v2 secret data.

For the full `environment` config syntax, see [Use the environment escape hatch](use-environment-escape-hatch.md).

## BlockedStatus messages

If secret resolution fails, the unit enters `BlockedStatus` with one of the following messages. The `<name>` placeholder is the value of the `name` field in the offending `vault:` entry.

- `"environment vault entry '<name>': vault-k8s relation not joined"` — the `vault-k8s` relation is absent or the remote application databag is empty.
- `"environment vault entry '<name>': vault credentials not ready"` — the relation is joined but the AppRole credentials have not been issued yet, or the vault URL or mount point is not yet published.
- `"environment vault entry '<name>': vault login failed (<short-error>)"` — the charm holds credentials but the AppRole login call to Vault was rejected.
- `"environment vault entry '<name>': path '<path>' not found"` — the KV path does not exist under the mount.
- `"environment vault entry '<name>': key '<key>' not in path '<path>'"` — the path exists but does not contain the requested field.

Correct the underlying condition and the unit will re-reconcile on the next hook.

## Detaching

```bash
juju remove-relation n8n vault-k8s
```

If `vault:` entries remain in the `environment` config after the relation is removed, the unit re-enters `BlockedStatus` with `"environment vault entry '<name>': vault-k8s relation not joined"`. Remove or replace the `vault:` entries before detaching, or remove them after and re-configure to clear the blocked state.
