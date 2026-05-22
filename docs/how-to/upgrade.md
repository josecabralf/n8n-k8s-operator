# Upgrade n8n

This page covers upgrading the n8n charm with `juju refresh`. Changing the n8n
workload version (the container image) is a separate operation: attach a
different `n8n-image` resource. See `build-derived-image.md` for that
procedure.

## Pre-refresh checklist

Complete all three steps before running `juju refresh`. Skipping any of them
leaves you without a recovery path if the refresh introduces a regression.

### Capture the encryption key

Run the `get-encryption-key` action and store the output offsite before
refreshing.

```bash
juju run n8n/0 get-encryption-key
```

The action returns an `encryption-key` field containing a 48-character hex
string. That value is the `N8N_ENCRYPTION_KEY` passed to the n8n process. If
it is lost and the unit is later redeployed from scratch, every credential
stored in the database becomes unreadable. Store it in an offline vault or
equivalent secure location. See `backup-and-restore.md` for the full backup
procedure and for how to supply this key on restore.

### Back up the database

This charm does not implement database backup. PostgreSQL is managed by the
`postgresql-k8s` charm; use its backup mechanism to capture the n8n database
before refreshing. See the postgresql-k8s documentation for the backup action
and any prerequisites.

The database is external to the charm and unaffected by `juju refresh`, but a
backup gives you a restore point if the new charm revision runs a migration that
cannot be rolled back.

### Back up binary data

If you are using filesystem storage, snapshot the `binary-data` PVC before
refreshing. The PVC is mounted at `/home/node/.n8n/binaryData`
(`charmcraft.yaml`). Use a Kubernetes-level volume snapshot.

If you are using S3, the bucket is the source of truth. Verify all objects are
present before proceeding. The bucket name defaults to the application name and
is set on the `s3` relation by `s3-integrator`.

## Refresh the charm

```bash
juju refresh n8n --channel=edge
```

To pin to a specific revision:

```bash
juju refresh n8n --revision=<n>
```

## What survives

| State | Persistence layer |
|---|---|
| Encryption key | Juju app secret; persists across pod restarts and charm upgrades |
| Workflows and credentials | PostgreSQL database, managed by `postgresql-k8s` |
| Binary data (filesystem) | PVC; persists across pod restarts and charm upgrades |
| Binary data (S3) | S3 bucket; re-read from the s3-integrator relation on each reconcile |
| Configuration | Juju controller (charm config keys in `charmcraft.yaml`) |

## Readiness gating during refresh

Pebble performs a `ready` check: HTTP GET to `/healthz/readiness`, period 10 s,
threshold 3. Three consecutive passing responses are required before Pebble
marks the check as `UP`. During replan the unit transitions through
`"starting n8n"` and then to `"waiting for n8n to start"` while the reconcile
loop waits for the check to pass. Traffic remains blocked until the check
reaches `UP`; the unit then moves to `ActiveStatus`.

## Rolling back

If the refreshed revision introduces a regression, roll back by refreshing to
the previous revision:

```bash
juju refresh n8n --revision=<previous>
```

Encryption-key rotation is not supported after initial deployment. See
`../explanation/encryption-key-handling.md` for the key lifecycle and the
constraints that apply.
