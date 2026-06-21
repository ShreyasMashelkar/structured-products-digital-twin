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
    server._cache.payload = None
    server._cache.built_at = 0.0
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


def test_xva_endpoint_charges_and_decides(client):
    """The Phase-6 governance tab: an autocallable → charge + exposure profile + decision."""
    r = client.post(
        "/api/xva",
        json={"product_type": "autocallable", "notional": 100,
              "observation_times": [0.5, 1.0, 1.5, 2.0], "maturity": 2.0,
              "params": {"coupon_rate": 0.04, "autocall_level": 1.0, "coupon_barrier": 0.8,
                         "knock_in": 0.6, "memory": True},
              "cds_spread_bps": 300.0, "recovery_rate": 0.40, "ead_limit": 1e9},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["decision"] in {"APPROVED", "REJECTED", "MANUAL_REVIEW"}
    assert b["charge"]["total"] == pytest.approx(b["charge"]["cva"] + b["charge"]["fva"])
    assert len(b["profile"]) > 0 and b["metrics"]["ead"] > 0
    # The spread sweep is monotone: a wider counterparty spread costs more CVA.
    sweep = b["spread_curve"]
    assert sweep[0]["cva"] == pytest.approx(0.0, abs=1e-3) and sweep[-1]["cva"] > sweep[0]["cva"]


def test_xva_limit_breach_rejects(client):
    """An EAD limit below the trade's own EAD must reject the trade."""
    r = client.post(
        "/api/xva",
        json={"product_type": "autocallable", "notional": 100,
              "observation_times": [0.5, 1.0, 1.5, 2.0], "maturity": 2.0,
              "params": {"coupon_rate": 0.04, "knock_in": 0.6}, "ead_limit": 0.01},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["decision"] == "REJECTED" and b["limit_status"] == "FAIL"


def test_xva_rejects_worst_of(client):
    r = client.post("/api/xva", json={"product_type": "worst_of", "notional": 100, "params": {}})
    assert r.status_code == 400


def test_xva_full_depth_payload(client):
    """The full charge (CVA+FVA+KVA+MVA−DVA), XVA risk, capital, and stress ladder are returned and
    internally consistent when the depth knobs are switched on."""
    r = client.post(
        "/api/xva",
        json={"product_type": "autocallable", "notional": 100,
              "observation_times": [0.5, 1.0, 1.5, 2.0], "maturity": 2.0,
              "params": {"coupon_rate": 0.04, "knock_in": 0.6, "autocall_level": 1.0,
                         "coupon_barrier": 0.8, "memory": True},
              "cds_spread_bps": 300.0, "cds_1y_bps": 150.0, "own_cds_bps": 120.0,
              "cost_of_capital": 0.12, "include_mva": True, "wwr_beta": 0.5, "ead_limit": 1e9},
    )
    assert r.status_code == 200
    b = r.json()
    ch = b["charge"]
    assert ch["kva"] > 0.0 and ch["mva"] > 0.0          # KVA + MVA switched on
    assert ch["total"] == pytest.approx(ch["cva"] + ch["fva"] + ch["kva"] + ch["mva"] - ch["dva"])
    assert b["sensitivities"]["cs01"] > 0.0
    assert b["capital"]["economic"] > 0.0 and b["capital"]["regulatory_bacva"] > 0.0
    assert b["capital"]["saccr_ead"] > 0.0
    cvas = [row["cva"] for row in b["stress_ladder"]]
    assert cvas == sorted(cvas)                          # stress ladder monotone in the shock


def test_xva_collateral_cuts_the_charge(client):
    """Turning on a CSA leaves only the close-out gap, so the total charge falls."""
    base = {"product_type": "autocallable", "notional": 100,
            "observation_times": [0.5, 1.0, 1.5, 2.0], "maturity": 2.0,
            "params": {"coupon_rate": 0.04, "knock_in": 0.6, "autocall_level": 1.0,
                       "coupon_barrier": 0.8, "memory": True}, "cds_spread_bps": 300.0}
    uncol = client.post("/api/xva", json={**base, "collateralised": False}).json()
    col = client.post("/api/xva", json={**base, "collateralised": True}).json()
    assert col["collateralised"] is True
    assert col["charge"]["cva"] < uncol["charge"]["cva"]


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
