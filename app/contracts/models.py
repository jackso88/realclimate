"""Compatibility alias for the message envelope.

The ``Envelope`` model is owned by the ``realclimate-contracts`` package.
New code should import it from there::

    from realclimate_contracts import Envelope

This module only keeps the old import path working while the services are moved
over, and is removed once nothing imports it.
"""

from realclimate_contracts.envelope import Envelope

__all__ = ["Envelope"]
