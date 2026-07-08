"""신호 시뮬레이터·시간 의존 라우팅·GLOSA 검증."""

import pytest

from backend.app.glosa import compute_advisories, min_advisory_ms
from backend.app.graph import Edge, Graph, Node
from backend.app.routing import find_route
from backend.app.sample_data import build_sample_graph
from backend.app.signals import SignalSimulator, SignalTiming
from backend.app.vehicles import PRESETS

IONIQ5 = PRESETS["ioniq5"]
SIM = SignalSimulator()


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


# ---- 시뮬레이터 자체 ----

def test_signal_cycle_covers_green_and_red():
    node = Node("x", 37.5, 127.0, 0, "major")
    timing = SIM.timing_for(node)
    states = {SIM.state_at(node, timing.offset_s + t).color for t in range(0, 160, 5)}
    assert states == {"green", "red"}


def test_signal_is_deterministic():
    node = Node("x", 37.5, 127.0, 0, "major")
    assert SIM.state_at(node, 12345.0) == SIM.state_at(node, 12345.0)


def test_wait_is_zero_on_green_and_bounded_on_red():
    node = Node("x", 37.5, 127.0, 0, "minor")
    timing = SIM.timing_for(node)
    for t in range(0, int(timing.cycle_s) * 2, 3):
        wait = SIM.wait_at(node, float(t))
        state = SIM.state_at(node, float(t))
        if state.color == "green":
            assert wait == 0.0
        else:
            assert 0 < wait <= timing.cycle_s - timing.green_s


def test_no_signal_node_never_waits():
    node = Node("x", 37.5, 127.0, 0, "none")
    assert SIM.timing_for(node) is None
    assert SIM.wait_at(node, 100.0) == 0.0


def test_real_timing_overrides_simulation_for_matched_node():
    """경찰청 실데이터가 있는 노드는 그 값을, 없는 노드는 기존 가상 시뮬레이션을 쓴다."""
    real = SignalTiming(cycle_s=90.0, green_s=40.0, offset_s=5.0)
    sim = SignalSimulator(real_timings={"x": real})
    matched = Node("x", 37.5, 127.0, 0, "major")
    unmatched = Node("y", 37.5, 127.0, 0, "major")
    assert sim.timing_for(matched) == real
    assert sim.timing_for(unmatched) == SIM.timing_for(unmatched)


# ---- 시간 의존 라우팅 ----

def test_sim_mode_routes_are_valid(sample_graph):
    eco = find_route(sample_graph, IONIQ5, "n0_0", "n12_12", 8, "eco", signals=SIM)
    fast = find_route(sample_graph, IONIQ5, "n0_0", "n12_12", 8, "fastest", signals=SIM)
    assert eco.total_energy_wh <= fast.total_energy_wh + 1e-6
    assert eco.node_ids[0] == "n0_0" and eco.node_ids[-1] == "n12_12"


def test_sim_waits_are_deterministic_not_expected_values(sample_graph):
    """시뮬레이터 모드의 대기는 0이거나 실제 적색 잔여시간(확정값)이어야 한다."""
    route = find_route(sample_graph, IONIQ5, "n0_0", "n8_8", 8, "fastest", signals=SIM)
    signalized = [leg for leg in route.legs
                  if sample_graph.nodes[leg.to_id].signal != "none"]
    assert signalized, "신호 교차로를 지나야 의미 있는 테스트"
    # 통계 모드라면 모든 신호 구간 대기가 동일한 기대값일 것 — 확정 모드는 0 포함 다양
    waits = {round(leg.wait_s, 1) for leg in signalized}
    assert len(waits) > 1 or 0.0 in waits


def test_departure_time_changes_sim_route_metrics(sample_graph):
    """출발 시각이 다르면 신호 위상이 달라져 결과가 달라진다."""
    a = find_route(sample_graph, IONIQ5, "n0_0", "n8_8", 8, "fastest",
                   signals=SIM, depart_s=8 * 3600.0)
    b = find_route(sample_graph, IONIQ5, "n0_0", "n8_8", 8, "fastest",
                   signals=SIM, depart_s=8 * 3600.0 + 40.0)
    assert a.total_time_s != b.total_time_s or a.node_ids != b.node_ids


# ---- GLOSA ----

def _straight_graph_with_red_signal() -> Graph:
    """정차가 확정되는 외길: 신호 위상은 해시라 여러 출발 시각으로 탐색."""
    g = Graph()
    g.add_node(Node("a", 37.50, 127.00, 0, "none"))
    g.add_node(Node("b", 37.51, 127.00, 0, "major"))
    g.add_node(Node("c", 37.52, 127.00, 0, "none"))
    for u, v in [("a", "b"), ("b", "c")]:
        g.add_edge(Edge(u, v, 1000.0, "primary"))
    return g


def test_glosa_advisory_replaces_stop_and_saves_energy():
    g = _straight_graph_with_red_signal()
    for depart in range(0, 200, 7):  # 적색에 걸리는 출발 시각을 찾는다
        route = find_route(g, IONIQ5, "a", "c", 3, "eco",
                           signals=SIM, depart_s=float(depart))
        stopped = [leg for leg in route.legs if leg.wait_s > 0]
        if not stopped:
            continue
        advisories = compute_advisories(g, IONIQ5, route, float(depart), SIM)
        if not advisories:
            continue  # 대기가 너무 길어 30km/h 미만이 필요한 경우
        adv = advisories[0]
        assert adv.saved_wh > 0
        floor_kmh = min_advisory_ms(adv.original_kmh / 3.6) * 3.6
        assert floor_kmh <= adv.advisory_kmh < adv.original_kmh
        assert adv.leg_start <= adv.leg_end
        # 안내 속도로 스팬을 주행하면 정확히 녹색 시작에 도착해야 한다
        t_span_start = float(depart) + sum(l.time_s for l in route.legs[:adv.leg_start])
        t_arrive = t_span_start + adv.distance_m / (adv.advisory_kmh / 3.6)
        node = g.nodes[adv.node_id]
        assert SIM.wait_at(node, t_arrive + 0.5) == 0.0  # 녹색 직후
        return
    pytest.fail("탐색한 출발 시각 중 GLOSA 안내 가능한 정차가 없음")


def test_glosa_advisories_respect_floor_and_do_not_overlap(sample_graph):
    """안내 속도는 하한(원속도 50%, 최저 15km/h) 이상, 스팬은 겹치지 않아야 한다."""
    found = 0
    for start, end in [("n0_0", "n12_12"), ("n0_6", "n12_6"), ("n2_1", "n10_11")]:
        route = find_route(sample_graph, IONIQ5, start, end, 8, "eco", signals=SIM)
        spans: set[int] = set()
        for adv in compute_advisories(sample_graph, IONIQ5, route, 8 * 3600.0, SIM):
            floor_kmh = min_advisory_ms(adv.original_kmh / 3.6) * 3.6
            assert adv.advisory_kmh >= floor_kmh - 1e-6
            legs = set(range(adv.leg_start, adv.leg_end + 1))
            assert not spans & legs
            spans |= legs
            found += 1
    assert found > 0, "테스트 경로들에서 GLOSA 안내가 하나는 나와야 한다"
