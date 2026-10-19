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

Each service configures the same console log format from its own `config.py`.
The default level is INFO; pass `logging.DEBUG` to that service's
`configure_logging` function to enable debug output.

## Change-driven workflow

The scheduler publishes a `sync_reference` event once an hour during working
hours. The reference downloader reads the spreadsheet and compares its SHA-256
digest with the compacted Kafka state topic `reference.snapshot.state`. If the
bytes changed, it publishes a separate `reference_downloaded` event to
`downloader.reference.completed`; otherwise, the chain stops. The current
downloader subscribes to that event, downloads the CMS export, and publishes
only its own CSV in a `current_downloaded` event to
`downloader.current.completed`. Core subscribes to both downloader topics and
uses Redis to pair the two payloads by the scheduler's `correlation_id`. It
processes the pair and publishes `catalogue_processed` to
`core.process.results`. The uploader subscribes to core results and imports
only messages with detailed changes. The same `correlation_id` is preserved
through the pipeline and included in failure notifications. Each service can
have multiple instances in its own consumer group; Kafka delivers each event
to one instance per service.
The reference fingerprint is checkpointed only after core reports no changes
or uploader confirms a successful import. If a downstream step fails, the next
scheduled sync retries the pipeline even when the spreadsheet bytes are still
the same.

## Kafka deployment

Copy `.env.example` to `.env`, fill in the CMS, Telegram, and Kafka security
settings, and place Google credentials in
`app/downloader/reference/credentials/`. Generate strong random values for
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

A heartbeat comes from a background thread, so it proves the process is alive
but not that it is working: a worker blocked on one message would keep sending
it. Each heartbeat therefore also reports how long the worker has been busy
with its current message, and the monitor sends a "stuck" alert (and a follow-up
when the worker recovers) once that time passes `HEALTH_MAX_BUSY_SECONDS`
(default 5400). Set it above the longest expected operation. Services that
should answer faster can get their own limit, for example
`HEALTH_MAX_BUSY_OVERRIDES=core=600,notifications=120`; an unknown service name
is rejected at startup.

The monitor checks Kafka itself and sends outage and recovery messages directly
through the Telegram Bot API, so Kafka failure does not block those alerts. If
the health monitor process or the host loses internet access, it cannot send an
alert about that failure; use external monitoring for host-level availability.

Telegram rejects messages longer than 4096 characters, so a long change report
(the first run, for example, lists every new article) is sent as consecutive
messages labelled `[1/3]`, `[2/3]`, ... and split between lines or after
commas. Delivery errors are logged without the bot token, which `requests` would
otherwise print as part of the API URL.

The scheduler runs at the start of each hour from 09:00 through 17:00 Monday to
Friday in `Europe/Minsk`. The event chain skips current download, core
processing, and upload when the reference bytes have not changed. Core persists
only `storage/outputs/for_zalivka_excluded.csv`. Kafka retains event messages
for one hour and keeps reference fingerprints and duplicate-code mappings in
compacted state topics across container restarts. Redis stores incomplete core
input pairs under their `correlation_id` for up to 24 hours by default, and
removes a pair after successful processing. A completion marker with the same
TTL makes Kafka redelivery of already completed input a no-op. Its AOF
persistence and Docker volume preserve pending pairs across Redis container
restarts. The default `CORE_PENDING_INPUT_TTL_SECONDS` and
`CORE_PROCESSING_CLAIM_TTL_SECONDS` values
are 86400 and 7200 seconds; `noeviction` is configured so Redis does not evict
pending inputs under memory pressure. Core seeks and retries Kafka records when
Redis is unavailable, and commits after the Redis operation succeeds. Other
processing failures are reported and committed so malformed or unprocessable
records do not block that consumer partition indefinitely.
Set `GOOGLE_AUTH_MODE=user` to keep using the existing OAuth flow. Its client
secret and persisted refresh token are stored under
`app/downloader/reference/credentials/`; run
`python -m app.downloader.reference.auth_cli` on the host once to authorize.
Set `GOOGLE_AUTH_MODE=service_account` to use
`service_account_secret.json` from that same ignored directory instead. Share
the spreadsheet with the service account's email address as a reader before
switching modes. Service-account access tokens are refreshed automatically and
do not require the interactive authorization step. If Google denies the
service account access, the downloader retries with cached user OAuth
credentials when both `GOOGLE_CREDENTIALS_FILE` and `GOOGLE_TOKEN_FILE` are
available. Initialize the user token once with `GOOGLE_AUTH_MODE=user` and
`python -m app.downloader.reference.auth_cli` before relying on that fallback.


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
