"""교통 흐름·신호 모델.

실서비스에서는 국가교통정보센터(ITS) 소통정보 API나 서울 TOPIS 실시간
속도를 링크별로 조회해 대체한다(providers 모듈 참고). 여기서는 도로
등급별 제한속도에 시간대별 혼잡 계수를 곱한 '평소 교통 흐름' 프로파일을
기본값으로 제공한다.
"""

from dataclasses import dataclass

# 도로 등급별 (제한속도 km/h, 자유류 대비 신호밀도 보정 계수)
ROAD_CLASS_SPEED_KMH: dict[str, float] = {
    "motorway": 100.0,   # 도시고속도로 (올림픽대로 등)
    "trunk": 80.0,       # 간선 대로
    "primary": 60.0,     # 주요 간선
    "secondary": 50.0,   # 보조 간선
    "tertiary": 40.0,    # 집산도로
    "residential": 30.0, # 이면도로 (안전속도 5030)
}

# 시간대별 혼잡 계수(자유류 속도에 곱함). 서울 도심 평일 패턴 근사:
# 출근 07~09시, 퇴근 18~20시 정체, 심야 자유류.
_HOURLY_FLOW_FACTOR: list[float] = [
    0.95, 0.98, 1.00, 1.00, 1.00, 0.95,  # 00-05
    0.85, 0.55, 0.50, 0.65, 0.75, 0.72,  # 06-11
    0.70, 0.72, 0.72, 0.70, 0.65, 0.55,  # 12-17
    0.45, 0.50, 0.65, 0.78, 0.85, 0.92,  # 18-23
]

# 고속도로는 신호가 없어 정체 시에도 상대적으로 흐름이 좋음
_MOTORWAY_FLOOR = 0.55


@dataclass(frozen=True)
class SignalProfile:
    stop_probability: float  # 녹색 연동 없이 도착 시 정지할 확률
    avg_wait_s: float        # 정지 시 평균 대기 시간(적색 잔여의 기대값)


# 교차하는 도로 등급이 클수록 신호 주기가 길고 대기도 김
SIGNAL_PROFILES: dict[str, SignalProfile] = {
    "major": SignalProfile(stop_probability=0.55, avg_wait_s=45.0),  # 간선-간선
    "minor": SignalProfile(stop_probability=0.45, avg_wait_s=25.0),  # 간선-이면
    "none": SignalProfile(stop_probability=0.0, avg_wait_s=0.0),
}


def expected_speed_ms(road_class: str, hour: int) -> float:
    """도로 등급과 출발 시각(시)에 따른 기대 주행 속도(m/s)."""
    base_kmh = ROAD_CLASS_SPEED_KMH.get(road_class, 40.0)
    factor = _HOURLY_FLOW_FACTOR[hour % 24]
    if road_class == "motorway":
        factor = max(factor, _MOTORWAY_FLOOR)
    return base_kmh * factor / 3.6


def signal_profile(signal_type: str) -> SignalProfile:
    return SIGNAL_PROFILES.get(signal_type, SIGNAL_PROFILES["none"])
