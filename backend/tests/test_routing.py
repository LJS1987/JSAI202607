"""경로 탐색 검증: 전비/시간 최적성과 샘플 도로망 통합."""

import pytest

from backend.app.graph import Graph, Node, Edge
from backend.app.routing import find_route, NoRouteError
from backend.app.sample_data import build_sample_graph
from backend.app.vehicles import PRESETS

IONIQ5 = PRESETS["ioniq5"]


def _graph_from_dict(raw: dict) -> Graph:
    g = Graph()
    for nid, a in raw["nodes"].items():
        g.add_node(Node(nid, a["lat"], a["lon"], a["elev"], a["signal"]))
    for e in raw["edges"]:
        g.add_edge(Edge(e["from"], e["to"], e["length"], e["road_class"]))
    return g


@pytest.fixture(scope="module")
def sample_graph() -> Graph:
    return _graph_from_dict(build_sample_graph())


def test_eco_uses_no_more_energy_than_fastest(sample_graph):
    eco = find_route(sample_graph, IONIQ5, "n0_0", "n12_12", hour=8, mode="eco")
    fast = find_route(sample_graph, IONIQ5, "n0_0", "n12_12", hour=8, mode="fastest")
    assert eco.total_energy_wh <= fast.total_energy_wh + 1e-6
    assert fast.total_time_s <= eco.total_time_s + 1e-6


def test_routes_differ_somewhere_on_grid(sample_graph):
    """신호·경사·등급이 섞인 격자에서 두 목적함수는 최소 한 구간에서 다른 경로를 내야 한다."""
    pairs = [("n0_0", "n12_12"), ("n0_6", "n12_6"), ("n2_1", "n10_11")]
    assert any(
        find_route(sample_graph, IONIQ5, a, b, 8, "eco").node_ids
        != find_route(sample_graph, IONIQ5, a, b, 8, "fastest").node_ids
        for a, b in pairs
    )


def test_route_is_connected(sample_graph):
    route = find_route(sample_graph, IONIQ5, "n0_0", "n5_5", hour=14, mode="eco")
    for leg, next_leg in zip(route.legs, route.legs[1:]):
        assert leg.to_id == next_leg.from_id
    assert route.node_ids[0] == "n0_0"
    assert route.node_ids[-1] == "n5_5"


def test_downhill_route_energy_can_be_negative():
    """긴 내리막 단일 경로는 총 소비가 음수(순충전)일 수 있어야 한다."""
    g = Graph()
    g.add_node(Node("top", 37.5, 127.0, 300.0, "none"))
    g.add_node(Node("bottom", 37.51, 127.0, 0.0, "none"))
    g.add_edge(Edge("top", "bottom", 3000.0, "primary"))
    route = find_route(g, IONIQ5, "top", "bottom", hour=3, mode="eco")
    assert route.total_energy_wh < 0


def test_no_route_raises():
    g = Graph()
    g.add_node(Node("a", 37.5, 127.0, 0, "none"))
    g.add_node(Node("b", 37.6, 127.1, 0, "none"))
    with pytest.raises(NoRouteError):
        find_route(g, IONIQ5, "a", "b", hour=8, mode="eco")


def test_rush_hour_is_slower_than_midnight(sample_graph):
    rush = find_route(sample_graph, IONIQ5, "n0_0", "n12_12", hour=8, mode="fastest")
    night = find_route(sample_graph, IONIQ5, "n0_0", "n12_12", hour=3, mode="fastest")
    assert rush.total_time_s > night.total_time_s
