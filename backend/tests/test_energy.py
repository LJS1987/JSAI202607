"""에너지 모델 물리적 타당성 검증."""

import pytest

from backend.app.energy import edge_energy_wh, signal_stop_energy_wh
from backend.app.vehicles import PRESETS

IONIQ5 = PRESETS["ioniq5"]


def test_flat_consumption_is_realistic():
    """평지 60km/h 정속(정차 없는 이상 조건): 공인 전비(≈5km/kWh)보다 좋고
    물리적으로 무리한 값(>11km/kWh)은 아니어야 한다."""
    wh = edge_energy_wh(IONIQ5, distance_m=10_000, elevation_gain_m=0, speed_ms=60 / 3.6)
    km_per_kwh = 10.0 / (wh / 1000)
    assert 5.0 < km_per_kwh < 11.0


def test_uphill_costs_more_than_flat():
    flat = edge_energy_wh(IONIQ5, 1000, 0, 50 / 3.6)
    uphill = edge_energy_wh(IONIQ5, 1000, 30, 50 / 3.6)
    assert uphill > flat


def test_downhill_can_regenerate():
    """급한 내리막에서는 순 에너지가 음수(충전)여야 한다."""
    wh = edge_energy_wh(IONIQ5, 1000, -60, 40 / 3.6)
    assert wh < 0


def test_regen_never_exceeds_potential_energy_bound():
    """회생 회수량은 위치에너지 낙차 × η_regen 을 넘을 수 없다 (전위 보정의 전제)."""
    drop = 60.0
    wh = edge_energy_wh(IONIQ5, 1000, -drop, 40 / 3.6)
    bound = -IONIQ5.regen_eff * IONIQ5.mass_kg * 9.81 * drop / 3600
    assert wh >= bound


def test_higher_speed_increases_aero_cost():
    slow = edge_energy_wh(IONIQ5, 1000, 0, 50 / 3.6)
    fast = edge_energy_wh(IONIQ5, 1000, 0, 100 / 3.6)
    assert fast > slow


def test_signal_stop_energy_scales_with_probability():
    v = 60 / 3.6
    none = signal_stop_energy_wh(IONIQ5, v, 0.0, 45)
    half = signal_stop_energy_wh(IONIQ5, v, 0.5, 45)
    full = signal_stop_energy_wh(IONIQ5, v, 1.0, 45)
    assert none == 0
    assert half == pytest.approx(full / 2)
    assert full > 0
