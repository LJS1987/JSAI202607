"""전기차·내연기관 차종별 물리 파라미터 프리셋.

전비/연비 계산에 필요한 최소한의 물리량만 정의한다. 값은 공개 제원과
일반적인 파워트레인 효율 범위를 기반으로 한 근사치다.

내연기관(가솔린/디젤)은 EV와 같은 주행저항 방정식(energy.py)을 그대로
쓰되 다음과 같이 재해석한다:
  - drivetrain_eff: EV=배터리→바퀴 효율, ICE=탱크→바퀴 종합효율
    (엔진 열효율 × 구동계, 상수 근사)
  - regen_eff: ICE 는 0.0 — 회생이 없고, 내리막에서는 연료분사를 끊는
    근사(에너지 모델상 e_wheel<0 구간이 자동으로 0 처리됨)
  - aux_power_w: EV=상시 전장, ICE=상시 전장 + 공회전 연료소비 환산(W)
    (정차 중 아이들 연료소비가 EV의 보조전력보다 훨씬 크다는 것을 반영)
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
    drivetrain_eff: float   # 구동계 종합효율 (EV: 모터+인버터+감속기, ICE: 열효율×구동계)
    regen_eff: float        # 회생제동 회수율 (ICE 는 0.0)
    aux_power_w: float      # 상시 보조 전력 (EV: 공조/전장, ICE: 전장+공회전 연료소비 환산)
    fuel_type: str = "ev"              # "ev" | "gasoline" | "diesel"
    battery_kwh: float | None = None   # EV 전용 — 배터리 용량 (잔여 주행거리 표시용)
    tank_liters: float | None = None   # ICE 전용 — 연료탱크 용량 (표시용)
    wh_per_liter: float | None = None  # ICE 전용 — 연료 발열량 환산(LHV 기준, 표시용 변환 상수)


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
        Vehicle(
            id="sonata_gas",
            name="현대 쏘나타 2.5 (가솔린)",
            mass_kg=1550.0,
            drag_coeff=0.27,
            frontal_area_m2=2.30,
            rolling_coeff=0.010,
            drivetrain_eff=0.25,   # 엔진 열효율×구동계 종합 근사(도심~복합 평균)
            regen_eff=0.0,
            aux_power_w=1900.0,    # 전장(~200W) + 공회전 연료소비(~0.7L/h) 환산
            fuel_type="gasoline",
            tank_liters=50.0,
            wh_per_liter=8900.0,   # 가솔린 LHV 약 32.0 MJ/L ÷ 3.6
        ),
        Vehicle(
            id="santafe_diesel",
            name="현대 싼타페 2.2 (디젤)",
            mass_kg=1900.0,
            drag_coeff=0.33,
            frontal_area_m2=2.65,
            rolling_coeff=0.011,
            drivetrain_eff=0.32,   # 디젤은 가솔린 대비 열효율이 높음
            regen_eff=0.0,
            aux_power_w=2500.0,    # 전장(~200W) + 공회전 연료소비(~0.8L/h) 환산
            fuel_type="diesel",
            tank_liters=67.0,
            wh_per_liter=10500.0,  # 디젤 LHV 약 37.8 MJ/L ÷ 3.6
        ),
    ]
}

DEFAULT_VEHICLE_ID = "ioniq5"
