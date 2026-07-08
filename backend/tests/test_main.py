"""FastAPI 엔드포인트 통합 테스트 — /api/vehicles, /api/route(ICE), /api/trip/ping."""

import pytest
from fastapi.testclient import TestClient

from backend.app import main

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _isolate_trip_db(tmp_path, monkeypatch):
    """실제 backend/data/trips.db 를 건드리지 않도록 매 테스트마다 임시 DB로 격리."""
    monkeypatch.setattr(main, "TRIP_DB_PATH", tmp_path / "trips.db")
    main._trip_conn = None
    main._learned_timings = None
    yield
    main._trip_conn = None
    main._learned_timings = None


def test_vehicles_include_all_fuel_types():
    resp = client.get("/api/vehicles")
    assert resp.status_code == 200
    fuel_types = {v["fuel_type"] for v in resp.json()}
    assert fuel_types == {"ev", "gasoline", "diesel"}
    for v in resp.json():
        assert v["eco_speed_kmh"] > 0


def test_route_for_ice_vehicle_returns_fuel_liters():
    resp = client.get("/api/route", params={
        "start_lat": 37.4979, "start_lon": 127.0276,
        "end_lat": 37.5115, "end_lon": 127.0595,
        "vehicle": "sonata_gas",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["vehicle"]["fuel_type"] == "gasoline"
    assert "fuel_l" in data["eco"]
    assert "efficiency_km_per_l" in data["eco"]
    assert "energy_kwh" not in data["eco"]
    assert all("eco_speed_kmh" in leg for leg in data["eco"]["legs"])


def test_route_for_ev_vehicle_unchanged_shape():
    resp = client.get("/api/route", params={
        "start_lat": 37.4979, "start_lon": 127.0276,
        "end_lat": 37.5115, "end_lon": 127.0595,
        "vehicle": "ioniq5",
    })
    data = resp.json()
    assert data["vehicle"]["fuel_type"] == "ev"
    assert "energy_kwh" in data["eco"]
    assert "fuel_l" not in data["eco"]


def test_trip_ping_near_signal_is_logged():
    graph = main.get_graph()
    signal_node = next(n for n in graph.nodes.values() if n.signal != "none")
    resp = client.post("/api/trip/ping", json={
        "lat": signal_node.lat, "lon": signal_node.lon, "speed_ms": 5.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["logged"] is True
    assert body["node_id"] == signal_node.id


def test_trip_ping_far_from_signal_is_not_logged():
    resp = client.post("/api/trip/ping", json={
        "lat": 35.0, "lon": 125.0, "speed_ms": 5.0,  # 도로망에서 멀리 벗어난 좌표
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["logged"] is False


def test_trip_relearn_reports_learned_node_count():
    resp = client.post("/api/trip/relearn")
    assert resp.status_code == 200
    assert resp.json()["learned_nodes"] == 0  # 로그가 없으니 학습된 노드 없음
