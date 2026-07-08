"""물리 기반 전기차 에너지 소비 모델.

도로 구간(링크) 하나를 일정 속도로 주행할 때의 배터리 에너지 소비를
주행저항 방정식으로 계산한다.

  바퀴 요구 에너지 E_wheel = (F_roll + F_aero) * d + m * g * Δh
    - 구름저항 F_roll = Crr * m * g * cosθ
    - 공기저항 F_aero = 0.5 * ρ * Cd * A * v²
    - 경사저항은 위치에너지 변화 m * g * Δh 로 정확히 반영

  배터리 에너지:
    E_wheel > 0 (구동): E_batt = E_wheel / η_drive
    E_wheel < 0 (내리막 회생): E_batt = E_wheel * η_regen  (음수 = 충전)

여기에 보조 전력(공조 등) P_aux * t 를 더한다.

신호등 정차는 별도 함수로: 정차 확률 p 에 대해
  - 감속으로 버리는 운동에너지 중 회생 못 하는 몫 + 재가속 손실
  - 대기 중 보조 전력
을 기대값으로 반영한다.
"""

import math

from .vehicles import Vehicle

GRAVITY = 9.81          # m/s²
AIR_DENSITY = 1.20      # kg/m³ (해수면 20°C 근사)


def edge_energy_wh(
    vehicle: Vehicle,
    distance_m: float,
    elevation_gain_m: float,
    speed_ms: float,
) -> float:
    """구간을 일정 속도로 주행할 때 배터리 소비 에너지(Wh). 음수면 회생 충전."""
    if distance_m <= 0:
        return 0.0
    grade = elevation_gain_m / distance_m
    cos_theta = 1.0 / math.sqrt(1.0 + grade * grade)

    f_roll = vehicle.rolling_coeff * vehicle.mass_kg * GRAVITY * cos_theta
    f_aero = 0.5 * AIR_DENSITY * vehicle.drag_coeff * vehicle.frontal_area_m2 * speed_ms**2
    e_wheel_j = (f_roll + f_aero) * distance_m + vehicle.mass_kg * GRAVITY * elevation_gain_m

    if e_wheel_j >= 0:
        e_batt_j = e_wheel_j / vehicle.drivetrain_eff
    else:
        e_batt_j = e_wheel_j * vehicle.regen_eff

    travel_time_s = distance_m / speed_ms
    e_batt_j += vehicle.aux_power_w * travel_time_s
    return e_batt_j / 3600.0


def signal_stop_energy_wh(
    vehicle: Vehicle,
    approach_speed_ms: float,
    stop_probability: float,
    avg_wait_s: float,
) -> float:
    """신호 정차의 기대 에너지 비용(Wh).

    정차 1회 = 운동에너지를 회생으로 일부 회수하며 감속한 뒤,
    같은 속도까지 재가속(구동 손실 포함) + 대기 중 보조 전력.
    순손실 = 0.5·m·v² · (1/η_drive − η_regen) + P_aux · 대기시간
    """
    if stop_probability <= 0:
        return 0.0
    kinetic_j = 0.5 * vehicle.mass_kg * approach_speed_ms**2
    net_loss_j = kinetic_j * (1.0 / vehicle.drivetrain_eff - vehicle.regen_eff)
    wait_aux_j = vehicle.aux_power_w * avg_wait_s
    return stop_probability * (net_loss_j + wait_aux_j) / 3600.0


def min_energy_per_meter_wh(vehicle: Vehicle) -> float:
    """평지·최적 조건에서의 미터당 최소 소비(Wh/m). A* 휴리스틱 하한용."""
    f_roll = vehicle.rolling_coeff * vehicle.mass_kg * GRAVITY
    return (f_roll / vehicle.drivetrain_eff) / 3600.0


def optimal_cruise_speed_ms(vehicle: Vehicle) -> float:
    """공기저항-보조전력(공회전 포함) 트레이드오프 기반 이론적 최소소비 순항속도.

    거리당 소비 = (구름저항 + 공기저항)/η_drive + P_aux/v. 구름저항은
    속도 무관이라 최적점에 영향이 없고, 공기저항(∝v²)과 보조전력 비용
    (시간당 일정 → 거리당 1/v)의 트레이드오프만으로 최소점이 정해진다:
    v* = (P_aux · η_drive / (ρ·Cd·A)) ** (1/3).

    이 모델의 단순화(구간·부하 무관 상수 효율)를 그대로 반영한 값이라
    제조사 공인연비 시험의 "최적속도"와는 다를 수 있다.
    """
    rho_cd_a = AIR_DENSITY * vehicle.drag_coeff * vehicle.frontal_area_m2
    return (vehicle.aux_power_w * vehicle.drivetrain_eff / rho_cd_a) ** (1 / 3)
