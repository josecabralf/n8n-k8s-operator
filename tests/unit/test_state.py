"""Unit tests for src/state.py — peer-relation-backed CharmState wrapper."""

from __future__ import annotations

import pytest

from state import CharmState


def test_encryption_key_secret_id_is_none_when_unset(harness_with_peer):
    state = CharmState(harness_with_peer.charm)
    assert state.is_ready is True
    assert state.encryption_key_secret_id is None


def test_encryption_key_secret_id_roundtrip(harness_with_peer):
    state = CharmState(harness_with_peer.charm)
    state.encryption_key_secret_id = "secret:abc123"
    assert state.encryption_key_secret_id == "secret:abc123"


def test_is_ready_false_without_peer_relation(harness_no_peer):
    state = CharmState(harness_no_peer.charm)
    assert state.is_ready is False


def test_encryption_key_secret_id_is_none_without_peer_relation(harness_no_peer):
    state = CharmState(harness_no_peer.charm)
    assert state.encryption_key_secret_id is None


def test_setter_raises_without_peer_relation(harness_no_peer):
    state = CharmState(harness_no_peer.charm)
    with pytest.raises(RuntimeError):
        state.encryption_key_secret_id = "secret:xyz"
