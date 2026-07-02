"""데모용 샘플 도로망 생성 (서울 강남 일대 격자 근사).

실제 서울 강남권 좌표 범위(테헤란로·강남대로 일대)에 격자형 도로망을
생성한다. 실서비스에서는 providers.osm_loader 로 OpenStreetMap 실데이터를
불러와 같은 JSON 형식으로 변환해 대체한다.

- 4번째마다 간선(primary), 2번째마다 보조간선(secondary), 나머지 이면도로
- 간선끼리 만나는 교차로는 대형 신호("major"), 간선-이면은 "minor"
- 고도는 완만한 구릉(사인 곡선 합성, 20~80m)으로 근사 — 전비 경로가
  최단 경로와 달라지는 효과를 보여주기 위함
- 남북 방향 외곽 한 축은 신호 없는 도시고속도로(motorway)로 지정
"""

import json
import math
from pathlib import Path

# 강남역~선릉역 일대 근사 범위
LAT_MIN, LAT_MAX = 37.490, 37.530
LON_MIN, LON_MAX = 127.020, 127.070
GRID_N = 13  # 13x13 교차로


def _elevation(i: int, j: int) -> float:
    """구릉 지형 근사: 남동쪽(매봉·구룡산 방향)이 높아지는 완만한 경사."""
    x, y = i / (GRID_N - 1), j / (GRID_N - 1)
    hills = (
        25.0 * math.sin(math.pi * x) * math.sin(math.pi * y)
        + 30.0 * x * (1 - y)
        + 8.0 * math.sin(3 * math.pi * x) * math.cos(2 * math.pi * y)
    )
    return round(20.0 + max(hills, 0.0), 1)


def _line_class(index: int) -> str:
    if index % 4 == 0:
        return "primary"
    if index % 2 == 0:
        return "secondary"
    return "residential"


def _signal_type(cls_a: str, cls_b: str) -> str:
    majors = {"primary", "secondary"}
    if cls_a in majors and cls_b in majors:
        return "major"
    if cls_a in majors or cls_b in majors:
        return "minor"
    return "none"


def build_sample_graph() -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node_id(i: int, j: int) -> str:
        return f"n{i}_{j}"

    for i in range(GRID_N):
        for j in range(GRID_N):
            lat = LAT_MIN + (LAT_MAX - LAT_MIN) * j / (GRID_N - 1)
            lon = LON_MIN + (LON_MAX - LON_MIN) * i / (GRID_N - 1)
            ns_class = "motorway" if i == GRID_N - 1 else _line_class(i)
            ew_class = _line_class(j)
            signal = "none" if ns_class == "motorway" else _signal_type(ns_class, ew_class)
            nodes[node_id(i, j)] = {
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "elev": _elevation(i, j),
                "signal": signal,
            }

    # 격자 간격의 실거리(m) — 위도/경도 방향이 다름
    lat_step_m = 111_320.0 * (LAT_MAX - LAT_MIN) / (GRID_N - 1)
    lon_step_m = (
        111_320.0
        * math.cos(math.radians((LAT_MIN + LAT_MAX) / 2))
        * (LON_MAX - LON_MIN)
        / (GRID_N - 1)
    )

    def add_bidirectional(a: str, b: str, length_m: float, road_class: str) -> None:
        edges.append({"from": a, "to": b, "length": round(length_m, 1), "road_class": road_class})
        edges.append({"from": b, "to": a, "length": round(length_m, 1), "road_class": road_class})

    for i in range(GRID_N):
        ns_class = "motorway" if i == GRID_N - 1 else _line_class(i)
        for j in range(GRID_N - 1):
            add_bidirectional(node_id(i, j), node_id(i, j + 1), lat_step_m, ns_class)
    for j in range(GRID_N):
        ew_class = _line_class(j)
        for i in range(GRID_N - 1):
            add_bidirectional(node_id(i, j), node_id(i + 1, j), lon_step_m, ew_class)

    return {"nodes": nodes, "edges": edges}


def ensure_sample_graph(path: Path) -> Path:
    """샘플 그래프 JSON이 없으면 생성한다 (data/ 는 git 미추적)."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(build_sample_graph(), ensure_ascii=False), encoding="utf-8"
        )
    return path
