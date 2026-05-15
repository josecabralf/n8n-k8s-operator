"""Ingress relation wrapper for n8n root-path ingress via traefik-route."""

from __future__ import annotations

from collections.abc import Callable

from charms.traefik_k8s.v0.traefik_route import TraefikRouteRequirer
from ops.charm import CharmBase
from ops.framework import Object

INGRESS_RELATION_NAME = "traefik-route"


class IngressRelation(Object):
    """Thin wrapper around TraefikRouteRequirer for n8n root-path ingress.

    The charm passes ``on_change``; the wrapper invokes it on any
    relation-lifecycle event so the charm's reconcile is the single
    source of truth for status + Pebble layer.
    """

    def __init__(self, charm: CharmBase, *, on_change: Callable[[], None]) -> None:
        super().__init__(charm, INGRESS_RELATION_NAME)
        self._charm = charm
        self._on_change = on_change

        rel = self._relation
        self._req: TraefikRouteRequirer | None = (
            TraefikRouteRequirer(charm, rel, relation_name=INGRESS_RELATION_NAME, raw=False)
            if rel is not None
            else None
        )

        charm.framework.observe(charm.on[INGRESS_RELATION_NAME].relation_created, self._handle)
        charm.framework.observe(charm.on[INGRESS_RELATION_NAME].relation_changed, self._handle)
        charm.framework.observe(charm.on[INGRESS_RELATION_NAME].relation_broken, self._handle)

        # Only attach the lib's ready event when the relation exists.
        if self._req is not None:
            charm.framework.observe(self._req.on.ready, self._handle)

    def _handle(self, _event) -> None:
        self._on_change()

    @property
    def _relation(self):
        return self._charm.model.get_relation(INGRESS_RELATION_NAME)

    @property
    def _requirer(self) -> TraefikRouteRequirer | None:
        if self._req is None:
            rel = self._relation
            if rel is None:
                return None
            self._req = TraefikRouteRequirer(self._charm, rel, relation_name=INGRESS_RELATION_NAME, raw=False)
        return self._req

    def is_related(self) -> bool:
        return self._relation is not None

    @property
    def external_host(self) -> str:
        req = self._requirer
        return req.external_host if req else ""

    @property
    def scheme(self) -> str:
        req = self._requirer
        return req.scheme if req else ""

    @property
    def url(self) -> str | None:
        host, scheme = self.external_host, self.scheme
        if not host or not scheme:
            return None
        return f"{scheme}://{host}/"

    def publish_route(self) -> None:
        """Submit a Host-routed dynamic config to traefik. Leader-only."""
        if not self._charm.unit.is_leader():
            return
        req = self._requirer
        if req is None or self.url is None:
            return
        model = self._charm.model.name
        app = self._charm.app.name
        router_name = f"juju-{model}-{app}"
        service_name = f"{router_name}-service"
        config = {
            "http": {
                "routers": {
                    router_name: {
                        "entryPoints": ["web"],
                        "rule": f"Host(`{self.external_host}`)",
                        "service": service_name,
                    },
                },
                "services": {
                    service_name: {
                        "loadBalancer": {
                            "servers": [{"url": (f"http://{app}-endpoints.{model}" f".svc.cluster.local:5678")}],
                        },
                    },
                },
            },
        }
        req.submit_to_traefik(config)
