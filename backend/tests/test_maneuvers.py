"""턴바이턴 안내 생성(build_maneuvers) 단위 테스트."""

import pytest

from backend.app.graph import Graph
from backend.app.maneuvers import _bearing_deg, _classify_turn, build_maneuvers


def _graph_from_nodes(coords: dict[str, tuple[float, float]]) -> Graph:
    """id -> (lat, lon) 로 노드만 있는 그래프(엣지는 build_maneuvers 가 쓰지 않음)."""
    raw = {
        "nodes": {nid: {"lat": lat, "lon": lon} for nid, (lat, lon) in coords.items()},
        "edges": [],
    }
    return Graph.from_dict(raw)


def test_bearing_deg_north_and_east():
    assert _bearing_deg(37.0, 127.0, 37.001, 127.0) == pytest.approx(0.0, abs=1.0)
    assert _bearing_deg(37.0, 127.0, 37.0, 127.001) == pytest.approx(90.0, abs=1.0)


def test_classify_turn_straight_left_right_uturn():
    assert _classify_turn(5.0) == "slight_right"
    assert _classify_turn(-5.0) == "slight_left"
    assert _classify_turn(90.0) == "right"
    assert _classify_turn(-90.0) == "left"
    assert _classify_turn(120.0) == "sharp_right"
    assert _classify_turn(-120.0) == "sharp_left"
    assert _classify_turn(170.0) == "uturn"
    assert _classify_turn(-170.0) == "uturn"


def test_build_maneuvers_empty_for_single_node():
    graph = _graph_from_nodes({"a": (37.0, 127.0)})
    assert build_maneuvers(graph, ["a"], []) == []


def test_build_maneuvers_straight_route_has_only_depart_and_arrive():
    """일직선(북쪽) 3점 경로는 중간에 회전이 없으니 depart/arrive 만 나와야 한다."""
    graph = _graph_from_nodes({
        "a": (37.000, 127.0),
        "b": (37.001, 127.0),
        "c": (37.002, 127.0),
    })
    maneuvers = build_maneuvers(graph, ["a", "b", "c"], [100.0, 100.0])
    assert [m.type for m in maneuvers] == ["depart", "arrive"]
    assert maneuvers[0].node_id == "a"
    assert maneuvers[-1].node_id == "c"
    assert maneuvers[-1].distance_m == pytest.approx(200.0, abs=0.5)
    assert maneuvers[-1].cumulative_m == pytest.approx(200.0, abs=0.5)


def test_build_maneuvers_detects_right_turn():
    """북쪽으로 가다가 동쪽으로 꺾는 경로는 중간 노드에서 right 안내가 나와야 한다."""
    graph = _graph_from_nodes({
        "a": (37.000, 127.000),
        "b": (37.001, 127.000),   # a->b: 북쪽
        "c": (37.001, 127.001),   # b->c: 동쪽 (약 90도 우회전)
    })
    maneuvers = build_maneuvers(graph, ["a", "b", "c"], [100.0, 100.0])
    types = [m.type for m in maneuvers]
    assert types[0] == "depart"
    assert types[-1] == "arrive"
    assert "right" in types


def test_build_maneuvers_cumulative_distance_matches_leg_lengths():
    graph = _graph_from_nodes({
        "a": (37.000, 127.000),
        "b": (37.001, 127.000),
        "c": (37.001, 127.001),
        "d": (37.002, 127.001),
    })
    legs = [80.0, 120.0, 60.0]
    maneuvers = build_maneuvers(graph, ["a", "b", "c", "d"], legs)
    assert maneuvers[-1].cumulative_m == pytest.approx(sum(legs), abs=0.5)
