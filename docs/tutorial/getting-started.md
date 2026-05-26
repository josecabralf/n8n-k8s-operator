# Get started with n8n

This page deploys n8n on microk8s, wires it to PostgreSQL and Traefik for ingress, terminates TLS with self-signed-certificates, and walks through bootstrapping the owner account. By the end, you will have a running n8n instance you can log into over HTTPS.

## Prerequisites

- [microk8s](https://microk8s.io/) installed and running
- [Juju](https://juju.is/) 3.6 or later bootstrapped against the microk8s cloud

The charm's `assumes:` block (declared in `charmcraft.yaml`) requires `k8s-api` and Juju >= 3.3. Juju 3.6 is recommended.

Enable the following microk8s add-ons before deploying:

```bash
microk8s enable storage dns metallb
```

Do not enable the microk8s `ingress` add-on. Ingress is provided by the `traefik-k8s` charm over the `ingress` relation.

## Deploy

Create a dedicated model, then deploy the n8n charm together with PostgreSQL, Traefik, and the certificate provider Traefik uses to terminate TLS.

```bash
juju add-model n8n-tutorial
```

Deploy the four applications:

```bash
juju deploy n8n --channel=edge
juju deploy postgresql-k8s --channel=14/stable --trust
juju deploy traefik-k8s --channel=latest/stable --trust
juju deploy self-signed-certificates --channel=1/stable
```

Add the required relations. The `postgresql` and `ingress` relations (declared in `charmcraft.yaml`) are both mandatory; the unit blocks without either.

```bash
juju integrate n8n postgresql-k8s
juju integrate n8n:ingress traefik-k8s
```

Give Traefik a TLS certificate. n8n defaults to `N8N_SECURE_COOKIE=true` (n8n's own default, not set by the charm), so it sends its session cookie only over HTTPS. Over plain HTTP the login page loads but authentication at `/setup` fails because the browser withholds the cookie. Relate Traefik to `self-signed-certificates` so it terminates TLS and serves the UI over HTTPS:

```bash
juju integrate traefik-k8s:certificates self-signed-certificates:certificates
```

Name both endpoints. `traefik-k8s` exposes a `certificates` and a `receive-ca-cert` endpoint, so `juju integrate traefik-k8s self-signed-certificates` fails as ambiguous.

## Wait for ActiveStatus

Watch the model until all units reach `active`:

```bash
juju status --watch 5s
```

The n8n unit passes through the following status strings before settling:

- `"waiting for postgresql relation"` (BlockedStatus): emitted before the `postgresql-k8s` integration is established
- `"waiting for database credentials"` (WaitingStatus): relation joined but PostgreSQL has not yet published credentials
- `"waiting for ingress relation"` (BlockedStatus): `traefik-k8s` integration not yet active
- `"waiting for ingress URL"` (WaitingStatus): the `ingress` relation is joined but the provider has not published an external URL yet
- `"waiting for n8n to start"` (MaintenanceStatus): service is up but the readiness probe at `/healthz/readiness` has not passed three consecutive checks yet

The expected end state in `juju status` once all checks pass:

```
Unit    Workload  Agent  Address      Ports  Message
n8n/0*  active    idle   10.x.x.x
```

The `Message` column is empty when n8n is healthy with no active warnings. If no S3 relation and no `binary-data` storage is attached, the message will instead read `"binary data in DB; attach 'binary-data' storage or relate s3-integrator for production use"`. That is an ActiveStatus advisory, not a failure.

## Reach the n8n UI

The ingress provider publishes the external URL over the `ingress` relation. Traefik v2 defaults to path-based routing, and with the `certificates` relation in place it serves over HTTPS, so the URL takes the form `https://<host>/<model>-<app>/`, for example `https://10.x.x.x/n8n-tutorial-n8n/`.

Retrieve it from the unit's relation data:

```bash
juju show-unit n8n/0
```

Look for the `ingress` relation data block; the URL is the value of the `url` field the provider published. Alternatively, the Traefik app status line in `juju status` shows the external address it is advertising.

Traefik redirects plain HTTP to HTTPS, so `http://<host>/<model>-<app>/` returns `301` to the HTTPS URL. The `self-signed-certificates` charm issues a certificate that browsers do not trust. Accept the browser warning to proceed, or pass `-k` to `curl`.

The charm reports `"waiting for ingress URL"` until the provider publishes that field. If Traefik has no external address yet (for example, MetalLB has not assigned one), wait for the address before accessing the UI.

## Bootstrap the owner

The `create-admin` action (declared in `charmcraft.yaml`) creates the instance owner account. Run it on the leader unit after n8n is active.

```bash
juju run n8n/0 create-admin \
  email=admin@example.com \
  password=changeme \
  first-name=Ada \
  last-name=Lovelace
```

Replace the values above with the credentials for your owner account. The password is accepted as plaintext and is stored in Juju action history. Treat it as you would any secret transmitted over an unencrypted channel: change it through the n8n UI immediately after first login.

The action fails with `"owner already exists; use n8n UI to manage users"` if the instance owner has already been bootstrapped. Each instance can only be bootstrapped once through this action.

## Back up the encryption key

n8n encrypts stored credentials with a key generated on first start and held in a Juju secret. Run the following to retrieve it:

```bash
juju run n8n/0 get-encryption-key
```

The action returns `{"encryption-key": "<hex value>"}` (declared in `charmcraft.yaml`). Store the key in a secure location outside the cluster. If the Juju model is destroyed and re-created, the encryption key must be supplied via the `encryption-key` config option or existing credentials in PostgreSQL will be unreadable. For details on key rotation and external key management, see [../explanation/encryption-key-handling.md](../explanation/encryption-key-handling.md).

## Next steps

- [Deploy with COS for observability](../how-to/deploy-with-cos.md)
- [Configure S3 binary data storage](../how-to/configure-s3-binary-data.md)
- [Configuration reference](../reference/configurations.md)
