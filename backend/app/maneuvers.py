"""경로 좌표열에서 회전 안내(턴바이턴)를 뽑아낸다.

노드 간 초기 방위각(bearing) 변화로 좌/우회전·완만한 회전·유턴을 판정한다.
도로명은 그래프에 없으므로(OSM `name` 태그 미저장) 방향·거리 위주의
일반적인 안내만 낸다 — `/nav`(frontend/nav.html) 턴바이턴 화면이 이 목록을
그대로 사용한다.
"""

import math
from dataclasses import dataclass

from .graph import Graph

# 이보다 작은 방향 변화는 직진으로 보고 이전 구간과 합친다
STRAIGHT_DEG = 20.0
# 이보다 크면 완만한 회전이 아니라 일반 좌/우회전으로 분류
NORMAL_TURN_DEG = 75.0
# 이보다 크면 유턴으로 분류
UTURN_DEG = 150.0


@dataclass(frozen=True)
class Maneuver:
    node_id: str
    lat: float
    lon: float
    type: str          # depart | straight_start(미사용) | slight_left | left |
                        # sharp_left | uturn | slight_right | right | sharp_right | arrive
    distance_m: float   # 직전 안내 지점부터 이 지점까지의 누적 주행거리
    cumulative_m: float  # 경로 출발점부터 이 지점까지의 누적 주행거리


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 지점 사이의 초기 방위각(진북 기준 시계방향, 0~360도)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(x, y)) % 360


def _classify_turn(turn_deg: float) -> str:
    """turn_deg: -180~180 정규화된 방향 변화. 양수=우회전, 음수=좌회전."""
    a = abs(turn_deg)
    if a >= UTURN_DEG:
        return "uturn"
    side = "right" if turn_deg > 0 else "left"
    if a >= NORMAL_TURN_DEG:
        return f"sharp_{side}" if a >= 110.0 else side
    return f"slight_{side}"


def build_maneuvers(
    graph: Graph, node_ids: list[str], leg_lengths_m: list[float]
) -> list[Maneuver]:
    """경로 노드ID 순열과 구간별 실제 주행거리로 턴바이턴 안내 목록을 만든다.

    직진(STRAIGHT_DEG 미만 방향 변화)은 별도 안내를 내지 않고 다음 회전
    지점까지 거리로 합쳐진다. 노드가 1개 이하면 빈 목록을 반환한다.
    """
    if len(node_ids) < 2:
        return []

    coords = [graph.nodes[n] for n in node_ids]
    maneuvers: list[Maneuver] = [
        Maneuver(node_ids[0], coords[0].lat, coords[0].lon, "depart", 0.0, 0.0)
    ]

    pending_m = 0.0
    cumulative_m = 0.0
    bearing_in = _bearing_deg(coords[0].lat, coords[0].lon, coords[1].lat, coords[1].lon)

    for i in range(1, len(node_ids) - 1):
        pending_m += leg_lengths_m[i - 1]
        cumulative_m += leg_lengths_m[i - 1]
        bearing_out = _bearing_deg(coords[i].lat, coords[i].lon, coords[i + 1].lat, coords[i + 1].lon)
        turn = ((bearing_out - bearing_in + 540) % 360) - 180

        if abs(turn) >= STRAIGHT_DEG:
            maneuvers.append(
                Maneuver(
                    node_ids[i], coords[i].lat, coords[i].lon,
                    _classify_turn(turn), round(pending_m, 1), round(cumulative_m, 1),
                )
            )
            pending_m = 0.0

        bearing_in = bearing_out

    pending_m += leg_lengths_m[-1]
    cumulative_m += leg_lengths_m[-1]
    maneuvers.append(
        Maneuver(node_ids[-1], coords[-1].lat, coords[-1].lon, "arrive", round(pending_m, 1), round(cumulative_m, 1))
    )
    return maneuvers
