"""전기차 전비 최적 내비게이션 API 서버.

실행:
    uvicorn backend.app.main:app --reload
이후 http://localhost:8000 에서 지도 UI 사용.
"""

import asyncio
import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import tripdb
from .energy import optimal_cruise_speed_ms
from .glosa import compute_advisories
from .graph import Graph, haversine_m
from .places import search_local
from .providers import fetch_police_signal_timings, search_kakao_places
from .regions import REGIONS
from .routing import NoRouteError, RouteResult, find_route
from .sample_data import ensure_sample_graph
from .signal_learning import estimate_timing, extract_visits
from .signals import SignalSimulator, SignalTiming
from .traffic import ROAD_CLASS_SPEED_KMH, normalize_road_class
from .vehicles import DEFAULT_VEHICLE_ID, PRESETS, Vehicle

logger = logging.getLogger(__name__)

# 요청 지점이 도로망에서 이보다 멀면 커버리지 밖 경고를 붙인다
COVERAGE_WARN_M = 1_500.0
# 개인 GPS 핑이 신호 노드에서 이보다 멀면 기록하지 않는다
MAX_PING_LOG_DIST_M = 40.0

ROOT = Path(__file__).resolve().parents[2]
# EV_NAV_GRAPH 로 실지도(OSM) 그래프 JSON 을 지정할 수 있다 (scripts/build_osm_graph.py 참고)
GRAPH_PATH = Path(os.environ.get("EV_NAV_GRAPH", ROOT / "backend" / "data" / "sample_graph.json"))
TRIP_DB_PATH = ROOT / "backend" / "data" / "trips.db"
FRONTEND_DIR = ROOT / "frontend"

app = FastAPI(title="EV 전비 최적 내비게이션", version="0.1.0")

_graph: Graph | None = None


def get_graph() -> Graph:
    global _graph
    if _graph is None:
        if not GRAPH_PATH.exists():
            if "EV_NAV_GRAPH" in os.environ:
                raise RuntimeError(f"EV_NAV_GRAPH 파일이 없습니다: {GRAPH_PATH}")
            ensure_sample_graph(GRAPH_PATH)
        _graph = Graph.from_json(GRAPH_PATH)
    return _graph


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
    payload = {
        "mode": result.mode,
        "coordinates": coords,
        "distance_km": round(result.total_distance_m / 1000, 2),
        "time_min": round(result.total_time_s / 60, 1),
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
    vehicle: str = Query(DEFAULT_VEHICLE_ID),
    signal_mode: str = Query("sim", pattern="^(sim|stats)$", description="신호 반영: sim=시뮬레이터 확정 판정+GLOSA, stats=통계 기대값"),
) -> dict:
    """전비 최적 경로와 최소 시간 경로를 함께 계산해 비교 결과를 반환."""
    if vehicle not in PRESETS:
        raise HTTPException(404, f"알 수 없는 차종: {vehicle}")
    graph = get_graph()
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
                f"{label}가 데모 도로망(강남 일대)에서 {gap_m / 1000:.1f}km 밖이라 "
                f"가장 가까운 도로망 지점으로 안내합니다"
            )

    signals = SignalSimulator(real_timings=_merged_timings(graph)) if signal_mode == "sim" else None
    depart_s = hour * 3600.0
    try:
        eco = find_route(
            graph, ev, start.id, goal.id, hour, mode="eco",
            signals=signals, depart_s=depart_s,
        )
        fastest = find_route(
            graph, ev, start.id, goal.id, hour, mode="fastest",
            signals=signals, depart_s=depart_s,
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


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
