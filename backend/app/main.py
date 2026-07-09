"""전기차 전비 최적 내비게이션 API 서버.

실행:
    uvicorn backend.app.main:app --reload
이후 http://localhost:8000 에서 지도 UI 사용.
"""

import asyncio
import logging
import math
import os
import time
from collections import OrderedDict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import tripdb
from . import providers
from .energy import optimal_cruise_speed_ms
from .glosa import compute_advisories
from .graph import Graph, haversine_m
from .maneuvers import build_maneuvers
from .places import search_local
from .providers import fetch_police_signal_timings, search_kakao_places
from .regions import REGIONS
from .routing import NoRouteError, RouteResult, find_route
from .sample_data import GRID_N, build_grid_graph, ensure_sample_graph
from .signal_learning import estimate_timing, extract_visits
from .signals import SignalSimulator, SignalTiming
from .traffic import ROAD_CLASS_SPEED_KMH, normalize_road_class
from .vehicles import DEFAULT_VEHICLE_ID, PRESETS, Vehicle

logger = logging.getLogger(__name__)

# 요청 지점이 도로망에서 이보다 멀면 커버리지 밖 경고를 붙인다
COVERAGE_WARN_M = 1_500.0
# 개인 GPS 핑이 신호 노드에서 이보다 멀면 기록하지 않는다
MAX_PING_LOG_DIST_M = 40.0
# 출발·도착 직선거리가 이보다 멀면 거절한다 — 실질적인 안전판으로만 쓴다
# (남한 대각선 최장거리가 약 480km라 600km면 국내 어디서나 충분히 커버된다).
# 이보다 훨씬 멀면 bbox 가 국가 단위로 커져 OSM 다운로드·격자망 계산이
# 비현실적으로 무거워지므로 그 지점만 거절한다. 환경변수로 조절 가능.
MAX_TRIP_KM = float(os.environ.get("EV_NAV_MAX_TRIP_KM", "600"))
# 이보다 먼 거리는 OSM bbox 요청을 "주요 도로만"(고속도로·간선)으로 좁혀
# Overpass 쿼리 크기를 억제한다 — 장거리는 어차피 간선 위주로 다니므로
# 이면도로까지 받을 필요가 적다는 점도 반영한다.
HIGHWAY_ONLY_THRESHOLD_KM = 40.0
# 합성 격자망 폴백의 셀 간격 목표(km) — 이보다 넓은 지역은 격자 해상도(grid_n)를
# 늘려 근사 품질을 유지하되, 계산량 폭주를 막기 위해 grid_n 상한을 둔다.
_SYNTHETIC_TARGET_CELL_KM = 4.0
_SYNTHETIC_GRID_N_MAX = 60
# 지역 그래프 캐시 최대 보관 개수 (LRU)
_REGION_CACHE_MAX = 16

ROOT = Path(__file__).resolve().parents[2]
# EV_NAV_GRAPH 로 실지도(OSM) 그래프 JSON 을 지정할 수 있다 (scripts/build_osm_graph.py 참고).
# 지정하지 않으면 기본 샘플 그래프(강남 일대)를 쓰되, /api/route 는 이 범위
# 밖의 출발/도착에 대해 get_graph_for_route() 로 그때그때 해당 지역 그래프를
# 동적으로 확보한다(OSM bbox 우선, 실패 시 합성 격자망 폴백).
GRAPH_PATH = Path(os.environ.get("EV_NAV_GRAPH", ROOT / "backend" / "data" / "sample_graph.json"))
TRIP_DB_PATH = ROOT / "backend" / "data" / "trips.db"
FRONTEND_DIR = ROOT / "frontend"

app = FastAPI(title="AI 내비게이션", version="0.1.0")

_graph: Graph | None = None
_region_graph_cache: "OrderedDict[tuple[float, float, float, float], tuple[Graph, bool]]" = OrderedDict()


def get_graph() -> Graph:
    global _graph
    if _graph is None:
        if not GRAPH_PATH.exists():
            if "EV_NAV_GRAPH" in os.environ:
                raise RuntimeError(f"EV_NAV_GRAPH 파일이 없습니다: {GRAPH_PATH}")
            ensure_sample_graph(GRAPH_PATH)
        _graph = Graph.from_json(GRAPH_PATH)
    return _graph


def _covers(graph: Graph, lat: float, lon: float) -> bool:
    """graph 에 (lat, lon) 근처(COVERAGE_WARN_M 이내) 도로가 있는지."""
    node = graph.nearest_node(lat, lon)
    return haversine_m(lat, lon, node.lat, node.lon) <= COVERAGE_WARN_M


def _padded_bbox(
    s_lat: float, s_lon: float, e_lat: float, e_lon: float
) -> tuple[float, float, float, float]:
    """출발·도착을 감싸는 bbox에 여유 패딩을 둔다 (min_lat, max_lat, min_lon, max_lon)."""
    lat_span = abs(e_lat - s_lat)
    lon_span = abs(e_lon - s_lon)
    pad = max(0.02, 0.15 * max(lat_span, lon_span))
    return (
        min(s_lat, e_lat) - pad, max(s_lat, e_lat) + pad,
        min(s_lon, e_lon) - pad, max(s_lon, e_lon) + pad,
    )


def _bbox_span_km(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> float:
    lat_km = (max_lat - min_lat) * 111.32
    lon_km = (max_lon - min_lon) * 111.32 * math.cos(math.radians((min_lat + max_lat) / 2))
    return max(lat_km, lon_km)


def _grid_n_for_span(span_km: float) -> int:
    """장거리일수록 합성 격자망 해상도를 높여 셀 간격을 ~_SYNTHETIC_TARGET_CELL_KM 근처로 유지.

    grid_n 이 커질수록(최대 _SYNTHETIC_GRID_N_MAX) 탐색 비용도 커지므로 상한을 둔다.
    """
    n = round(span_km / _SYNTHETIC_TARGET_CELL_KM) + 1
    return max(GRID_N, min(n, _SYNTHETIC_GRID_N_MAX))


def get_graph_for_route(
    s_lat: float, s_lon: float, e_lat: float, e_lon: float
) -> tuple[Graph, bool]:
    """출발/도착 좌표를 커버하는 그래프를 확보한다. (graph, is_synthetic) 반환.

    1. EV_NAV_GRAPH 를 명시적으로 지정했으면 항상 그 그래프를 쓴다(기존 동작 보존).
    2. 아니면 기본 샘플 그래프(강남 일대)가 두 지점을 모두 커버하면 그대로 재사용
       — 강남 좌표에 대한 기존 테스트·동작은 완전히 그대로다.
    3. 그 밖의 지역은 두 지점을 감싸는 bbox 로 OSM 실도로망을 그때그때 내려받는다
       (providers.load_osm_graph_bbox). HIGHWAY_ONLY_THRESHOLD_KM 을 넘는 장거리는
       고속도로·간선만 받아 Overpass 쿼리 크기를 억제한다. 실패(osmnx 미설치·
       오프라인·Overpass 오류)하면 같은 bbox 를 감싸는 합성 격자망
       (sample_data.build_grid_graph)으로 폴백해 인터넷이 없어도, 그리고 초장거리
       라도 항상 결과를 낸다 — 격자 해상도는 거리에 비례해 늘려 근사 품질을 유지한다.
    4. 직선거리가 MAX_TRIP_KM(기본 600km, 국내 최장 거리보다 넉넉함)을 넘으면
       그 지점만 거절한다 — bbox 가 국가/대륙 단위로 커져 다운로드·계산이
       비현실적으로 무거워지는 것을 막는 안전판일 뿐, 국내 장거리는 모두 지원한다.

    지역 그래프는 bbox 를 0.01도(~1km) 격자로 반올림한 키로 캐싱한다.
    """
    if "EV_NAV_GRAPH" in os.environ:
        return get_graph(), False

    default = get_graph()
    if _covers(default, s_lat, s_lon) and _covers(default, e_lat, e_lon):
        return default, False

    trip_km = haversine_m(s_lat, s_lon, e_lat, e_lon) / 1000.0
    if trip_km > MAX_TRIP_KM:
        raise HTTPException(
            400,
            f"출발·도착 직선거리가 {trip_km:.0f}km 로 이 프로토타입의 처리 범위"
            f"(최대 {MAX_TRIP_KM:.0f}km)를 넘었습니다",
        )

    min_lat, max_lat, min_lon, max_lon = _padded_bbox(s_lat, s_lon, e_lat, e_lon)
    key = (round(min_lat, 2), round(max_lat, 2), round(min_lon, 2), round(max_lon, 2))
    cached = _region_graph_cache.get(key)
    if cached is not None:
        _region_graph_cache.move_to_end(key)
        return cached

    highway_only = trip_km > HIGHWAY_ONLY_THRESHOLD_KM
    try:
        graph = providers.load_osm_graph_bbox(
            min_lat, min_lon, max_lat, max_lon, highway_only=highway_only,
        )
        is_synthetic = False
    except Exception:
        logger.info(
            "OSM 실도로망을 가져오지 못해 합성 격자망으로 폴백합니다 (bbox=%s)",
            key, exc_info=True,
        )
        grid_n = _grid_n_for_span(_bbox_span_km(min_lat, max_lat, min_lon, max_lon))
        graph = Graph.from_dict(build_grid_graph(min_lat, max_lat, min_lon, max_lon, grid_n))
        is_synthetic = True

    _region_graph_cache[key] = (graph, is_synthetic)
    _region_graph_cache.move_to_end(key)
    if len(_region_graph_cache) > _REGION_CACHE_MAX:
        _region_graph_cache.popitem(last=False)
    return graph, is_synthetic


_real_timings: dict[str, SignalTiming] | None = None


def get_real_timings(graph: Graph) -> dict[str, SignalTiming]:
    """경찰청 신호운영 데이터(POLICE_API_KEY + POLICE_REGION_CODE 설정 시)를 1회 조회해 캐시한다.

    미설정이거나 조회 실패 시 빈 dict — SignalSimulator 는 결정적 가상
    시뮬레이션으로 그대로 폴백한다 (providers.fetch_police_signal_timings 참고).
    """
    global _real_timings
    if _real_timings is None:
        region_code = os.environ.get("POLICE_REGION_CODE")
        if not os.environ.get("POLICE_API_KEY") or not region_code:
            _real_timings = {}
        else:
            try:
                _real_timings = asyncio.run(fetch_police_signal_timings(graph, region_code))
            except Exception:
                logger.warning("경찰청 신호운영 데이터 조회 실패 — 시뮬레이터로 폴백", exc_info=True)
                _real_timings = {}
    return _real_timings


_trip_conn = None


def get_trip_conn():
    global _trip_conn
    if _trip_conn is None:
        TRIP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _trip_conn = tripdb.connect(TRIP_DB_PATH)
    return _trip_conn


_learned_timings: dict[str, SignalTiming] | None = None


def get_learned_timings(graph: Graph, force: bool = False) -> dict[str, SignalTiming]:
    """개인 GPS 로그(tripdb)로 추정한 신호 타이밍. 표본 부족 시 해당 노드는 빠진다.

    경찰청 실측과 달리 계속 쌓이는 데이터라 force=True 로 강제 재계산할 수
    있다(POST /api/trip/relearn).
    """
    global _learned_timings
    if _learned_timings is None or force:
        conn = get_trip_conn()
        learned: dict[str, SignalTiming] = {}
        for node_id in tripdb.distinct_nodes(conn):
            visits = extract_visits(tripdb.pings_for_node(conn, node_id))
            timing = estimate_timing(visits)
            if timing is not None:
                learned[node_id] = timing
        _learned_timings = learned
    return _learned_timings


def _merged_timings(graph: Graph) -> dict[str, SignalTiming]:
    """우선순위: 경찰청 실측 > 개인 학습 추정 > (미해당 노드는) 가상 시뮬레이션."""
    return {**get_learned_timings(graph), **get_real_timings(graph)}


def _vehicle_payload(v: Vehicle) -> dict:
    payload = {
        "id": v.id,
        "name": v.name,
        "fuel_type": v.fuel_type,
        "eco_speed_kmh": round(optimal_cruise_speed_ms(v) * 3.6, 1),
    }
    if v.fuel_type == "ev":
        payload["battery_kwh"] = v.battery_kwh
    else:
        payload["tank_liters"] = v.tank_liters
    return payload


def _route_payload(graph: Graph, vehicle: Vehicle, result: RouteResult) -> dict:
    coords = [
        {"lat": graph.nodes[nid].lat, "lon": graph.nodes[nid].lon}
        for nid in result.node_ids
    ]
    eco_speed_kmh = optimal_cruise_speed_ms(vehicle) * 3.6
    maneuvers = build_maneuvers(graph, result.node_ids, [leg.length_m for leg in result.legs])
    payload = {
        "mode": result.mode,
        "coordinates": coords,
        "distance_km": round(result.total_distance_m / 1000, 2),
        "time_min": round(result.total_time_s / 60, 1),
        "maneuvers": [
            {
                "lat": m.lat,
                "lon": m.lon,
                "type": m.type,
                "distance_m": m.distance_m,
                "cumulative_m": m.cumulative_m,
            }
            for m in maneuvers
        ],
        "legs": [
            {
                "from": leg.from_id,
                "to": leg.to_id,
                "road_class": leg.road_class,
                "length_m": round(leg.length_m),
                "speed_kmh": leg.speed_kmh,
                "energy_wh": round(leg.energy_wh, 1),
                "wait_s": round(leg.wait_s, 1),
                "eco_speed_kmh": round(
                    min(eco_speed_kmh, ROAD_CLASS_SPEED_KMH.get(normalize_road_class(leg.road_class), 40.0)),
                    1,
                ),
            }
            for leg in result.legs
        ],
    }
    if vehicle.fuel_type == "ev":
        payload["energy_kwh"] = round(result.total_energy_wh / 1000, 3)
        payload["efficiency_km_per_kwh"] = round(
            result.total_distance_m / max(result.total_energy_wh, 1e-9), 2
        )
    else:
        fuel_l = result.total_energy_wh / vehicle.wh_per_liter
        payload["fuel_l"] = round(fuel_l, 3)
        payload["efficiency_km_per_l"] = round(
            result.total_distance_m / 1000 / max(fuel_l, 1e-9), 2
        )
    return payload


@app.get("/api/regions")
def list_regions() -> dict:
    """시/도 → 시/군/구 목록과 근사 중심 좌표 (주소 기반 목적지 선택용)."""
    return {
        sido: {
            "lat": info["lat"],
            "lon": info["lon"],
            "districts": {
                gu: {"lat": lat, "lon": lon}
                for gu, (lat, lon) in info["districts"].items()
            },
        }
        for sido, info in REGIONS.items()
    }


@app.get("/api/search")
async def search(q: str = Query(..., min_length=1), limit: int = Query(10, le=20)) -> list[dict]:
    """통합검색: 카카오 로컬 API(키 설정 시) → 내장 POI·행정구역 폴백."""
    kakao = await search_kakao_places(q, limit)
    if kakao is not None:
        return kakao
    return [
        {
            "name": p.name,
            "address": p.address,
            "lat": p.lat,
            "lon": p.lon,
            "category": p.category,
        }
        for p in search_local(q, limit)
    ]


@app.get("/api/network")
def network() -> dict:
    """3D 렌더링용 도로망 전체: 노드(고도·신호 타이밍)와 링크.

    신호 타이밍(주기/녹색/오프셋)을 함께 내려 클라이언트가 임의 시각의
    신호 색을 직접 계산(시뮬레이터와 동일 규칙)할 수 있게 한다.
    """
    graph = get_graph()
    sim = SignalSimulator(real_timings=_merged_timings(graph))
    nodes = {}
    for n in graph.nodes.values():
        item: dict = {"lat": n.lat, "lon": n.lon, "elev": n.elev_m, "signal": n.signal}
        timing = sim.timing_for(n)
        if timing:
            item["timing"] = {
                "cycle_s": timing.cycle_s,
                "green_s": timing.green_s,
                "offset_s": timing.offset_s,
            }
        nodes[n.id] = item
    edges = [
        {"from": e.from_id, "to": e.to_id, "road_class": e.road_class}
        for adj in graph.adjacency.values()
        for e in adj
    ]
    return {"nodes": nodes, "edges": edges}


@app.get("/api/vehicles")
def list_vehicles() -> list[dict]:
    return [_vehicle_payload(v) for v in PRESETS.values()]


@app.get("/api/route")
def route(
    start_lat: float = Query(..., description="출발 위도"),
    start_lon: float = Query(..., description="출발 경도"),
    end_lat: float = Query(..., description="도착 위도"),
    end_lon: float = Query(..., description="도착 경도"),
    hour: int = Query(8, ge=0, le=23, description="출발 시각(0-23시)"),
    is_weekend: bool = Query(False, description="평일/주말 교통 패턴 선택"),
    vehicle: str = Query(DEFAULT_VEHICLE_ID),
    signal_mode: str = Query("sim", pattern="^(sim|stats)$", description="신호 반영: sim=시뮬레이터 확정 판정+GLOSA, stats=통계 기대값"),
) -> dict:
    """전비 최적 경로와 최소 시간 경로를 함께 계산해 비교 결과를 반환. 전국 어디서나 출발/도착 가능."""
    if vehicle not in PRESETS:
        raise HTTPException(404, f"알 수 없는 차종: {vehicle}")
    graph, is_synthetic = get_graph_for_route(start_lat, start_lon, end_lat, end_lon)
    ev = PRESETS[vehicle]

    start = graph.nearest_node(start_lat, start_lon)
    goal = graph.nearest_node(end_lat, end_lon)
    if start.id == goal.id:
        raise HTTPException(400, "출발지와 도착지가 같은 교차로입니다")

    warnings: list[str] = []
    for label, lat, lon, node in (
        ("출발지", start_lat, start_lon, start),
        ("도착지", end_lat, end_lon, goal),
    ):
        gap_m = haversine_m(lat, lon, node.lat, node.lon)
        if gap_m > COVERAGE_WARN_M:
            warnings.append(
                f"{label}가 도로망 데이터에서 {gap_m / 1000:.1f}km 밖이라 "
                f"가장 가까운 도로망 지점으로 안내합니다"
            )
    if is_synthetic:
        warnings.append(
            "이 지역은 실도로망(OSM) 데이터를 가져오지 못해 근사 격자망으로 계산했습니다 — "
            "실제 도로 형태·제한속도와 다를 수 있습니다"
        )

    signals = SignalSimulator(real_timings=_merged_timings(graph)) if signal_mode == "sim" else None
    depart_s = hour * 3600.0
    try:
        eco = find_route(
            graph, ev, start.id, goal.id, hour, mode="eco",
            signals=signals, depart_s=depart_s, is_weekend=is_weekend,
        )
        fastest = find_route(
            graph, ev, start.id, goal.id, hour, mode="fastest",
            signals=signals, depart_s=depart_s, is_weekend=is_weekend,
        )
    except NoRouteError as exc:
        raise HTTPException(404, str(exc)) from exc

    glosa_payload = None
    if signals is not None:
        advisories = compute_advisories(graph, ev, eco, depart_s, signals)
        saved_wh = sum(a.saved_wh for a in advisories)
        remaining_wh = eco.total_energy_wh - saved_wh
        glosa_payload = {
            "advisories": [
                {
                    "node_id": a.node_id,
                    "leg_start": a.leg_start,
                    "leg_end": a.leg_end,
                    "distance_m": a.distance_m,
                    "lat": graph.nodes[a.node_id].lat,
                    "lon": graph.nodes[a.node_id].lon,
                    "original_kmh": a.original_kmh,
                    "advisory_kmh": a.advisory_kmh,
                    "wait_avoided_s": a.wait_avoided_s,
                    "saved_wh": a.saved_wh,
                }
                for a in advisories
            ],
            "saved_wh": round(saved_wh, 1),
        }
        if ev.fuel_type == "ev":
            glosa_payload["energy_kwh_if_followed"] = round(remaining_wh / 1000, 3)
        else:
            glosa_payload["fuel_l_if_followed"] = round(remaining_wh / ev.wh_per_liter, 3)

    saving_wh = fastest.total_energy_wh - eco.total_energy_wh
    return {
        "vehicle": _vehicle_payload(ev),
        "hour": hour,
        "is_weekend": is_weekend,
        "signal_mode": signal_mode,
        "warnings": warnings,
        "glosa": glosa_payload,
        "eco": _route_payload(graph, ev, eco),
        "fastest": _route_payload(graph, ev, fastest),
        "saving": {
            "energy_wh": round(saving_wh, 1),
            "energy_pct": round(
                100 * saving_wh / max(fastest.total_energy_wh, 1e-9), 1
            ),
            "extra_time_min": round(
                (eco.total_time_s - fastest.total_time_s) / 60, 1
            ),
        },
    }


class TripPing(BaseModel):
    lat: float
    lon: float
    speed_ms: float
    ts: float | None = None


@app.post("/api/trip/ping")
def trip_ping(ping: TripPing) -> dict:
    """실주행 GPS 핑 기록 (frontend/live.html). 신호 노드 근처가 아니면 버린다."""
    graph = get_graph()
    match = graph.nearest_signal_node(ping.lat, ping.lon, MAX_PING_LOG_DIST_M)
    if match is None:
        return {"logged": False, "node_id": None, "dist_m": None}
    node, dist_m = match
    ts = ping.ts if ping.ts is not None else time.time()
    tripdb.log_ping(get_trip_conn(), node.id, dist_m, ping.lat, ping.lon, ping.speed_ms, ts)
    return {"logged": True, "node_id": node.id, "dist_m": round(dist_m, 1)}


@app.post("/api/trip/relearn")
def trip_relearn() -> dict:
    """누적된 GPS 로그로 개인 신호 타이밍 추정을 강제 재계산."""
    graph = get_graph()
    learned = get_learned_timings(graph, force=True)
    return {"learned_nodes": len(learned)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/3d")
def three_d() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "3d.html")


@app.get("/live")
def live_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "live.html")


@app.get("/nav")
def nav_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "nav.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
