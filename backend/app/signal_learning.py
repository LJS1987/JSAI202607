"""개인 GPS 로그로부터 신호 타이밍(주기·녹색·오프셋) 추정.

tripdb 에 쌓인 (시각, 속도) 핑을 "방문"(교차로를 지나간 한 번의 사건) 단위로
묶고, 방문이 정차였는지 통과(그린)였는지를 신호는 하루 주기로 반복된다는
가정 아래 (cycle, green, offset) 그리드 서치로 설명해 가장 잘 맞는 조합을
고른다. 표본이 적거나 설명력이 낮으면 None을 반환해 기존 결정적 가상
시뮬레이션(signals.py) 폴백을 그대로 쓰게 한다.
"""

from dataclasses import dataclass

from .signals import SignalTiming

STOP_SPEED_MS = 1.0     # 이하면 "정차"로 간주
VISIT_GAP_S = 120.0     # 이 간격 이상 벌어지면 새 방문으로 분리
MIN_VISITS = 10         # 이보다 적으면 추정하지 않음(폴백 유지)
CONFIDENCE_THRESHOLD = 0.75  # 최고 점수 조합의 설명 적중률 하한

_CYCLE_CANDIDATES_S = range(60, 181, 10)
_OFFSET_STEP_S = 5
_GREEN_STEP_S = 10
_MIN_GREEN_S = 20
_MIN_RED_S = 10  # green_s 후보 상한 = cycle_s - _MIN_RED_S


@dataclass(frozen=True)
class Visit:
    arrival_ts: float  # 자정 기준 초(신호 하루주기 가정) — signals.py 와 동일 규약
    stopped: bool


def extract_visits(pings: list[tuple[float, float]]) -> list[Visit]:
    """시간순 (ts, speed_ms) 핑을 VISIT_GAP_S 간격으로 묶어 방문 단위로 분리.

    방문 내 최저속도가 STOP_SPEED_MS 이하면 정차(적색 대기), 아니면 통과(녹색).
    """
    if not pings:
        return []
    visits: list[Visit] = []
    window_start = 0
    for i in range(len(pings)):
        is_last = i == len(pings) - 1
        gap_exceeded = not is_last and pings[i + 1][0] - pings[i][0] >= VISIT_GAP_S
        if is_last or gap_exceeded:
            window = pings[window_start : i + 1]
            stopped = any(speed <= STOP_SPEED_MS for _, speed in window)
            visits.append(Visit(arrival_ts=window[0][0] % 86400.0, stopped=stopped))
            window_start = i + 1
    return visits


def estimate_timing(visits: list[Visit]) -> SignalTiming | None:
    """방문 목록을 가장 잘 설명하는 (cycle, green, offset) 을 그리드 서치로 추정.

    predicted_green = phase < green_s 가 "통과"를, 그 반대가 "정차"를
    예측한다고 보고, 예측과 실제 관측이 일치한 비율이 가장 높은 조합을
    고른다. 표본 부족(len(visits) < MIN_VISITS) 또는 최고 적중률이
    CONFIDENCE_THRESHOLD 미만이면 None(폴백 유지).
    """
    if len(visits) < MIN_VISITS:
        return None

    best: tuple[int, int, int] | None = None
    best_score = -1
    for cycle_s in _CYCLE_CANDIDATES_S:
        max_green = cycle_s - _MIN_RED_S
        if max_green <= _MIN_GREEN_S:
            continue
        for green_s in range(_MIN_GREEN_S, max_green, _GREEN_STEP_S):
            for offset_s in range(0, cycle_s, _OFFSET_STEP_S):
                score = 0
                for visit in visits:
                    phase = (visit.arrival_ts - offset_s) % cycle_s
                    predicted_green = phase < green_s
                    if predicted_green != visit.stopped:  # 예측과 관측 일치
                        score += 1
                if score > best_score:
                    best_score = score
                    best = (cycle_s, green_s, offset_s)

    if best is None or best_score / len(visits) < CONFIDENCE_THRESHOLD:
        return None
    cycle_s, green_s, offset_s = best
    return SignalTiming(cycle_s=float(cycle_s), green_s=float(green_s), offset_s=float(offset_s))
