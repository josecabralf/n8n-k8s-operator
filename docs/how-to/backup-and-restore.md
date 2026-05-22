# Back up and restore n8n

Three artifacts must survive a disaster: the encryption key, the PostgreSQL
database, and the binary-data store. Losing any one of them results in either
an unbootable deployment or inaccessible workflow attachments.

## Capture the encryption key

Run the `get-encryption-key` action (declared in `charmcraft.yaml`):

```bash
juju run n8n/0 get-encryption-key
```

The action returns the current value of `N8N_ENCRYPTION_KEY` in the
`encryption-key` result field. The value is a 48-character hex string. Store it
offsite, in an offline vault or equivalent. This is the only retrieval path
after initial deployment. If the key is lost and the unit is redeployed, every
credential stored in the database is unreadable.

## Capture the database

This charm does not implement database backup. The PostgreSQL instance is
managed by the `postgresql-k8s` charm.

Use the postgresql-k8s backup mechanism to capture the n8n database. See the
postgresql-k8s documentation for the backup action and any prerequisites. The
database name defaults to `n8n`.

## Capture binary data

### Filesystem mode

The `binary-data` storage is a filesystem volume mounted at
`/home/node/.n8n/binaryData` (`charmcraft.yaml`):

```yaml
storage:
  binary-data:
    type: filesystem
    location: /home/node/.n8n/binaryData
    minimum-size: 1G
```

Take a Kubernetes-level PVC snapshot before any operation that could replace
the pod. Mount ownership is re-applied automatically on each reconcile, so no
manual fixup is needed after restore.

### S3 mode

The S3 bucket is the source of truth. The bucket name defaults to the
application name (configured via s3-integrator). Verify that all objects are
present in the bucket. The charm reads S3 credentials from the s3-integrator
relation on each reconcile and sets `N8N_EXTERNAL_STORAGE_S3_*` environment
variables accordingly.

## Restore on a fresh model

Follow these steps in order. n8n must not start before the encryption key and
database are in place, or credentials cannot be decrypted.

**1. Pre-create the encryption-key secret.**

Create a Juju user secret holding the saved key and grant it to the charm:

```bash
juju add-secret n8n-enc-key value=<48-char hex>
juju grant-secret n8n-enc-key n8n
```

Note the secret ID returned by `juju add-secret`.

**2. Deploy n8n with the saved key.**

Pass the secret ID as the `encryption-key` config so the charm uses the saved
key instead of auto-generating a new one:

```bash
juju deploy n8n --channel=edge --config encryption-key=secret:<id>
```

The `encryption-key` config option accepts a Juju secret URI
(`charmcraft.yaml`).

**3. Restore the PostgreSQL database.**

Restore the database dump before integrating n8n with postgresql-k8s, or
restore in-place via the postgresql-k8s restore action. The n8n database must
be present and consistent before n8n first connects.

**4. Reattach binary-data storage.**

For filesystem mode, restore the PVC snapshot and ensure the `binary-data`
storage is attached to the unit. The charm detects the attachment on each
reconcile and sets `binary_data_mode="filesystem"` automatically.

For S3 mode, ensure the S3 bucket objects are present, then relate
s3-integrator:

```bash
juju integrate n8n s3-integrator
```

**5. Integrate n8n.**

```bash
juju integrate n8n postgresql-k8s
juju integrate n8n traefik-k8s
```

Integrate s3-integrator if you are using S3 binary data (already done in step
4 if applicable).

**6. Verify.**

```bash
juju status
```

All units should reach `active` with no error messages. If the encryption key
was supplied correctly, the n8n UI should present existing workflows and
credentials without decryption errors.

## Restore drill

Run the full restore procedure once on a non-production model before treating
your backup process as validated. A backup that has never been exercised gives
no confidence that the artifacts are correct or that the recovery order works
in your environment.
