# Configure S3 binary-data storage

Integrate `s3-integrator` to store n8n file attachments in an S3-compatible
bucket instead of the application database. Once the relation is active, n8n
writes all binary data (uploaded files, workflow outputs) to the bucket and
reads them back on demand.

## When to use S3

Without a storage relation or an S3 relation, the charm runs in in-DB mode and
appends the status hint
`"binary data in DB; attach 'binary-data' storage or relate s3-integrator for production use"`
to the unit status. That mode is acceptable for development but unsuitable for
deployments where attachments are large or long-lived. When the `binary-data`
storage mount is attached, the charm switches to filesystem mode. When an S3
relation is active and credentials are ready, the charm ignores the storage
mount and uses S3 instead regardless of whether the mount is also present.

## Deploy s3-integrator

Deploy and configure the `s3-integrator` charm, then supply credentials via its
`sync-s3-credentials` action.

```bash
juju deploy s3-integrator
juju config s3-integrator \
    endpoint=https://s3.example.com \
    bucket=n8n-binary-data \
    region=us-east-1
juju run s3-integrator/leader sync-s3-credentials \
    access-key=<access-key> \
    secret-key=<secret-key>
```

Replace the endpoint, bucket, region, and credential values with those from
your S3-compatible provider. See the
[s3-integrator documentation](https://charmhub.io/s3-integrator) for the full
list of supported configuration options.

## Integrate with n8n

```bash
juju integrate n8n s3-integrator
```

The charm reads five credential fields from the S3 relation: `bucket`, `endpoint`, `region`,
`access-key`, and `secret-key`. All five must be present and non-empty before
the charm activates S3 mode. If any field is missing the charm treats the
relation as not yet ready and falls back to the next available mode.

## Env vars set on the workload

When all five credentials are present, the charm injects the following environment variables into the n8n container:

- `N8N_DEFAULT_BINARY_DATA_MODE=s3`
- `N8N_AVAILABLE_BINARY_DATA_MODES="filesystem,s3"`
- `N8N_EXTERNAL_STORAGE_S3_HOST` — from `endpoint`
- `N8N_EXTERNAL_STORAGE_S3_BUCKET_NAME` — from `bucket`
- `N8N_EXTERNAL_STORAGE_S3_BUCKET_REGION` — from `region`
- `N8N_EXTERNAL_STORAGE_S3_ACCESS_KEY` — from `access-key`
- `N8N_EXTERNAL_STORAGE_S3_ACCESS_SECRET` — from `secret-key`

`N8N_DEFAULT_BINARY_DATA_MODE` is set by the charm's managed-environment layer;
it is not user-configurable.

## Precedence: S3 wins

When both an S3 relation and the `binary-data` storage mount are active, S3
takes priority. The unit enters `active` with the status string
`"binary data: s3 (storage mount idle)"`, indicating that the filesystem mount
is present but unused.

## Detaching S3

```bash
juju remove-relation n8n s3-integrator
```

When the relation is removed, the charm re-evaluates binary-data mode. If the
`binary-data` storage mount is attached, the charm falls back to filesystem
mode. If the mount is absent, the charm falls back to in-DB mode. No data
migration is performed; files written to S3 while the relation was active
remain in the bucket but will not be accessible to n8n after the relation is
removed.
