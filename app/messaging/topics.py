"""Compatibility alias for the Kafka topic registry.

Topic names are owned by the ``realclimate-contracts`` package. New code should
import them from there::

    from realclimate_contracts.topics import CORE_PROCESS_RESULTS

This module re-exports the shared names so the old import path keeps working
while the services are moved over, and is removed once nothing imports it.
"""

from realclimate_contracts.topics import *  # noqa: F401,F403

# Still used by the core worker until its state moves to the database service.
CORE_ABSENT_ARTICLES_STATE = "core.absent-articles.state"
