# Restart the n8n workload

The `restart` action stops and restarts the n8n workload service through Pebble
without reconfiguring the unit. Reach for it to pick up an upstream OCI image
refresh after `juju refresh`, to recover a wedged sidecar or process, or to
re-run the startup probes after fixing an external dependency. It is lighter
than a `juju refresh` or a scale-down/up.

## Run the action

The action runs per unit and does not require the leader.

```bash
juju run n8n/0 restart
```

While the service cycles, the unit shows `MaintenanceStatus("restarting n8n")`
with the message `restarting n8n`. The charm then re-runs its reconcile path and
returns to its normal status, typically `ActiveStatus`.

## What the restart does and does not touch

The action stops and restarts the `n8n` service in the Pebble plan. The unit is
not reconfigured: config is not re-read and relations are not re-resolved beyond
the normal reconcile that runs afterward to restore status.

Any in-flight workflow executions are interrupted by the restart.

The restart cycles only the running process. These survive untouched:

| State | Persistence layer |
|---|---|
| Workflows and credentials | PostgreSQL database, managed by `postgresql-k8s` |
| Encryption key | Juju app secret |
| Binary data (filesystem) | `binary-data` PVC |

## Failure modes

If the `n8n` container is not yet connectable, the action fails:

```
n8n container not yet connectable
```

If the `n8n` service has not been configured into the Pebble plan yet (for
example, required relations are not satisfied), the action fails:

```
n8n service not configured yet; nothing to restart
```
