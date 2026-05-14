"""Unit tests for src/state.py — peer-relation-backed CharmState wrapper."""

from __future__ import annotations

import pytest
from ops.testing import Harness

from charm import N8nK8sCharm
from state import CharmState

PEER_RELATION = "n8n-peers"


def _harness_with_peer() -> Harness:
    harness = Harness(N8nK8sCharm)
    harness.set_leader(True)
    harness.add_relation(PEER_RELATION, "n8n-k8s")
    harness.begin()
    return harness


def _harness_without_peer() -> Harness:
    harness = Harness(N8nK8sCharm)
    harness.set_leader(True)
    harness.begin()
    return harness


def test_encryption_key_secret_id_is_none_when_unset():
    harness = _harness_with_peer()
    try:
        state = CharmState(harness.charm)
        assert state.is_ready is True
        assert state.encryption_key_secret_id is None
    finally:
        harness.cleanup()


def test_encryption_key_secret_id_roundtrip():
    harness = _harness_with_peer()
    try:
        state = CharmState(harness.charm)
        state.encryption_key_secret_id = "secret:abc123"
        assert state.encryption_key_secret_id == "secret:abc123"
    finally:
        harness.cleanup()


def test_is_ready_false_without_peer_relation():
    harness = _harness_without_peer()
    try:
        state = CharmState(harness.charm)
        assert state.is_ready is False
        assert state.encryption_key_secret_id is None
    finally:
        harness.cleanup()


def test_setter_raises_without_peer_relation():
    harness = _harness_without_peer()
    try:
        state = CharmState(harness.charm)
        with pytest.raises(RuntimeError):
            state.encryption_key_secret_id = "secret:xyz"
    finally:
        harness.cleanup()
