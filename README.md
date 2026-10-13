# RealClimate catalogue updater

<p align="center">
  <img src="docs/assets/realclimate-admin.png" alt="RealClimate Admin" width="420">
</p>

Python services that download catalogue data from Google Sheets and the CMS,
merge it in memory, and send the result back to the CMS.

## Local setup

Install Poetry, install the project dependencies, and configure the
repository-local commit hook:

```bash
pipx install poetry==2.5.1
poetry install
git config core.hooksPath .githooks
```

Before each commit the hook formats staged Python files with Black, stages the
formatted files, and runs the full pytest suite. To run the checks manually:

```bash
poetry run python -m black app
poetry run python -m pytest -q
```

GitHub Actions runs `black --check app` and `pytest -q` on every push and pull
request.

## Logging

Command line entry points configure a consistent INFO-level log format.
The default level is INFO. Module level debug messages can be enabled by
calling `configure_logging(logging.DEBUG)` from an entry point.

## Kafka deployment

Copy `.env.example` to `.env`, fill in the CMS, Telegram, and Kafka security
settings, and place the Google OAuth client secret at
`config/google/client_secret.json`. Generate strong random values for
`KAFKA_SASL_PASSWORD` and `KAFKA_TLS_STORE_PASSWORD`; both values must contain
only letters, digits, dots, underscores, and dashes. Then, from the project
root, start the services and Kafka broker with:

```bash
docker compose --env-file .env -f deploy/docker/compose.yaml up --build
```

Docker configuration is kept in `deploy/docker`. The Compose file uses the
project root as its build context, so application files, `.env`, and mounted
directories keep their existing locations. Compose passes only the variables
each service needs; Google credentials go only to `downloader_reference`, the
Telegram token goes to `notifications` and `health_monitor`, and CMS login
credentials are passed only to `admin_auth`.
The admin authentication service caches its serialized session snapshot for
`ADMIN_AUTH_SESSION_CACHE_TTL_SECONDS` (default: 4 hours).

Long-running application containers and the Kafka broker use the
`unless-stopped` restart policy. To start them automatically after a system
reboot, enable the Docker daemon in the operating system (on systemd-based Linux:
`sudo systemctl enable --now docker`). A container stopped explicitly remains
stopped until started again.

Kafka client traffic uses TLS with SASL/SCRAM-SHA-512 authentication. Compose
generates a self-signed broker certificate on first startup and provisions the
SCRAM user through a bootstrap listener bound only to the broker container's
loopback interface. The broker listener, controller listener, and bootstrap
listener are not published to the host. The private broker key and public
client trust bundle are stored in separate Docker volumes. Kafka log data is
not encrypted at rest by this setup; protect the host or Docker storage if that
is also required. Keep the real `.env` file secret and outside version control.

The broker certificate and trust bundle persist in Docker volumes. If you
change `KAFKA_TLS_STORE_PASSWORD` or need to regenerate the certificate, stop
the stack and remove the `kafka_server_certs` and `kafka_client_certs` volumes
before starting it again. Removing `kafka_data` also erases persisted Kafka
state and is not needed for normal certificate rotation.

### Service health monitoring

The `health_monitor` container watches Kafka heartbeats from `admin_auth`, both
downloaders, `core`, `uploader`, `scheduler`, and `notifications`. Workers send a
heartbeat every 30 seconds. A service is reported unavailable after 120 seconds
without a heartbeat; startup and Kafka reconnection have a 180-second grace
period. These thresholds can be changed with `HEALTH_HEARTBEAT_TIMEOUT_SECONDS`,
`HEALTH_STARTUP_GRACE_SECONDS`, and `HEALTH_CHECK_INTERVAL_SECONDS`.

The monitor checks Kafka itself and sends outage and recovery messages directly
through the Telegram Bot API, so Kafka failure does not block those alerts. If
the health monitor process or the host loses internet access, it cannot send an
alert about that failure; use external monitoring for host-level availability.

The scheduler runs at the start of each hour from 09:00 through 17:00 Monday to
Friday in `Europe/Minsk`. Core downloads both source CSVs concurrently, processes
them in memory, imports the result, and persists only
`storage/outputs/for_zalivka_excluded.csv`. Kafka retains queue messages for one
hour and keeps the duplicate-code mapping in a compacted state topic across
core container restarts.
Google's OAuth token is kept under `config/google/token.json`, alongside the
ignored client secret, and persists across container restarts. Before starting
the headless workers, run `python -m app.downloader.reference.auth_cli` once on
the host to authorize Google and create that token; this setup step does not
download or write a catalogue CSV. OAuth requires interactive user
authorization and the resulting token is secret material, so it is not
generated while building a Docker image.


### Kafka TLS integration check

With the Compose stack configured from `.env`, run the isolated live-broker checks with:

```bash
docker compose --env-file .env -f deploy/docker/compose.yaml --profile integration run --build --rm kafka_tls_integration_test
```

The checks validate the broker certificate against the configured private CA,
confirm that the broker certificate is rejected by the system trust store, and
round-trip a uniquely named test record through a SASL_SSL producer and consumer.
The integration service is opt-in and does not start with the normal application
stack.
