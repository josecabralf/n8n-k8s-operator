"""Peer-relation-backed state for the n8n charm."""

from __future__ import annotations

from ops.charm import CharmBase
from ops.model import Relation

PEER_RELATION_NAME = "n8n-peers"
ENCRYPTION_KEY_SECRET_ID = "encryption-key-secret-id"
OWNER_BOOTSTRAPPED = "owner-bootstrapped"


class CharmState:
    """Read/write helpers over the n8n-peers app databag."""

    def __init__(self, charm: CharmBase) -> None:
        self._charm = charm

    @property
    def peer_relation(self) -> Relation | None:
        return self._charm.model.get_relation(PEER_RELATION_NAME)

    @property
    def is_ready(self) -> bool:
        """True iff the peer relation is joined (databag is writable on leader)."""
        return self.peer_relation is not None

    @property
    def encryption_key_secret_id(self) -> str | None:
        rel = self.peer_relation
        if rel is None:
            return None
        value = rel.data[self._charm.app].get(ENCRYPTION_KEY_SECRET_ID)
        return value or None

    @encryption_key_secret_id.setter
    def encryption_key_secret_id(self, value: str) -> None:
        rel = self.peer_relation
        if rel is None:
            raise RuntimeError(
                f"Cannot set encryption-key secret id: peer relation {PEER_RELATION_NAME!r} not yet joined"
            )
        rel.data[self._charm.app][ENCRYPTION_KEY_SECRET_ID] = value

    @property
    def owner_bootstrapped(self) -> bool:
        rel = self.peer_relation
        if rel is None:
            return False
        return rel.data[self._charm.app].get(OWNER_BOOTSTRAPPED) == "true"

    @owner_bootstrapped.setter
    def owner_bootstrapped(self, value: bool) -> None:
        rel = self.peer_relation
        if rel is None:
            raise RuntimeError(
                f"Cannot set owner-bootstrapped flag: peer relation {PEER_RELATION_NAME!r} not yet joined"
            )
        rel.data[self._charm.app][OWNER_BOOTSTRAPPED] = "true" if value else ""
