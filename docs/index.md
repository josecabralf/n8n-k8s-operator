# n8n charm documentation

This is the documentation set for the n8n Kubernetes charm. The pages are organised by [Diátaxis](https://diataxis.fr/) quadrant: a tutorial for first-time users, how-to guides for specific tasks, reference material for every config surface, and explanation pages for the design decisions behind v1.

## In this documentation

| Quadrant | When to read |
| --- | --- |
| [Tutorial](tutorial/getting-started.md) | First time deploying the charm. Walks from a fresh microk8s to a working n8n you can log into. |
| [How-to guides](how-to/) | You have n8n running and need to add a capability: COS, S3, SMTP, Vault, upgrade, backup. |
| [Reference](reference/) | Look up a config key, action, relation, or status string. Every surface, with file:line citations. |
| [Explanation](explanation/) | Background on architecture, encryption-key handling, and v1 limitations. |

## Tutorial

- [Get started with n8n](tutorial/getting-started.md) — deploy the charm on microk8s, reach `ActiveStatus`, bootstrap the owner, and capture the encryption key.

## How-to

- [Add COS Lite observability](how-to/deploy-with-cos.md) — integrate metrics, logs, and the Grafana dashboard.
- [Configure S3 binary-data storage](how-to/configure-s3-binary-data.md) — back file attachments with S3 instead of the database.
- [Configure SMTP for outbound mail](how-to/configure-smtp.md) — set up the SMTP trio and the Juju user-secret password.
- [Set extra env vars with `environment`](how-to/use-environment-escape-hatch.md) — the Tier 3 escape hatch for vars without a typed config.
- [Integrate Vault for secret resolution](how-to/integrate-vault.md) — resolve `vault:` entries from a running vault-k8s.
- [Upgrade n8n](how-to/upgrade.md) — `juju refresh` workflow and pre-refresh checklist.
- [Back up and restore n8n](how-to/backup-and-restore.md) — capture the encryption key, the database, and the binary-data store.
- [Build a derived n8n image](how-to/build-derived-image.md) — install community nodes by attaching a custom OCI image.

## Reference

- [Configuration options](reference/configurations.md) — every config key with type, default, env-var mapping, and validation.
- [Actions](reference/actions.md) — `get-encryption-key` and `create-admin`.
- [Relations](reference/relations.md) — required and optional relations, their interfaces and semantics.
- [Statuses](reference/statuses.md) — every `BlockedStatus`, `WaitingStatus`, `MaintenanceStatus`, and `ActiveStatus` message the charm emits.

## Explanation

- [Architecture](explanation/architecture.md) — single-container topology, reconcile pattern, why no queue mode in v1.
- [Encryption-key handling](explanation/encryption-key-handling.md) — auto-generation, override, why rotation is unsupported.
- [Limitations](explanation/limitations.md) — known constraints of the v1 charm.

## Writing style

If you contribute prose to these pages, read [STYLE.md](STYLE.md) first.
