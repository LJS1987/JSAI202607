"""경찰청 신호운영 데이터 커넥터 — 실측 타이밍 파싱·노드 매칭 검증."""

import asyncio

import httpx
import pytest

from backend.app import providers
from backend.app.graph import Edge, Graph, Node
from backend.app.signals import SignalTiming

INTERSECTION = {
    "INT_NO": "101",
    "INT_NM": "테스트교차로",
    "X_COORD": 127.0,
    "Y_COORD": 37.5,
}
PLAN = {
    "CYCLE": 130.0,
    "OFFSET": 12.0,
    "A_RING_1": 55.0,
    "A_RING_2": 10.0,
}


def _mock_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/getCrossRoadInfoList"):
        return httpx.Response(
            200,
            json={"response": {"body": {"items": [INTERSECTION], "totalCount": 1}}},
        )
    if request.url.path.endswith(f"/{providers.POLICE_PLAN_OPERATION}"):
        return httpx.Response(
            200,
            json={"response": {"body": {"items": [PLAN]}}},
        )
    return httpx.Response(404)


@pytest.fixture
def mock_client(monkeypatch):
    transport = httpx.MockTransport(_mock_handler)
    real_async_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        return real_async_client(transport=transport)

    monkeypatch.setattr(providers.httpx, "AsyncClient", _factory)


def _graph_with_signal_at(lat: float, lon: float) -> Graph:
    g = Graph()
    g.add_node(Node("near", lat, lon, 0, "major"))
    g.add_node(Node("far", lat + 1.0, lon, 0, "major"))
    g.add_edge(Edge("near", "far", 1000.0, "primary"))
    return g


def test_no_api_key_returns_empty(monkeypatch):
    monkeypatch.delenv("POLICE_API_KEY", raising=False)
    graph = _graph_with_signal_at(37.5, 127.0)
    result = asyncio.run(providers.fetch_police_signal_timings(graph, "L01"))
    assert result == {}


def test_fetches_and_matches_nearest_signal_node(monkeypatch, mock_client):
    monkeypatch.setenv("POLICE_API_KEY", "test-key")
    graph = _graph_with_signal_at(37.5, 127.0)
    result = asyncio.run(providers.fetch_police_signal_timings(graph, "L01"))
    assert result == {"near": SignalTiming(cycle_s=130.0, green_s=65.0, offset_s=12.0)}


def test_no_match_when_signal_too_far(monkeypatch, mock_client):
    monkeypatch.setenv("POLICE_API_KEY", "test-key")
    graph = _graph_with_signal_at(37.9, 127.0)  # 수십 km 밖 — max_dist_m 밖
    result = asyncio.run(providers.fetch_police_signal_timings(graph, "L01"))
    assert result == {}
