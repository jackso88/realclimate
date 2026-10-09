# RealClimate catalogue updater

Python tools for downloading the reference catalogue, exporting the current
catalogue from the CMS, and merging the two data sources.

## Local setup

Install the dependencies and configure the repository-local commit hook:

```bash
python -m pip install -r requirements.txt
git config core.hooksPath .githooks
```

Before each commit the hook formats staged Python files with Black, stages the
formatted files, and runs the full pytest suite. To run the checks manually:

```bash
python -m black app
python -m pytest -q
```

GitHub Actions runs `black --check app` and `pytest -q` on every push and pull
request.

## Logging

Command line entry points configure a consistent INFO-level log format.
The default level is INFO. Module level debug messages can be enabled by
calling `configure_logging(logging.DEBUG)` from an entry point.
