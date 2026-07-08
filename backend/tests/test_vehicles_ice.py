"""가솔린/디젤 차량 프리셋과 일반화된 에너지 모델 검증."""

from backend.app.energy import edge_energy_wh, optimal_cruise_speed_ms
from backend.app.vehicles import PRESETS

GASOLINE = PRESETS["sonata_gas"]
DIESEL = PRESETS["santafe_diesel"]
EV = PRESETS["ioniq5"]


def test_ice_presets_have_fuel_fields():
    for v in (GASOLINE, DIESEL):
        assert v.fuel_type in ("gasoline", "diesel")
        assert v.regen_eff == 0.0
        assert v.tank_liters is not None and v.tank_liters > 0
        assert v.wh_per_liter is not None and v.wh_per_liter > 0
        assert v.battery_kwh is None


def test_ev_preset_unaffected_by_new_fields():
    assert EV.fuel_type == "ev"
    assert EV.battery_kwh is not None
    assert EV.tank_liters is None
    assert EV.wh_per_liter is None


def test_ice_downhill_costs_zero_not_negative():
    """회생이 없는 ICE(regen_eff=0)는 내리막에서 충전이 아니라 0으로 바닥친다."""
    wh = edge_energy_wh(GASOLINE, distance_m=1000.0, elevation_gain_m=-50.0, speed_ms=15.0)
    # aux_power_w 항은 남아있어 완전히 0은 아니지만, 회생으로 인한 음수(충전)는 없다.
    flat_wh = edge_energy_wh(GASOLINE, distance_m=1000.0, elevation_gain_m=0.0, speed_ms=15.0)
    assert wh < flat_wh  # 내리막이 평지보다는 적게 든다(구동 에너지 필요분이 줄어서)
    assert wh > 0  # 그러나 회생(음수) 처리는 없음


def test_optimal_cruise_speed_positive_and_finite():
    for v in (EV, GASOLINE, DIESEL):
        speed_ms = optimal_cruise_speed_ms(v)
        assert speed_ms > 0
        assert speed_ms < 60  # 200km/h 미만의 상식적 범위


def test_ice_has_higher_idle_cost_than_ev():
    """ICE 의 aux_power_w(공회전 포함)가 EV 보다 훨씬 크다."""
    assert GASOLINE.aux_power_w > EV.aux_power_w * 2
    assert DIESEL.aux_power_w > EV.aux_power_w * 2
