"""전기차 전비 최적 내비게이션 API 서버.

실행:
    uvicorn backend.app.main:app --reload
이후 http://localhost:8000 에서 지도 UI 사용.
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .glosa import compute_advisories
from .graph import Graph, haversine_m
from .places import search_local
from .providers import search_kakao_places
from .regions import REGIONS
from .routing import NoRouteError, RouteResult, find_route
from .sample_data import ensure_sample_graph
from .signals import SignalSimulator
from .vehicles import DEFAULT_VEHICLE_ID, PRESETS

# 요청 지점이 도로망에서 이보다 멀면 커버리지 밖 경고를 붙인다
COVERAGE_WARN_M = 1_500.0

ROOT = Path(__file__).resolve().parents[2]
# EV_NAV_GRAPH 로 실지도(OSM) 그래프 JSON 을 지정할 수 있다 (scripts/build_osm_graph.py 참고)
GRAPH_PATH = Path(os.environ.get("EV_NAV_GRAPH", ROOT / "backend" / "data" / "sample_graph.json"))
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


def _route_payload(graph: Graph, result: RouteResult) -> dict:
    coords = [
        {"lat": graph.nodes[nid].lat, "lon": graph.nodes[nid].lon}
        for nid in result.node_ids
    ]
    return {
        "mode": result.mode,
        "coordinates": coords,
        "distance_km": round(result.total_distance_m / 1000, 2),
        "time_min": round(result.total_time_s / 60, 1),
        "energy_kwh": round(result.total_energy_wh / 1000, 3),
        "efficiency_km_per_kwh": round(
            result.total_distance_m / max(result.total_energy_wh, 1e-9), 2
        ),
        "legs": [
            {
                "from": leg.from_id,
                "to": leg.to_id,
                "road_class": leg.road_class,
                "length_m": round(leg.length_m),
                "speed_kmh": leg.speed_kmh,
                "energy_wh": round(leg.energy_wh, 1),
                "wait_s": round(leg.wait_s, 1),
            }
            for leg in result.legs
        ],
    }


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
    sim = SignalSimulator()
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
    return [
        {"id": v.id, "name": v.name, "battery_kwh": v.battery_kwh}
        for v in PRESETS.values()
    ]


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

    signals = SignalSimulator() if signal_mode == "sim" else None
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
            "energy_kwh_if_followed": round(
                (eco.total_energy_wh - saved_wh) / 1000, 3
            ),
        }

    saving_wh = fastest.total_energy_wh - eco.total_energy_wh
    return {
        "vehicle": {"id": ev.id, "name": ev.name, "battery_kwh": ev.battery_kwh},
        "hour": hour,
        "signal_mode": signal_mode,
        "warnings": warnings,
        "glosa": glosa_payload,
        "eco": _route_payload(graph, eco),
        "fastest": _route_payload(graph, fastest),
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


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/3d")
def three_d() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "3d.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
