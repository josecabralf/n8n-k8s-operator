[![Release Edge](https://github.com/canonical/n8n-k8s-operator/actions/workflows/test_and_publish_charm.yaml/badge.svg)](https://github.com/canonical/n8n-k8s-operator/actions/workflows/publish_charm.yaml)

# n8n K8s Operator

[n8n](https://n8n.io/) is a source-available workflow automation platform.
It connects APIs, databases, and internal services through a visual editor,
and drops down to custom JavaScript or Python when a step needs code.

Small and medium teams self-host n8n to keep automation and the data it
touches on their own infrastructure. The upstream n8n Sustainable Use
License permits internal self-hosting; reselling n8n as a multi-tenant
SaaS is restricted. Read the upstream licence before commercial use.

## Quick deploy

```bash
juju add-model n8n
juju deploy n8n --channel=edge
juju deploy postgresql-k8s --channel=14/stable --trust
juju deploy traefik-k8s --channel=edge --trust
juju integrate n8n postgresql-k8s
juju integrate n8n traefik-k8s
juju run n8n/0 create-admin \
  email=admin@example.com password=<your-password> \
  first-name=Ada last-name=Lovelace
```

Minimum Juju: 3.3 (per `charmcraft.yaml` `assumes:`).

## Encryption key

n8n encrypts every stored credential with `N8N_ENCRYPTION_KEY`. The charm
auto-generates this key on first deploy. Run `juju run n8n/0 get-encryption-key`
immediately after deploy and store the result offsite. Rotation is not
supported in v1. See [docs/explanation/encryption-key-handling.md](docs/explanation/encryption-key-handling.md).

## Documentation

- [Tutorial](docs/tutorial/getting-started.md)
- [How-to guides](docs/how-to/)
- [Reference](docs/reference/)
- [Explanation](docs/explanation/)

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) and the
[Juju SDK docs](https://juju.is/docs/sdk).
