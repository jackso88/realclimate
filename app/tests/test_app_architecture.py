"""Architecture fitness tests.

They check that the Python code, the topic registry and the Docker deployment
still describe the same system, and that services stay decoupled from each
other. A failure here means one of those pieces drifted away from the others.
"""

import ast
import importlib.util
import re
from pathlib import Path

import pytest

from app.health_monitor.models import HealthMonitorEnvironment
from app.messaging import topics
from app.downloader.current import consumer as current_consumer
from app.downloader.reference import consumer as reference_consumer
from app.core import consumer as core_consumer
from app.uploader import consumer as uploader_consumer

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "app"
COMPOSE = REPO_ROOT / "deploy" / "docker" / "compose.yaml"
DOCKERFILE = REPO_ROOT / "deploy" / "docker" / "Dockerfile"

COMMAND_PATTERN = re.compile(r'"python",\s*"-m",\s*"(app\.[\w.]+)"')
# Where one topic definition in compose.yaml ends and the next one begins.
NEXT_COMMAND_MARKERS = ("kafka-topics.sh", "create_topic")

requires_compose = pytest.mark.skipif(
    not COMPOSE.is_file(), reason="deployment files are not part of this checkout"
)

# Direct imports of one service's code by another that are intentional:
#   * services request a CMS session through the admin_auth client helper;
#   * the health monitor alerts through Telegram without going via Kafka.
ALLOWED_SERVICE_DEPENDENCIES = {
    ("downloader.current", "admin_auth"),
    ("health_monitor", "notifications.bot"),
    ("uploader", "admin_auth"),
}


def topic_names():
    return {value for name, value in vars(topics).items() if name.isupper()}


def production_sources():
    return [path for path in APP_DIR.rglob("*.py") if "tests" not in path.parts]


def service_of(module_name):
    """Return the service package a dotted module name belongs to."""
    parts = module_name.split(".")
    if len(parts) >= 3 and parts[1] == "downloader":
        return f"downloader.{parts[2]}"
    elif len(parts) >= 3 and parts[1] == "notifications":
        return f"notifications.{parts[2]}"
    return parts[1] if len(parts) > 1 else None


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)


@requires_compose
def test_every_topic_in_code_is_created_by_the_deployment():
    text = COMPOSE.read_text(encoding="utf-8")
    created = set(re.findall(r"--topic\s+([A-Za-z0-9._-]+)", text))

    assert topic_names() - created == set(), "topics missing from compose"
    assert created - topic_names() == set(), "compose creates unknown topics"


@requires_compose
def test_state_topics_are_log_compacted_so_retention_cannot_erase_them():
    text = COMPOSE.read_text(encoding="utf-8")
    state_topics = sorted(name for name in topic_names() if name.endswith(".state"))
    assert state_topics

    for name in state_topics:
        start = text.index(f"--topic {name}")
        ends = [text.find(marker, start + 1) for marker in NEXT_COMMAND_MARKERS]
        end = min((position for position in ends if position != -1), default=len(text))
        assert "cleanup.policy=compact" in text[start:end], name


def test_every_heartbeating_service_is_monitored_and_vice_versa():
    sender_patterns = (
        r'service_name\s*=\s*"([a-z_]+)"',
        r'HeartbeatReporter\(\s*\w+,\s*"([a-z_]+)"',
    )
    senders = set()
    for path in production_sources():
        text = path.read_text(encoding="utf-8")
        for pattern in sender_patterns:
            senders.update(re.findall(pattern, text))

    assert senders == set(HealthMonitorEnvironment.DEFAULT_MONITORED_SERVICES)


@requires_compose
def test_every_container_command_points_at_a_runnable_module():
    commands = set(COMMAND_PATTERN.findall(COMPOSE.read_text(encoding="utf-8")))
    commands |= set(COMMAND_PATTERN.findall(DOCKERFILE.read_text(encoding="utf-8")))
    assert commands

    for module_name in sorted(commands):
        spec = importlib.util.find_spec(module_name)
        assert spec is not None and spec.origin, f"{module_name} does not exist"
        source = Path(spec.origin).read_text(encoding="utf-8")
        assert "def main(" in source, f"{module_name} has no main()"
        assert 'if __name__ == "__main__":' in source, module_name


def test_the_shared_messaging_layer_does_not_depend_on_any_service():
    offenders = []
    for path in (APP_DIR / "messaging").rglob("*.py"):
        if "tests" in path.parts:
            continue
        for module in imported_modules(path):
            owner = service_of(module) if module.startswith("app.") else None
            if owner not in (None, "messaging", "contracts"):
                offenders.append((path.name, module))

    assert offenders == []


def test_services_only_depend_on_each_other_through_known_exceptions():
    found = set()
    for path in production_sources():
        module_name = ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)
        source_service = service_of(module_name)
        if source_service in (None, "main", "messaging", "contracts"):
            continue
        for imported in imported_modules(path):
            if not imported.startswith("app."):
                continue
            target_service = service_of(imported)
            if target_service not in (None, "messaging", "contracts", source_service):
                found.add((source_service, target_service))

    assert found == ALLOWED_SERVICE_DEPENDENCIES


def test_orchestrator_service_has_been_removed():
    source_files = (
        list((APP_DIR / "orchestrator").rglob("*.py"))
        if (APP_DIR / "orchestrator").exists()
        else []
    )
    assert source_files == []
    assert "orchestrator:" not in COMPOSE.read_text(encoding="utf-8")


def test_pub_sub_pipeline_routes_reference_to_current_and_core_to_uploader():
    assert reference_consumer.REFERENCE_SYNC_REQUESTS == topics.REFERENCE_SYNC_REQUESTS
    assert current_consumer.REFERENCE_DOWNLOADS == topics.REFERENCE_DOWNLOADS
    assert core_consumer.CORE_INPUT_TOPICS == [
        topics.REFERENCE_DOWNLOADS,
        topics.CURRENT_DOWNLOADS,
    ]
    assert uploader_consumer.CORE_PROCESS_RESULTS == topics.CORE_PROCESS_RESULTS


def test_message_envelope_is_owned_by_the_contracts_package():
    from app.contracts.models import Envelope

    assert Envelope.__module__ == "app.contracts.models"
