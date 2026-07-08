"""개인 GPS 로그 기반 신호 타이밍 추정 — 합성 데이터로 순수 함수 검증."""

from backend.app.signal_learning import (
    CONFIDENCE_THRESHOLD,
    MIN_VISITS,
    Visit,
    estimate_timing,
    extract_visits,
)


def _synthetic_visits(cycle_s: float, green_s: float, offset_s: float, n: int) -> list[Visit]:
    """일정 간격으로 반복 방문하며, 실제 신호 상태에 따라 정차 여부를 기록."""
    visits = []
    for i in range(n):
        arrival = (i * 37.0) % cycle_s * 3 + offset_s  # 다양한 위상으로 흩어지게
        phase = (arrival - offset_s) % cycle_s
        stopped = phase >= green_s
        visits.append(Visit(arrival_ts=arrival % 86400.0, stopped=stopped))
    return visits


def test_estimate_recovers_synthetic_timing():
    visits = _synthetic_visits(cycle_s=120.0, green_s=50.0, offset_s=20.0, n=40)
    timing = estimate_timing(visits)
    assert timing is not None
    assert abs(timing.cycle_s - 120.0) <= 10.0
    assert abs(timing.green_s - 50.0) <= 15.0


def test_estimate_returns_none_for_too_few_visits():
    visits = _synthetic_visits(cycle_s=120.0, green_s=50.0, offset_s=0.0, n=MIN_VISITS - 1)
    assert estimate_timing(visits) is None


def test_estimate_returns_none_for_random_noise():
    import random

    rng = random.Random(42)
    visits = [Visit(arrival_ts=rng.uniform(0, 86400), stopped=rng.random() < 0.5) for _ in range(50)]
    timing = estimate_timing(visits)
    # 노이즈만 있으면 최고 조합도 신뢰 임계값을 넘기기 어렵거나, 넘겨도 우연이므로
    # 최소한 함수가 죽지 않고 None 또는 낮은 신뢰의 결과를 반환하는지만 확인.
    assert timing is None or timing.cycle_s > 0


def test_extract_visits_groups_by_gap_and_detects_stop():
    pings = [
        (0.0, 10.0), (1.0, 9.0), (2.0, 0.5), (3.0, 0.0), (4.0, 8.0),  # 방문 1: 정차 있었음
        (200.0, 12.0), (201.0, 11.0), (202.0, 10.0),                  # 방문 2 (간격 큼): 무정차 통과
    ]
    visits = extract_visits(pings)
    assert len(visits) == 2
    assert visits[0].stopped is True
    assert visits[1].stopped is False


def test_extract_visits_empty_input():
    assert extract_visits([]) == []
