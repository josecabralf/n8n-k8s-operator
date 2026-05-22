# Build a derived n8n image

The charm pins an upstream image in `charmcraft.yaml`:

```
upstream-source: docker.n8n.io/n8nio/n8n@sha256:32d7475...
```

To add community nodes you cannot install packages at runtime through the charm. Build a derived image that layers your additions on top of the upstream image, then pass it to the charm as a resource.

## Dockerfile

A minimal Dockerfile that installs a community node package:

```dockerfile
FROM docker.n8n.io/n8nio/n8n:1.x.y
USER root
RUN npm install -g n8n-nodes-browserless
USER node
```

Replace `1.x.y` with the upstream tag that corresponds to the pinned digest. Replace `n8n-nodes-browserless` with the package you want to install.

## Build and push

```bash
docker build -t registry.example/n8n-custom:v1 .
docker push registry.example/n8n-custom:v1
```

## Deploy with the derived image

For a fresh deployment:

```bash
juju deploy n8n --resource n8n-image=registry.example/n8n-custom:v1
```

To update an existing application:

```bash
juju refresh n8n --resource n8n-image=registry.example/n8n-custom:v1
```

## What the charm expects from the image

- **Command.** The charm starts the workload with `n8n start`. Do not override the image entrypoint or the service will fail to start.
- **Health endpoints.** Pebble probes `http://localhost:5678/healthz` (alive check) and `http://localhost:5678/healthz/readiness` (ready check, threshold 3). The image must expose these endpoints.
- **Writable mount.** The charm mounts `binary-data` storage at `/home/node/.n8n/binaryData` (`charmcraft.yaml`). The runtime user must be able to write there.
- **Environment variables.** The charm injects the full set of `N8N_*` variables it manages. The image must not hard-code values that conflict with those variables. See [configurations reference](../reference/configurations.md) for the full list.

## Caveats

The charm pins an upstream digest; a derived image replaces that pin entirely. Community node packages are unaudited third-party code: review the source before installing them. Upstream image upgrades and charm upgrades are independent release tracks. Track both and rebuild your derived image when the upstream digest changes.
