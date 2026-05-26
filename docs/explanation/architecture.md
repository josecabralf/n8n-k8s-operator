# Architecture

The charm runs a single `n8n` container managed by Pebble and exposes seven relation surfaces: `postgresql` (database), `s3` (binary-data object storage), `grafana-dashboard` (Grafana integration), `logging` (Loki log forwarding), `metrics-endpoint` (Prometheus scrape), `ingress` (HTTP ingress), and `vault-k8s` (secrets backend). Each relation surface connects directly to the corresponding charm library with no intermediate wrapper layer.

## Single container, single service

The `n8n` container is declared in `charmcraft.yaml` with one storage mount (`binary-data` at `/home/node/.n8n/binaryData`). Inside that container, a single Pebble service named `n8n` runs with `command: n8n start`, `override: replace`, and `startup: enabled`. There is no queue mode, worker pool, or separate container in v1.

With `task-runner=true`, n8n spawns a child runner process inside the same container to execute workflow code nodes. This is still one Pebble service and one container, not a queue-mode topology; Pebble manages only the `n8n start` process, which launches the runner as its child. With the default `task-runner=false`, every workflow execution runs in the same process that `n8n start` launches.

## State and peer relation

The charm keeps a peer relation named `n8n-peers` to propagate state across units. The peer-relation app databag is leader-writable and carries the Juju secret ID for the encryption key. Non-leader units read this ID from the databag; only the leader writes it.

## Reconcile pattern

On every relevant event the charm walks a linear sequence of prerequisite checks: it verifies the encryption key is resolved, validates tier-1 config and SMTP config, resolves user-supplied environment entries, checks that the PostgreSQL relation is present and credentials are available, confirms the ingress relation is present, and finally tests that the Pebble container is reachable. Each failed check transitions the unit to `BlockedStatus`, `WaitingStatus`, or `MaintenanceStatus` and stops processing. When all checks pass, the charm applies the Pebble layer and sets `ActiveStatus`.

## Pebble checks

Two HTTP checks run against `localhost:5678`. The `live` check (level `alive`) polls `/healthz` every 30 seconds with the default failure threshold. The `ready` check (level `ready`) polls `/healthz/readiness` every 10 seconds with `threshold: 3`, meaning Pebble requires three consecutive failures before marking the service not-ready. The threshold of 3 prevents the unit from flapping to a non-ready state during the startup window while n8n initialises its database schema.

## Why single-unit

Encryption-key generation, ingress publication, and the `create-admin` action are all leader-only operations. The peer relation carries the encryption-key secret ID so that a replacement leader can recover it, but the n8n process itself runs only on the leader. Horizontal scaling would require n8n's built-in queue mode, a Redis relation, and coordinated session affinity at the ingress layer. Those are not in scope for v1.

## Relation surfaces

The charm exposes seven relation endpoints. `postgresql` supplies the database credentials n8n requires to persist workflow state. `s3` connects to an S3-compatible store for binary workflow attachments. `grafana-dashboard`, `logging`, and `metrics-endpoint` wire the unit into a COS Lite observability stack (Grafana, Loki, and Prometheus respectively). `ingress` requests HTTP ingress over the provider-agnostic `ingress` v2 interface (`charms.traefik_k8s.v2.ingress.IngressPerAppRequirer`), so any v2-compatible provider works, such as `traefik-k8s` or `nginx-ingress-integrator`. The charm auto-publishes its routing requirements through the requirer and reads back the external URL; it does not build or submit provider-specific routing config. The URL drives the n8n env vars `N8N_HOST`, `N8N_PROTOCOL`, `N8N_PORT`, `WEBHOOK_URL`, `N8N_EDITOR_BASE_URL`, and `N8N_PATH`. `N8N_PATH` carries the URL subpath so the UI and webhooks resolve under path-based routing. `vault-k8s` provides a Vault KV backend as an alternative secrets store.
