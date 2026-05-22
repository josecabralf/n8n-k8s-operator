# Add COS Lite observability

This guide assumes you have completed the steps in [Getting started](../tutorial/getting-started.md): n8n is deployed on microk8s, integrated with PostgreSQL and Traefik, and the unit is in `active` status. The steps below add metrics collection, log forwarding, and a Grafana dashboard using COS Lite.

## What you get

- **Metrics** via the `metrics-endpoint` relation: Prometheus scrapes n8n's `/metrics` endpoint.
- **Logs** via the `logging` relation: Loki receives forwarded workload logs.
- **Dashboard** via the `grafana-dashboard` relation: Grafana loads a pre-bundled dashboard JSON with workflow execution panels.

## Deploy COS Lite

Deploy COS Lite into a separate model, then create cross-model offers so the n8n model can consume them.

```bash
juju add-model cos
juju deploy cos-lite --channel=edge --trust
```

Once all COS Lite applications are active, offer the relevant endpoints:

```bash
juju offer cos.prometheus-k8s:metrics-endpoint
juju offer cos.loki-k8s:logging
juju offer cos.grafana-k8s:grafana-dashboard
```

Replace `cos` with the name of your COS model if you used a different value.

## Integrate with n8n

Switch to the model where n8n runs, then add each integration:

```bash
juju switch <n8n-model>
juju integrate n8n admin/cos.prometheus-k8s
juju integrate n8n admin/cos.loki-k8s
juju integrate n8n admin/cos.grafana-k8s
```

`MetricsEndpointProvider` (imported in `src/charm.py:21`) publishes scrape targets for the `metrics-endpoint` relation. `LogForwarder` (imported in `src/charm.py:20`, instantiated at `src/charm.py:115`) handles log forwarding over the `logging` relation. `GrafanaDashboardProvider` (imported in `src/charm.py:19`, instantiated at `src/charm.py:114`) publishes the dashboard JSON over the `grafana-dashboard` relation.

## What the charm publishes

Metrics scrape targets are configured as `*:5678` (port `N8N_PORT`, set at `src/charm.py:111`), so Prometheus scrapes all units on port 5678 at the `/metrics` path. Logs are forwarded by `LogForwarder` (`src/charm.py:115`); the library manages relation data and log collection without additional charm-side event handlers. The dashboard JSON is bundled at `src/grafana_dashboards/n8n.json` and published to Grafana through the `grafana-dashboard` relation.

## Toggle n8n internal metrics

No user action is required. When the `metrics-endpoint` relation is joined, the charm sets `N8N_METRICS=true` in the workload environment (`src/charm.py:543`), which enables n8n's built-in Prometheus exporter. The value is injected into the Pebble service layer via `src/pebble.py:476-477`. When the relation is removed, the variable is unset and the exporter is disabled.

## Dashboard panels

The `n8n Overview` dashboard (`src/grafana_dashboards/n8n.json`) contains three panels. The dashboard is intentionally minimal.

- Workflow execution rate
- Workflow execution duration
- Active executions
