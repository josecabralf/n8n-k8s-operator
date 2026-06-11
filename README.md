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
juju deploy traefik-k8s --channel=latest/stable --trust
juju deploy self-signed-certificates --channel=1/stable
juju config traefik-k8s routing_mode=subdomain external_hostname=example.com
juju integrate n8n postgresql-k8s
juju integrate n8n:ingress traefik-k8s
juju integrate traefik-k8s:certificates self-signed-certificates:certificates
```

Replace `example.com` with a domain whose subdomains resolve to Traefik's external address. Name both endpoints on the last `integrate`. `traefik-k8s` exposes `certificates` and `receive-ca-cert`, so the bare form fails as ambiguous.

Wait for all units to reach `active` (`juju status --watch 5s`), then create the owner account:

```bash
juju run n8n/0 create-admin \
  email=admin@example.com password=<your-password> \
  first-name=Ada last-name=Lovelace
```

The `create-admin` action is declared in `charmcraft.yaml`.

The UI is served at the root of a subdomain: `https://<model>-<app>.<external_hostname>/` (host-based routing; n8n's docs recommend serving at the root of a subdomain rather than under a path). The self-signed certificate is not trusted by browsers; accept the warning to proceed. n8n defaults to `N8N_SECURE_COOKIE=true`, so login requires HTTPS. Over plain HTTP the login page loads but authentication fails; for HTTP-only test setups, override it via the `environment` config option (`env: [{name: N8N_SECURE_COOKIE, value: "false"}]`).

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
