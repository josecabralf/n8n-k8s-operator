[![Release Edge](https://github.com/canonical/n8n-k8s-operator/actions/workflows/test_and_publish_charm.yaml/badge.svg)](https://github.com/canonical/n8n-k8s-operator/actions/workflows/publish_charm.yaml)

# n8n K8s Operator

This is the Kubernetes Python Operator for [n8n](https://n8n.io/).

## Description

n8n is a source-available workflow automation platform that lets teams connect
APIs, databases, and internal services through a visual, low-code editor while
still allowing custom code where needed.

This [operator](https://charmhub.io/n8n-k8s) provides an n8n server, and
consists of Python scripts which wrap the versions distributed by
[n8n.io](https://docker.n8n.io/n8nio/n8n). It offers opinionated defaults,
standard Canonical relations (PostgreSQL, ingress, COS Lite, S3), automatic
encryption-key management, and a clean upgrade path on Juju Kubernetes clouds.

## Encryption-key handling (read before deploy)

n8n encrypts every stored credential with `N8N_ENCRYPTION_KEY`. The charm
auto-generates this key as a Juju app secret on install. Run
`juju run n8n-k8s/0 get-encryption-key` immediately after deploy and store
the result offsite — if you lose it, every stored credential is bricked.
**Encryption-key rotation is NOT supported in v1.** Changing the
`encryption-key` config after the charm has stored credentials will brick
them. Use the override only when migrating from an existing n8n install:
create a Juju user secret with a `value` field, grant it to the
application, and set `encryption-key=secret:<id>`.

## Contributing

This charm is still in active development. Please see the
[Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this
charm following best practice guidelines, and
[CONTRIBUTING.md](./CONTRIBUTING.md) for developer guidance.
