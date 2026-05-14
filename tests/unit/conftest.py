"""Shared fixtures for n8n-k8s charm unit tests."""

from __future__ import annotations

import pytest
from ops.testing import Harness

from charm import N8nK8sCharm

CONTAINER_NAME = "n8n"


@pytest.fixture
def harness():
    """Return a primed Harness with the n8n container ready to talk to."""
    harness = Harness(N8nK8sCharm)
    harness.set_leader(True)
    harness.set_can_connect(CONTAINER_NAME, True)
    yield harness
    harness.cleanup()
