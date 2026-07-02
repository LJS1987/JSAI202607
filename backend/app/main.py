"""전기차 전비 최적 내비게이션 API 서버.

실행:
    uvicorn backend.app.main:app --reload
이후 http://localhost:8000 에서 지도 UI 사용.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .graph import Graph
from .routing import NoRouteError, RouteResult, find_route
from .sample_data import ensure_sample_graph
from .vehicles import DEFAULT_VEHICLE_ID, PRESETS

ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = ROOT / "backend" / "data" / "sample_graph.json"
FRONTEND_DIR = ROOT / "frontend"

app = FastAPI(title="EV 전비 최적 내비게이션", version="0.1.0")

_graph: Graph | None = None


def get_graph() -> Graph:
    global _graph
    if _graph is None:
        _graph = Graph.from_json(ensure_sample_graph(GRAPH_PATH))
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
                "road_class": leg.road_class,
                "length_m": round(leg.length_m),
                "speed_kmh": leg.speed_kmh,
                "energy_wh": round(leg.energy_wh, 1),
            }
            for leg in result.legs
        ],
    }


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

    try:
        eco = find_route(graph, ev, start.id, goal.id, hour, mode="eco")
        fastest = find_route(graph, ev, start.id, goal.id, hour, mode="fastest")
    except NoRouteError as exc:
        raise HTTPException(404, str(exc)) from exc

    saving_wh = fastest.total_energy_wh - eco.total_energy_wh
    return {
        "vehicle": {"id": ev.id, "name": ev.name, "battery_kwh": ev.battery_kwh},
        "hour": hour,
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


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
