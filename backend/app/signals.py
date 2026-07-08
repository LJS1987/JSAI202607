"""신호 시뮬레이터 — 결정적 가상 신호 현시.

실제 도시 신호처럼 교차로마다 (주기, 녹색시간, 오프셋)을 부여하고
"시각 t 에 이 교차로 신호가 무엇이며 잔여시간이 몇 초인가"를 결정적으로
계산한다. 실시간 신호 API(경찰청 UTIC 등)와 같은 질문에 답하는 구조라,
협약 후에는 이 클래스만 실데이터 구현으로 교체하면 경로 탐색과 GLOSA 는
그대로 동작한다.

단순화: 교차로 전체를 하나의 2현시(진행 녹색/적색)로 본다. 방향별 현시
분리는 실데이터 연동 단계에서 확장한다.
"""

import hashlib
from dataclasses import dataclass

from .graph import Node

# 신호 유형별 (주기 s, 녹색 비율) — 한국 도시 신호 운영 범위 근사
_TIMING_BASE = {
    "major": (160.0, 0.45),  # 간선 교차로: 긴 주기, 다현시로 녹색 몫 작음
    "minor": (120.0, 0.55),  # 이면 교차로
}


@dataclass(frozen=True)
class SignalTiming:
    cycle_s: float
    green_s: float
    offset_s: float


@dataclass(frozen=True)
class SignalState:
    color: str        # "green" | "red"
    remaining_s: float  # 현재 색이 유지되는 남은 시간


class SignalSimulator:
    """노드 ID 기반 결정적 가상 신호. 같은 입력이면 항상 같은 현시.

    real_timings 를 주면 해당 노드는 가상 시뮬레이션 대신 실측 타이밍을
    사용한다 (경찰청 신호운영 데이터 연동, providers.fetch_police_signal_timings
    참고). 실데이터가 없는 노드는 기존 결정적 시뮬레이션으로 폴백한다.
    """

    def __init__(self, real_timings: dict[str, SignalTiming] | None = None):
        self.real_timings = real_timings or {}

    def timing_for(self, node: Node) -> SignalTiming | None:
        real = self.real_timings.get(node.id)
        if real is not None:
            return real
        if node.signal not in _TIMING_BASE:
            return None
        cycle, green_ratio = _TIMING_BASE[node.signal]
        # 오프셋은 노드 ID 해시로 결정 — 교차로마다 다르지만 재현 가능
        digest = hashlib.md5(node.id.encode()).digest()
        offset = (int.from_bytes(digest[:4], "big") % int(cycle * 10)) / 10.0
        return SignalTiming(cycle_s=cycle, green_s=cycle * green_ratio, offset_s=offset)

    def state_at(self, node: Node, t_s: float) -> SignalState | None:
        """시각 t(자정 기준 초)의 신호 상태. 신호 없는 노드는 None."""
        timing = self.timing_for(node)
        if timing is None:
            return None
        phase = (t_s - timing.offset_s) % timing.cycle_s
        if phase < timing.green_s:
            return SignalState("green", timing.green_s - phase)
        return SignalState("red", timing.cycle_s - phase)

    def wait_at(self, node: Node, t_arrive_s: float) -> float:
        """t_arrive 에 도착했을 때 대기 시간(초). 녹색이면 0."""
        state = self.state_at(node, t_arrive_s)
        if state is None or state.color == "green":
            return 0.0
        return state.remaining_s
