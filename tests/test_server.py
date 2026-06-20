"""Integration smoke tests for the FastAPI desk service (webapp/server.py).

Covers the HTTP glue that the unit tests don't: the desk payload shape, the live structuring
and pricing endpoints, the TTL-cache refresh, and the optional API-token gate. Uses a small
desk build so the suite stays fast.
"""

import pytest
from fastapi.testclient import TestClient

import webapp.server as server


@pytest.fixture(scope="module", autouse=True)
def _small_desk():
    """Build a small desk (4 notes / 4k paths) so the HTTP tests stay fast."""
    original = server.build_desk_data
    server.build_desk_data = lambda **kw: original(n_notes=4, n_paths=4000, **kw)
    server._cache.update(payload=None, built_at=0.0)
    yield
    server.build_desk_data = original


@pytest.fixture(scope="module")
def client():
    return TestClient(server.app)


def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_desk_payload_shape(client):
    d = client.get("/api/desk").json()
    for key in ("positions", "net_greeks", "surface", "stress", "reserves", "data_source"):
        assert key in d
    assert d["data_source"] == "synthetic"


def test_price_endpoint_returns_greeks_and_scenarios(client):
    r = client.post(
        "/api/price",
        json={"product_type": "brc", "notional": 100, "observation_times": [0.5, 1.0],
              "params": {"coupon_rate": 0.06, "knock_in": 0.7, "strike": 1.0}},
    )
    assert r.status_code == 200
    body = r.json()
    assert "greeks" in body and "scenarios" in body and body["pv"] > 0


def test_structure_endpoint_solves(client):
    r = client.post(
        "/api/structure",
        json={"target_coupon": 0.12, "max_downside": 0.3, "maturity": 1.0, "obs_per_year": 4},
    )
    assert r.status_code == 200
    assert len(r.json()["pv_curve"]) > 0


def test_refresh_rebuilds(client):
    r = client.post("/api/desk/refresh")
    assert r.status_code == 200
    assert r.json()["status"] == "rebuilt"


def test_api_token_gate(client, monkeypatch):
    monkeypatch.setattr(server, "_API_TOKEN", "s3cret")
    body = {"product_type": "autocallable", "notional": 100, "observation_times": [1.0],
            "params": {"coupon_rate": 0.03, "knock_in": 0.6}}
    assert client.post("/api/price", json=body).status_code == 401
    assert client.post("/api/price", json=body, headers={"X-API-Token": "s3cret"}).status_code == 200
