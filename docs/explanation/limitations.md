# Limitations

This page lists known constraints of the v1 charm: what it does not do today, and why.

## Single-unit only

Only one unit runs the n8n process. Encryption-key generation, ingress publication, and the `create-admin` action are all leader-only operations; adding extra units does not increase throughput or availability. Horizontal scaling in n8n requires queue mode backed by Redis, neither of which is implemented in v1. Scale the unit vertically if throughput is a concern.

## No encryption-key rotation

Changing the encryption key after the first deploy bricks every credential stored by
n8n. Rotation is explicitly unsupported in v1. See
[encryption-key-handling.md](encryption-key-handling.md) for the full rationale and
the manual migration path.

## Binary-data in-DB fallback is suboptimal

Without `binary-data` storage attached or an S3 relation active, n8n stores workflow attachments directly in PostgreSQL. The charm surfaces this condition as the active status message `"binary data in DB; attach 'binary-data' storage or relate s3-integrator for production use"`. PostgreSQL in-DB storage works for low-volume use but does not suit production deployments with large or frequent file attachments. Attach the `binary-data` storage or integrate `s3-integrator` before going to production.

## No internal task runner

v1 runs a single n8n process that handles both the web UI and workflow execution. There is no queue mode, dedicated worker pool, or internal task runner. Workflows that generate sustained high execution load should be addressed by vertical scaling (larger Kubernetes resource limits) until a queue-mode slice is implemented.

## No rollback hooks

The charm has no explicit rollback handler or action. The reconcile loop is idempotent, so re-running it after a failed upgrade will restore the previous configuration, but the charm does not define a downgrade code path. The supported method to revert to a previous charm revision is:

```bash
juju refresh n8n --revision=<previous>
```

Downgrading the n8n application image independently of the charm revision is not
tested and may leave the database schema in an inconsistent state.

## Relation `limit: 1`

Every `requires` relation in `charmcraft.yaml` declares `limit: 1`: `postgresql`,
`ingress`, `s3`, `logging`, and `vault-k8s`. Multi-provider topologies, such
as two PostgreSQL backends or two ingress endpoints, are not supported. Attempting to
add a second provider for any of these relations will be rejected by Juju.

## Ingress endpoint renamed (breaking change)

Ingress now uses the provider-agnostic `ingress` interface, requested over an endpoint named `ingress`. Earlier charm revisions exposed ingress over a `traefik-route` endpoint (interface `traefik_route`). That endpoint no longer exists. After upgrading, the old `traefik-route` relation is gone and the operator must re-relate on `ingress`:

```bash
juju remove-relation n8n:traefik-route traefik-k8s
juju integrate n8n:ingress traefik-k8s
```

Because the endpoint speaks the `ingress` v2 interface, any v2-compatible provider satisfies it, not only `traefik-k8s`. `nginx-ingress-integrator` is one alternative.

## `assumes:` block

The charm declares two deployment requirements in `charmcraft.yaml`:

- `k8s-api` — the Juju controller must have access to the Kubernetes API. The charm
  cannot be deployed on a machine cloud.
- `juju >= 3.3` — Juju secrets (`ops.Secret`) are used for encryption-key storage.
  Older controllers will refuse to deploy the charm.

## Upstream n8n licence (SUL)

n8n upstream is published under the n8n Sustainable Use License (SUL), a
source-available licence that is not OSI-approved open source. The charm wraps the
upstream binary without modifying the licence terms; the SUL governs operating n8n
itself, not the charm code. The SUL permits self-hosting for internal use. It
restricts using n8n as the basis of a multi-tenant SaaS product offered to third
parties. Consult the upstream licence text at
<https://github.com/n8n-io/n8n/blob/master/LICENSE.md> before any commercial use.
