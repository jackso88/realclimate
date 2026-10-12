# RealClimate catalogue updater

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

Copy `.env.example` to `.env`, fill in the CMS and Telegram settings, and place
the Google OAuth client secret at `config/google/client_secret.json`. Then,
from the project root, start the independent services and Kafka broker with:

```bash
docker compose --env-file .env -f deploy/docker/compose.yaml up --build
```

Docker configuration is kept in `deploy/docker`. The Compose file uses the
project root as its build context, so application files, `.env`, and mounted
directories keep their existing locations. Compose passes only the variables
each service needs; for example, Google and Telegram secrets are limited to
their respective workers, and CMS login credentials are passed only to
`admin_auth`.

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

The Kafka broker and application containers use an internal plaintext network.
For deployment outside a trusted single-host Docker network, configure Kafka
SASL/TLS and restrict access to the broker before exposing it to other hosts.
