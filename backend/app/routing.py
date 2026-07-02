"""에너지(전비) 최적 / 최소 시간 경로 탐색.

전비 최적 모드의 핵심 문제: 내리막 회생제동 때문에 엣지 비용(Wh)이
음수가 될 수 있어 다익스트라를 그대로 못 쓴다. 고도 기반 전위 함수

  φ(n) = -η_regen · m · g · h(n) / 3600   (Wh)

로 비용을 보정하면 c'(u,v) = E(u,v) + φ(v) - φ(u) ≥ 0 이 보장된다.
(회생으로 회수 가능한 에너지는 위치에너지 낙차의 η_regen 배를 넘을 수
없기 때문.) 보정 비용으로 다익스트라를 돌리고, 실제 에너지·시간은
경로를 따라 별도로 합산한다.
"""

import heapq
from dataclasses import dataclass

from .energy import GRAVITY, edge_energy_wh, signal_stop_energy_wh
from .graph import Edge, Graph
from .traffic import expected_speed_ms, signal_profile
from .vehicles import Vehicle


@dataclass(frozen=True)
class RouteLeg:
    from_id: str
    to_id: str
    length_m: float
    road_class: str
    speed_kmh: float
    energy_wh: float
    time_s: float


@dataclass(frozen=True)
class RouteResult:
    mode: str                 # "eco" | "fastest"
    node_ids: list[str]
    legs: list[RouteLeg]
    total_energy_wh: float
    total_time_s: float
    total_distance_m: float


class NoRouteError(Exception):
    pass


def _edge_metrics(
    graph: Graph, vehicle: Vehicle, edge: Edge, hour: int
) -> tuple[float, float, float]:
    """엣지 하나의 (에너지 Wh, 시간 s, 속도 m/s). 도착 노드 신호 비용 포함."""
    u = graph.nodes[edge.from_id]
    v = graph.nodes[edge.to_id]
    speed = expected_speed_ms(edge.road_class, hour)

    energy = edge_energy_wh(vehicle, edge.length_m, v.elev_m - u.elev_m, speed)
    time_s = edge.length_m / speed

    sig = signal_profile(v.signal)
    energy += signal_stop_energy_wh(vehicle, speed, sig.stop_probability, sig.avg_wait_s)
    time_s += sig.stop_probability * sig.avg_wait_s
    return energy, time_s, speed


def _potential_wh(vehicle: Vehicle, elev_m: float) -> float:
    return -vehicle.regen_eff * vehicle.mass_kg * GRAVITY * elev_m / 3600.0


def find_route(
    graph: Graph,
    vehicle: Vehicle,
    start_id: str,
    goal_id: str,
    hour: int,
    mode: str,
) -> RouteResult:
    """mode="eco"(전비 최적) 또는 "fastest"(최소 시간) 경로 탐색."""
    if start_id not in graph.nodes or goal_id not in graph.nodes:
        raise NoRouteError("출발/도착 노드가 도로망에 없습니다")

    def cost_of(edge: Edge) -> float:
        energy, time_s, _ = _edge_metrics(graph, vehicle, edge, hour)
        if mode == "fastest":
            return time_s
        # 전위 보정으로 음수 비용 제거
        u_elev = graph.nodes[edge.from_id].elev_m
        v_elev = graph.nodes[edge.to_id].elev_m
        shifted = energy + _potential_wh(vehicle, v_elev) - _potential_wh(vehicle, u_elev)
        return max(shifted, 0.0)  # 부동소수점 오차 방어

    dist: dict[str, float] = {start_id: 0.0}
    prev: dict[str, Edge] = {}
    heap: list[tuple[float, str]] = [(0.0, start_id)]
    visited: set[str] = set()

    while heap:
        d, node_id = heapq.heappop(heap)
        if node_id in visited:
            continue
        if node_id == goal_id:
            break
        visited.add(node_id)
        for edge in graph.adjacency.get(node_id, []):
            if edge.to_id in visited:
                continue
            nd = d + cost_of(edge)
            if nd < dist.get(edge.to_id, float("inf")):
                dist[edge.to_id] = nd
                prev[edge.to_id] = edge
                heapq.heappush(heap, (nd, edge.to_id))

    if goal_id not in prev and goal_id != start_id:
        raise NoRouteError("경로를 찾을 수 없습니다")

    # 경로 복원 후 실제 에너지/시간 합산
    edges: list[Edge] = []
    cur = goal_id
    while cur != start_id:
        edge = prev[cur]
        edges.append(edge)
        cur = edge.from_id
    edges.reverse()

    legs: list[RouteLeg] = []
    for edge in edges:
        energy, time_s, speed = _edge_metrics(graph, vehicle, edge, hour)
        legs.append(
            RouteLeg(
                from_id=edge.from_id,
                to_id=edge.to_id,
                length_m=edge.length_m,
                road_class=edge.road_class,
                speed_kmh=round(speed * 3.6, 1),
                energy_wh=energy,
                time_s=time_s,
            )
        )

    return RouteResult(
        mode=mode,
        node_ids=[start_id] + [e.to_id for e in edges],
        legs=legs,
        total_energy_wh=sum(leg.energy_wh for leg in legs),
        total_time_s=sum(leg.time_s for leg in legs),
        total_distance_m=sum(leg.length_m for leg in legs),
    )
