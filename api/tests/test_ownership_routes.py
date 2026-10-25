"""Every real route that takes an ID checks ownership (TRD §3.1), not just the probe routes."""

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from sherlock import ownership

API = "/api/v1"
CSV = b"name,age\nAnn,30\nBob,41\n"

# Routes that check ownership in their body instead of through a dependency, and why.
INLINE_CHECKS = {
    "restore_dataset": "check_dataset(include_deleted=True): it must find a soft-deleted dataset",
}


def api_routes(routes):
    """The app's APIRoutes, including those inside included routers (FastAPI wraps them lazily)."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from api_routes(route.original_router.routes)


def dependency_calls(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from dependency_calls(dep)


def is_ownership_check(call) -> bool:
    return call is ownership.owned_dataset or (
        getattr(call, "__module__", "") == ownership.__name__
        and getattr(call, "__qualname__", "") == "owned.<locals>.dependency"
    )


def test_every_route_with_an_id_has_an_ownership_dependency(app):
    routes = list(api_routes(app.routes))
    assert len(routes) > 20  # the walk found the /api/v1 routers
    missing = []
    for route in routes:
        if not route.dependant.path_params or route.endpoint.__name__ in INLINE_CHECKS:
            continue
        if not any(is_ownership_check(c) for c in dependency_calls(route.dependant)):
            missing.append(f"{','.join(sorted(route.methods))} {route.path}")
    assert missing == [], f"routes without owned_dataset/owned(kind): {missing}"


def test_inline_checks_still_exist(app):
    names = {r.endpoint.__name__ for r in api_routes(app.routes)}
    assert set(INLINE_CHECKS) <= names  # drop an entry when its route goes


def test_restore_is_owner_only(app):
    with TestClient(app) as alice, TestClient(app) as bob:
        ds = alice.post(f"{API}/datasets", files={"file": ("people.csv", CSV, "text/csv")}).json()
        bob.get(f"{API}/me")
        assert alice.delete(f"{API}/datasets/{ds['id']}").status_code == 204
        res = bob.post(f"{API}/datasets/{ds['id']}/restore")
        assert res.status_code == 404 and res.json()["error"]["code"] == "not_found"
        assert alice.post(f"{API}/datasets/{ds['id']}/restore").status_code == 200
