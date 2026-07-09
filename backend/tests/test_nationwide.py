"""전국 어디서나 경로 계산: 지역 그래프 동적 확보(get_graph_for_route)와
합성 격자망 폴백(build_grid_graph), 평일/주말 교통 패턴 검증.

이 샌드박스에는 osmnx 가 없어(README 참고) OSM 실도로망 경로는 항상 합성
격자망 폴백을 타게 된다 — 그 폴백 경로 자체가 "오프라인에서도 전국 어디서나
동작"의 핵심이라 여기서 직접 검증한다.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.graph import Graph
from backend.app.sample_data import build_grid_graph
from backend.app.traffic import expected_speed_ms

client = TestClient(main.app)

# 강남 샘플 도로망(37.490~37.530, 127.020~127.070) 밖의 대전 유성구 좌표
DAEJEON_START = {"lat": 36.369552970085145, "lon": 127.33426809310915}
DAEJEON_END = {"lat": 36.3729556407402, "lon": 127.34218597412111}


@pytest.fixture(autouse=True)
def _isolate_region_cache():
    """지역 그래프 캐시가 테스트 간 상태를 공유하지 않도록 매번 비운다."""
    main._region_graph_cache.clear()
    yield
    main._region_graph_cache.clear()


def test_build_grid_graph_works_for_arbitrary_center():
    """강남이 아닌 임의 좌표 범위에서도 유효한 연결 격자망을 만든다."""
    raw = build_grid_graph(36.35, 36.40, 127.31, 127.36, grid_n=5)
    graph = Graph.from_dict(raw)
    assert len(graph.nodes) == 25
    node = next(iter(graph.nodes.values()))
    assert 36.35 <= node.lat <= 36.40
    assert 127.31 <= node.lon <= 127.36
    assert any(adj for adj in graph.adjacency.values())


def test_route_outside_default_graph_falls_back_to_synthetic_network():
    """대전 좌표는 기본(강남) 그래프 밖이라 합성 격자망 폴백으로 200이 나와야 한다."""
    resp = client.get("/api/route", params={
        "start_lat": DAEJEON_START["lat"], "start_lon": DAEJEON_START["lon"],
        "end_lat": DAEJEON_END["lat"], "end_lon": DAEJEON_END["lon"],
        "vehicle": "ioniq5",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert any("근사 격자망" in w for w in data["warnings"])
    assert data["eco"]["distance_km"] > 0


def test_gangnam_route_still_uses_default_graph_unchanged():
    """강남 좌표는 여전히 기본 그래프를 그대로 써서 합성망 경고가 없어야 한다."""
    resp = client.get("/api/route", params={
        "start_lat": 37.4979, "start_lon": 127.0276,
        "end_lat": 37.5115, "end_lon": 127.0595,
        "vehicle": "ioniq5",
    })
    assert resp.status_code == 200
    assert not any("근사 격자망" in w for w in resp.json()["warnings"])


def test_long_domestic_trip_still_succeeds():
    """서울↔부산(~325km) 같은 국내 장거리는 600km 상한 이내라 그대로 계산돼야 한다."""
    resp = client.get("/api/route", params={
        "start_lat": 37.5665, "start_lon": 126.9780,   # 서울
        "end_lat": 35.1796, "end_lon": 129.0756,        # 부산
        "vehicle": "ioniq5",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert any("근사 격자망" in w for w in data["warnings"])
    assert data["eco"]["distance_km"] > 200  # 직선 325km 구간이니 도로 거리도 상당히 길어야 함


def test_trip_beyond_max_distance_is_rejected():
    """국경을 넘는 등 이 프로토타입 처리 범위(기본 600km)를 넘는 초장거리는 400."""
    resp = client.get("/api/route", params={
        "start_lat": 37.5665, "start_lon": 126.9780,    # 서울
        "end_lat": 35.6762, "end_lon": 139.6503,         # 도쿄 (약 1160km)
        "vehicle": "ioniq5",
    })
    assert resp.status_code == 400
    assert "km" in resp.json()["detail"]


def test_weekend_profile_has_less_severe_rush_hour_than_weekday():
    """평일 출근시간대(8시) 속도가 같은 시각의 주말보다 느려야 한다(피크가 뚜렷하므로)."""
    weekday_speed = expected_speed_ms("primary", 8, is_weekend=False)
    weekend_speed = expected_speed_ms("primary", 8, is_weekend=True)
    assert weekday_speed < weekend_speed


def test_expected_speed_ms_defaults_to_weekday_profile():
    """is_weekend 생략 시 기존 평일 프로파일과 동일해야 회귀가 없다."""
    assert expected_speed_ms("primary", 8) == expected_speed_ms("primary", 8, is_weekend=False)


def test_grid_n_for_span_scales_up_but_is_capped():
    """장거리일수록 합성 격자 해상도를 높이되, 상한(_SYNTHETIC_GRID_N_MAX)을 넘지 않는다."""
    small = main._grid_n_for_span(5.0)
    large = main._grid_n_for_span(300.0)
    huge = main._grid_n_for_span(5000.0)
    assert small == main.GRID_N  # 최소값은 기존 강남 격자 해상도
    assert small < large <= main._SYNTHETIC_GRID_N_MAX
    assert huge == main._SYNTHETIC_GRID_N_MAX
