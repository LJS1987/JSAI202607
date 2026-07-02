"""GLOSA (Green Light Optimal Speed Advisory) — 녹색 신호 최적 속도 안내.

경로의 신호 정차 지점마다 "미리 감속해서 녹색 시작 시각에 정확히 도착"
하는 권장 속도를 계산한다. 이 경우 교차로 통과 시각이 원래 정차 후
출발하던 시각과 동일하므로 하류 구간 타이밍은 변하지 않고, 정차 1회의
순손실 ½mv²(1/η_drive − η_regen) 만 사라진다.

한 구간 감속만으로 권장 속도가 최저 실용 속도(30km/h) 아래로 내려가면
실제 GLOSA 처럼 접근 구간을 앞으로 확장(최대 MAX_SPAN_LEGS 구간)해
더 긴 거리에 감속을 분산한다. 확장 시 중간 신호들이 새 도착 시각에도
녹색인지 확인한다.
"""

from dataclasses import dataclass

from .energy import edge_energy_wh, signal_stop_energy_wh
from .graph import Graph
from .routing import RouteResult
from .signals import SignalSimulator
from .vehicles import Vehicle

# 안내 속도 하한: 교통류 방해 방지. 원속도의 50% 이상, 절대 최저 15km/h
MIN_ADVISORY_ABS_MS = 15.0 / 3.6
MIN_ADVISORY_RATIO = 0.5
MAX_SPAN_LEGS = 3  # 감속을 분산할 최대 접근 구간 수


def min_advisory_ms(cruise_ms: float) -> float:
    return max(MIN_ADVISORY_ABS_MS, MIN_ADVISORY_RATIO * cruise_ms)


@dataclass(frozen=True)
class Advisory:
    node_id: str          # 정차를 회피하는 신호 교차로
    leg_start: int        # 감속 시작 구간 (경로 내 번호, inclusive)
    leg_end: int          # 신호 교차로로 끝나는 구간 (inclusive)
    distance_m: float     # 감속 적용 총 거리
    original_kmh: float   # 정차 구간의 원래 속도
    advisory_kmh: float
    wait_avoided_s: float
    saved_wh: float


def _leg_energy(graph: Graph, vehicle: Vehicle, leg, speed_ms: float) -> float:
    u = graph.nodes[leg.from_id]
    v = graph.nodes[leg.to_id]
    return edge_energy_wh(vehicle, leg.length_m, v.elev_m - u.elev_m, speed_ms)


def compute_advisories(
    graph: Graph,
    vehicle: Vehicle,
    route: RouteResult,
    depart_s: float,
    signals: SignalSimulator,
) -> list[Advisory]:
    """경로의 정차마다 실행 가능한 GLOSA 안내를 계산한다.

    route 는 signals 시뮬레이터 모드로 계산된 결과여야 한다(leg.wait_s 가
    확정 대기시간). 안내를 따라도 신호 통과 시각이 같으므로 안내끼리
    간섭하지 않으며, 스팬이 겹치지 않게 배정한다.
    """
    leg_start_t: list[float] = []
    t = depart_s
    for leg in route.legs:
        leg_start_t.append(t)
        t += leg.time_s

    advisories: list[Advisory] = []
    claimed: set[int] = set()  # 이미 다른 안내 스팬에 포함된 구간

    for i, leg in enumerate(route.legs):
        if leg.wait_s <= 0 or i in claimed:
            continue
        speed_i = leg.speed_kmh / 3.6
        floor_ms = min_advisory_ms(speed_i)
        green_start_t = leg_start_t[i] + leg.length_m / speed_i + leg.wait_s

        for j in range(i, max(i - MAX_SPAN_LEGS, -1), -1):
            if j in claimed or (j < i and route.legs[j].wait_s > 0):
                break  # 스팬 겹침 또는 중간에 다른 정차 — 더 못 늘림
            span = route.legs[j : i + 1]
            dist = sum(l.length_m for l in span)
            v_adv = dist / (green_start_t - leg_start_t[j])
            if v_adv < floor_ms:
                continue  # 너무 느림 → 접근 구간을 더 확장해 본다

            # 감속으로 도착 시각이 바뀌는 중간 신호들이 녹색인지 확인
            d_cum, feasible = 0.0, True
            for k in range(j, i):
                d_cum += route.legs[k].length_m
                node = graph.nodes[route.legs[k].to_id]
                if node.signal != "none" and signals.wait_at(
                    node, leg_start_t[j] + d_cum / v_adv
                ) > 0:
                    feasible = False
                    break
            if not feasible:
                continue

            e_original = sum(
                _leg_energy(graph, vehicle, l, l.speed_kmh / 3.6) for l in span
            ) + signal_stop_energy_wh(vehicle, speed_i, 1.0, leg.wait_s)
            e_advised = sum(_leg_energy(graph, vehicle, l, v_adv) for l in span)
            saved = e_original - e_advised
            if saved <= 0:
                break

            advisories.append(
                Advisory(
                    node_id=leg.to_id,
                    leg_start=j,
                    leg_end=i,
                    distance_m=round(dist, 1),
                    original_kmh=leg.speed_kmh,
                    advisory_kmh=round(v_adv * 3.6, 1),
                    wait_avoided_s=round(leg.wait_s, 1),
                    saved_wh=round(saved, 1),
                )
            )
            claimed.update(range(j, i + 1))
            break

    return advisories
