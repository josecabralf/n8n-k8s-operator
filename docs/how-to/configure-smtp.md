# Configure SMTP for outbound mail

n8n sends notification emails (workflow errors, user invites, password resets) over SMTP. Configure the six SMTP keys in `charmcraft.yaml` and supply the password as a Juju user-secret.

## Required configs

All six keys are declared in `charmcraft.yaml` (lines 166–203).

| Config key      | Type    | Default | Env var            | Notes                                         |
|-----------------|---------|---------|--------------------|-----------------------------------------------|
| `smtp-host`     | string  | `""`    | `N8N_SMTP_HOST`    | Required together with `smtp-user` and `smtp-password`. |
| `smtp-port`     | int     | `587`   | `N8N_SMTP_PORT`    | Must be 1–65535. Used only when the trio is set. |
| `smtp-user`     | string  | `""`    | `N8N_SMTP_USER`    | Required together with `smtp-host` and `smtp-password`. |
| `smtp-password` | secret  | `""`    | `N8N_SMTP_PASSWORD`| Juju user-secret URI (`secret:<id>`). Must be granted to the app. |
| `smtp-sender`   | string  | `""`    | `N8N_SMTP_SENDER`  | Optional envelope-from address. Omitted from the environment when empty. |
| `smtp-ssl-tls`  | boolean | `false` | `N8N_SMTP_SSL`     | Set to `true` for implicit TLS (port 465 style). |

## Create the password secret

Store the SMTP password as a Juju user-secret so it is not exposed in plain config.

```bash
juju add-secret n8n-smtp-password value=<the-password>
```

`juju add-secret` prints the secret URI, e.g. `secret:cvf5hv0es9pc7g3s9280`. Grant that secret to the n8n application:

```bash
juju grant-secret n8n-smtp-password n8n
```

The secret must contain a single field named `value`. The charm reads `content.get("value")` (`src/charm.py:316`) and blocks if the field is absent.

## Configure the charm

Pass the URI printed by `juju add-secret` as the value of `smtp-password`. Replace `secret:cvf5hv0es9pc7g3s9280` with the URI from your own run.

```bash
juju config n8n \
  smtp-host=smtp.example.com \
  smtp-port=587 \
  smtp-user=notify@example.com \
  smtp-password=secret:cvf5hv0es9pc7g3s9280
```

`smtp-sender` and `smtp-ssl-tls` are optional. Set them if the server requires a specific envelope-from address or implicit TLS:

```bash
juju config n8n \
  smtp-sender=notify@example.com \
  smtp-ssl-tls=true
```

## Status while incomplete

The three keys `smtp-host`, `smtp-user`, and `smtp-password` must be set together or not at all. If any one is set without the others, the unit blocks (`src/pebble.py:385–386`):

```
"smtp-host, smtp-user, and smtp-password must all be set together"
```

If `smtp-port` is set outside the valid range, the unit blocks (`src/pebble.py:390`):

```
"invalid smtp-port '<port>'; must be 1–65535"
```

Correct the offending config value and the unit will re-reconcile automatically.

## Secret ungranted

If the secret URI in `smtp-password` has not been granted to the app, or the URI does not exist, the unit blocks (`src/charm.py:315`):

```
"<config-name> secret not granted to app"
```

If the secret exists and is granted but does not contain a `value` field, the unit blocks (`src/charm.py:318`):

```
"<config-name> secret missing 'value' field"
```

In both messages `<config-name>` is the config key that triggered the error (e.g. `smtp-password`). Run `juju grant-secret n8n-smtp-password n8n` to resolve the first case, or recreate the secret with the correct field name to resolve the second.
