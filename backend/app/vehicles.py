"""전기차 차종별 물리 파라미터 프리셋.

전비 계산에 필요한 최소한의 물리량만 정의한다. 값은 공개 제원과
일반적인 EV 파워트레인 효율 범위를 기반으로 한 근사치다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Vehicle:
    id: str
    name: str
    mass_kg: float          # 공차중량 + 탑승자(75kg) 근사
    drag_coeff: float       # 공기저항계수 Cd
    frontal_area_m2: float  # 전면 투영 면적 A
    rolling_coeff: float    # 구름저항계수 Crr
    drivetrain_eff: float   # 배터리→바퀴 효율 (모터+인버터+감속기)
    regen_eff: float        # 바퀴→배터리 회생제동 회수율
    aux_power_w: float      # 상시 보조 전력 (공조/전장, 연중 평균 근사)
    battery_kwh: float      # 배터리 용량 (잔여 주행거리 표시용)


PRESETS: dict[str, Vehicle] = {
    v.id: v
    for v in [
        Vehicle(
            id="ioniq5",
            name="현대 아이오닉 5 (롱레인지 2WD)",
            mass_kg=2020.0,
            drag_coeff=0.288,
            frontal_area_m2=2.68,
            rolling_coeff=0.010,
            drivetrain_eff=0.90,
            regen_eff=0.65,
            aux_power_w=500.0,
            battery_kwh=77.4,
        ),
        Vehicle(
            id="ev6",
            name="기아 EV6 (롱레인지 2WD)",
            mass_kg=1985.0,
            drag_coeff=0.28,
            frontal_area_m2=2.65,
            rolling_coeff=0.010,
            drivetrain_eff=0.90,
            regen_eff=0.65,
            aux_power_w=500.0,
            battery_kwh=77.4,
        ),
        Vehicle(
            id="model3",
            name="테슬라 모델 3 (RWD)",
            mass_kg=1840.0,
            drag_coeff=0.23,
            frontal_area_m2=2.22,
            rolling_coeff=0.009,
            drivetrain_eff=0.91,
            regen_eff=0.68,
            aux_power_w=450.0,
            battery_kwh=60.0,
        ),
        Vehicle(
            id="ray_ev",
            name="기아 레이 EV",
            mass_kg=1370.0,
            drag_coeff=0.34,
            frontal_area_m2=2.25,
            rolling_coeff=0.010,
            drivetrain_eff=0.89,
            regen_eff=0.60,
            aux_power_w=450.0,
            battery_kwh=35.2,
        ),
    ]
}

DEFAULT_VEHICLE_ID = "ioniq5"
