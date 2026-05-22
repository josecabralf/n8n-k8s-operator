# Set extra env vars with the `environment` config

The `environment` config key is the Tier 3 escape hatch for passing arbitrary
env vars to n8n without rebuilding the charm. Reach for it only when neither
Tier 1 typed configs (log level, timezone, execution settings) nor Tier 2 SMTP
configs cover your case. Both of those are declared in `charmcraft.yaml` and
provide validation; the `environment` key does not.

## YAML schema

`environment` accepts a YAML string with up to three sub-keys:

```yaml
env:
  - name: N8N_FOO
    value: bar
juju:
  - secret-id: secret:abc
    name: N8N_BAZ
    key: token
vault:
  - path: myapp
    name: N8N_API_TOKEN
    key: api_token
```

All three sub-keys are optional. `env:` holds static plaintext values. `juju:`
pulls values from Juju secrets. `vault:` pulls values from a Vault KV v2 path
via the `vault-k8s` relation. Each entry's `name` field must match
`[A-Z_][A-Z0-9_]*`; the unit blocks on parse failure if the pattern is
violated.

## Static values: `env:` section

Use `env:` for env vars that carry no secret material and are not managed by
the charm:

```yaml
env:
  - name: N8N_PERSONALIZATION_ENABLED
    value: "false"
  - name: N8N_VERSION_NOTIFICATIONS_ENABLED
    value: "false"
```

Save that block to a file and apply it:

```bash
juju config n8n environment=@./environment.yaml
```

The `--file` flag is equivalent. Each `name` is validated against
`[A-Z_][A-Z0-9_]*` (`src/pebble.py:114-120`). Duplicate names within `env:`
are rejected at parse time.

## Juju secrets: `juju:` section

Use `juju:` to pull a value from a Juju user secret. All three fields
(`secret-id`, `name`, `key`) are required and must be non-empty strings.

```yaml
juju:
  - secret-id: secret:cvh1d04mp25c77gqd8h0
    name: N8N_EXTERNAL_API_KEY
    key: api-key
```

Create and grant the secret before applying the config:

```bash
juju add-secret n8n-external-api-key api-key=your-value
juju grant-secret n8n-external-api-key n8n
```

If the secret is not granted, the unit blocks with:

```
"environment juju entry '<name>': secret not granted"
```

If the secret is granted but the key is absent from its content, the unit
blocks with:

```
"environment juju entry '<name>': key '<key>' not in secret"
```

Both status strings are emitted from `src/charm.py:373,378`.

## Vault: `vault:` section

Use `vault:` to pull a value from a Vault KV v2 path. All three fields
(`path`, `name`, `key`) are required.

```yaml
vault:
  - path: n8n/credentials
    name: N8N_EXTERNAL_API_KEY
    key: api_token
```

The `vault-k8s` relation must be joined and credentials must be ready before
the charm can resolve `vault:` entries. See
[integrate-vault.md](integrate-vault.md) for the full wiring procedure.

If the relation is absent, the unit blocks with:

```
"environment vault entry '<name>': vault-k8s relation not joined"
```

(`src/charm.py:430`)

## Precedence

Two layers of precedence apply.

**Charm-managed envs override user-supplied.** `build_layer()` in
`src/pebble.py:487-489` applies user entries first, then overlays all
charm-managed envs:

```python
environment = dict(user_env) if user_env else {}
environment.update(charm_managed)
conflicts = sorted(set(user_env or {}).intersection(charm_managed))
```

Any key present in both is silently won by the charm. The unit status appends:

```
"ignoring user env overrides: <keys> (charm-managed; see juju debug-log)"
```

`juju debug-log` records one line per dropped key:

```
environment: dropping <KEY> (<origin>)
```

(`src/charm.py:558-583`)

**Within user-supplied entries, vault overrides juju, which overrides env.**
The merge loop in `src/pebble.py:231-269` applies `env:` entries first, then
`juju:`, then `vault:`. A later source silently overrides an earlier one for
the same name. This lets you migrate a plaintext `env:` entry to a `juju:` or
`vault:` entry without removing the old one in the same operation.

## Charm-managed envs (cannot override)

The full registry is `CHARM_MANAGED_ENV_ORIGIN` in `src/pebble.py:29-72`.
Categories, with one example each:

- **Ingress** (`N8N_HOST`, derived from the `traefik-route` relation)
- **PostgreSQL** (`DB_POSTGRESDB_HOST`, derived from the `postgresql` relation)
- **Encryption key** (`N8N_ENCRYPTION_KEY`, managed by the charm or the
  `encryption-key` config)
- **Metrics** (`N8N_METRICS`, set when the `metrics-endpoint` relation is joined)
- **Binary data / S3** (`N8N_EXTERNAL_STORAGE_S3_HOST`, derived from the `s3`
  relation)
- **Tier 1 typed configs** (`N8N_LOG_LEVEL`, use `juju config n8n log-level=`
  instead)
- **Tier 2 SMTP configs** (`N8N_SMTP_HOST`, use `juju config n8n smtp-host=`
  instead)

## Atomic failure

If any single `juju:` or `vault:` entry fails to resolve, `user_env` is set to
`None` and all user-supplied entries are dropped from the Pebble layer for that
reconcile cycle (`src/charm.py:498-507`). The charm does not apply a partial
set. Charm-managed envs are unaffected and still applied. The unit blocks with
the first error message that caused the failure.
