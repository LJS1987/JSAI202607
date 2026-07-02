"""에너지(전비) 최적 / 최소 시간 경로 탐색.

신호 반영은 두 방식:
- 통계 모드(signals=None): 신호 유형별 정차 확률 × 기대 대기시간
- 시뮬레이터 모드(signals 지정): 교차로 도착 시각으로 현시를 확정 판정하는
  시간 의존(time-dependent) 탐색. 최소 시간 모드는 대기시간이 FIFO 성질을
  만족하므로 정확하고, 전비 모드는 에너지 우선 탐색에 도착 시각을 함께
  전파하는 근사(각 노드의 도착 시각을 최초 확정 라벨로 고정)다.

전비 모드의 핵심 문제: 내리막 회생제동 때문에 엣지 비용(Wh)이 음수가
될 수 있어 다익스트라를 그대로 못 쓴다. 고도 기반 전위 함수

  φ(n) = -η_regen · m · g · h(n) / 3600   (Wh)

로 비용을 보정하면 c'(u,v) = E(u,v) + φ(v) - φ(u) ≥ 0 이 보장된다.
(회생으로 회수 가능한 에너지는 위치에너지 낙차의 η_regen 배를 넘을 수
없기 때문.) 보정 비용으로 탐색하고 실제 에너지·시간은 별도 합산한다.
"""

import heapq
from dataclasses import dataclass

from .energy import GRAVITY, edge_energy_wh, signal_stop_energy_wh
from .graph import Edge, Graph
from .signals import SignalSimulator
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
    time_s: float   # 주행 + 신호 대기 포함
    wait_s: float   # 도착 노드 신호 대기 (통계 모드는 기대값)


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
    graph: Graph,
    vehicle: Vehicle,
    edge: Edge,
    hour: int,
    signals: SignalSimulator | None = None,
    t_depart_s: float = 0.0,
) -> tuple[float, float, float, float]:
    """엣지 하나의 (에너지 Wh, 시간 s, 속도 m/s, 대기 s).

    signals 가 있으면 t_depart_s(엣지 진입 시각)로부터 도착 시각을 계산해
    신호를 확정 판정하고, 없으면 통계적 기대값을 쓴다.
    """
    u = graph.nodes[edge.from_id]
    v = graph.nodes[edge.to_id]
    speed = expected_speed_ms(edge.road_class, hour)

    energy = edge_energy_wh(vehicle, edge.length_m, v.elev_m - u.elev_m, speed)
    drive_s = edge.length_m / speed

    if signals is not None:
        wait_s = signals.wait_at(v, t_depart_s + drive_s)
        if wait_s > 0:
            energy += signal_stop_energy_wh(vehicle, speed, 1.0, wait_s)
    else:
        sig = signal_profile(v.signal)
        wait_s = sig.stop_probability * sig.avg_wait_s
        energy += signal_stop_energy_wh(
            vehicle, speed, sig.stop_probability, sig.avg_wait_s
        )
    return energy, drive_s + wait_s, speed, wait_s


def _potential_wh(vehicle: Vehicle, elev_m: float) -> float:
    return -vehicle.regen_eff * vehicle.mass_kg * GRAVITY * elev_m / 3600.0


def find_route(
    graph: Graph,
    vehicle: Vehicle,
    start_id: str,
    goal_id: str,
    hour: int,
    mode: str,
    signals: SignalSimulator | None = None,
    depart_s: float | None = None,
) -> RouteResult:
    """mode="eco"(전비 최적) 또는 "fastest"(최소 시간) 경로 탐색."""
    if start_id not in graph.nodes or goal_id not in graph.nodes:
        raise NoRouteError("출발/도착 노드가 도로망에 없습니다")
    t0 = depart_s if depart_s is not None else hour * 3600.0

    def cost_of(edge: Edge, t_depart: float) -> tuple[float, float]:
        """(탐색 비용, 소요 시간). 전비 모드는 전위 보정 에너지."""
        energy, time_s, _, _ = _edge_metrics(
            graph, vehicle, edge, hour, signals, t_depart
        )
        if mode == "fastest":
            return time_s, time_s
        u_elev = graph.nodes[edge.from_id].elev_m
        v_elev = graph.nodes[edge.to_id].elev_m
        shifted = energy + _potential_wh(vehicle, v_elev) - _potential_wh(vehicle, u_elev)
        return max(shifted, 0.0), time_s  # 부동소수점 오차 방어

    dist: dict[str, float] = {start_id: 0.0}
    arrive: dict[str, float] = {start_id: t0}
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
        t_here = arrive[node_id]
        for edge in graph.adjacency.get(node_id, []):
            if edge.to_id in visited:
                continue
            cost, time_s = cost_of(edge, t_here)
            nd = d + cost
            if nd < dist.get(edge.to_id, float("inf")):
                dist[edge.to_id] = nd
                arrive[edge.to_id] = t_here + time_s
                prev[edge.to_id] = edge
                heapq.heappush(heap, (nd, edge.to_id))

    if goal_id not in prev and goal_id != start_id:
        raise NoRouteError("경로를 찾을 수 없습니다")

    # 경로 복원 후 실제 에너지/시간을 출발 시각부터 다시 합산
    edges: list[Edge] = []
    cur = goal_id
    while cur != start_id:
        edge = prev[cur]
        edges.append(edge)
        cur = edge.from_id
    edges.reverse()

    legs: list[RouteLeg] = []
    t = t0
    for edge in edges:
        energy, time_s, speed, wait_s = _edge_metrics(
            graph, vehicle, edge, hour, signals, t
        )
        legs.append(
            RouteLeg(
                from_id=edge.from_id,
                to_id=edge.to_id,
                length_m=edge.length_m,
                road_class=edge.road_class,
                speed_kmh=round(speed * 3.6, 1),
                energy_wh=energy,
                time_s=time_s,
                wait_s=wait_s,
            )
        )
        t += time_s

    return RouteResult(
        mode=mode,
        node_ids=[start_id] + [e.to_id for e in edges],
        legs=legs,
        total_energy_wh=sum(leg.energy_wh for leg in legs),
        total_time_s=sum(leg.time_s for leg in legs),
        total_distance_m=sum(leg.length_m for leg in legs),
    )
