# Architecture

The charm runs a single `n8n` container managed by Pebble and exposes seven relation surfaces. Those surfaces are imported directly in `src/charm.py:17-23`: `DatabaseRequires` (PostgreSQL), `S3Requirer`, `GrafanaDashboardProvider`, `LogForwarder` (Loki), `MetricsEndpointProvider` (Prometheus), `TraefikRouteRequirer`, and `vault_kv`. No wrapper layer sits between the charm class and the library objects; the `src/relations/` directory is empty.

## Single container, single service

The `n8n` container is declared in `charmcraft.yaml:22-27` with one storage mount (`binary-data` at `/home/node/.n8n/binaryData`). Inside that container, `build_layer()` in `src/pebble.py:498` defines a single Pebble service named `n8n` with `command: n8n start`, `override: replace`, and `startup: enabled`. There is no queue mode, worker pool, or separate runner process in v1; every workflow execution runs in the same process that the `n8n start` command launches.

## State module

`src/state.py:8-43` defines two module-level constants, `PEER_RELATION_NAME = "n8n-peers"` and `ENCRYPTION_KEY_SECRET_ID = "encryption-key-secret-id"`, and a `CharmState` class that wraps the peer-relation app databag. The class exposes three properties: `peer_relation` (returns the relation object or `None`), `is_ready` (true once the peer relation is joined), and `encryption_key_secret_id` (a getter/setter pair that reads and writes the secret ID string in the app databag). Only the leader can write the databag, so secret-ID propagation is inherently leader-scoped.

## Reconcile pattern

Most event handlers call `_reconcile()` at `src/charm.py:463`. The method walks a linear sequence of prerequisite checks: it verifies the encryption key is resolved, validates tier-1 config and SMTP config, resolves user-supplied environment entries, checks that the PostgreSQL relation is present and credentials are available, confirms the ingress relation is present, and finally tests that the Pebble container is reachable. Each failed check calls `self.unit.status =` with `BlockedStatus`, `WaitingStatus`, or `MaintenanceStatus` and returns early. When all checks pass, `_reconcile` builds the Pebble layer, applies it, and sets `ActiveStatus`.

## Pebble checks

`src/pebble.py:504-517` defines two HTTP checks against `localhost:5678`. The `live` check (level `alive`) polls `/healthz` every 30 seconds with the default failure threshold. The `ready` check (level `ready`) polls `/healthz/readiness` every 10 seconds with `threshold: 3`, meaning Pebble requires three consecutive failures before marking the service not-ready. The threshold of 3 prevents the unit from flapping to a non-ready state during the startup window while n8n initialises its database schema.

## Why single-unit

The encryption key is generated and stored by the leader unit during `_reconcile`. Ingress publication and the `create-admin` action are also leader-only operations. The peer relation carries the encryption-key secret ID so that a replacement leader can recover it, but the n8n process itself runs only on the leader. Horizontal scaling would require n8n's built-in queue mode, a Redis relation, and coordinated session affinity at the ingress layer. Those are not in scope for v1.

## Relation surfaces

- **PostgreSQL** — `charms.data_platform_libs.v0.data_interfaces.DatabaseRequires` (`src/charm.py:17`)
- **S3** — `charms.data_platform_libs.v0.s3.S3Requirer` (`src/charm.py:18`)
- **Grafana dashboard** — `charms.grafana_k8s.v0.grafana_dashboard.GrafanaDashboardProvider` (`src/charm.py:19`)
- **Loki** — `charms.loki_k8s.v1.loki_push_api.LogForwarder` (`src/charm.py:20`)
- **Prometheus scrape** — `charms.prometheus_k8s.v0.prometheus_scrape.MetricsEndpointProvider` (`src/charm.py:21`)
- **Traefik route** — `charms.traefik_k8s.v0.traefik_route.TraefikRouteRequirer` (`src/charm.py:22`)
- **Vault KV** — `charms.vault_k8s.v0.vault_kv` (`src/charm.py:23`)
