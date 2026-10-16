"""Contract tests for the Kafka topic names shared by all services."""

import re

from app.messaging import topics

KAFKA_TOPIC_NAME = re.compile(r"^[A-Za-z0-9._-]{1,249}$")


def topic_values():
    """Return every public topic constant defined in the topics module."""
    return {name: value for name, value in vars(topics).items() if name.isupper()}


def test_every_topic_is_a_nonempty_string():
    values = topic_values()

    assert values
    assert all(isinstance(value, str) and value for value in values.values())


def test_topic_names_are_unique():
    values = list(topic_values().values())

    assert len(values) == len(set(values))


def test_topic_names_only_use_characters_kafka_allows():
    values = topic_values().values()
    invalid = [value for value in values if not KAFKA_TOPIC_NAME.match(value)]

    assert invalid == []


def test_topic_names_do_not_collide_in_kafka_metrics():
    # Kafka treats "." and "_" as the same character in metric names, so two
    # topics that differ only by that character can collide.
    normalized = [value.replace(".", "_") for value in topic_values().values()]

    assert len(normalized) == len(set(normalized))
