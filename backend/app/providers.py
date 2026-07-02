"""실데이터 연동 지점 (공공 API / OSM).

데모는 sample_data 의 합성 도로망과 traffic 의 평균 프로파일로 동작하지만,
실서비스 전환 시 이 모듈의 커넥터를 구현해 끼워 넣는다.

필요한 API 키는 환경 변수로 주입한다 (.env 는 git 미추적):
  ITS_API_KEY   국가교통정보센터 (https://www.its.go.kr) 오픈 API
  SEOUL_API_KEY 서울 열린데이터광장 / TOPIS (https://topis.seoul.go.kr)
  VWORLD_KEY    브이월드 (지오코딩·고도 API, https://www.vworld.kr)

데이터 소스 매핑:
  도로망/신호 위치  OpenStreetMap 한국 추출본 (highway=traffic_signals 태그)
                    또는 표준노드링크 (국가교통정보센터 제공)
  실시간 소통 속도  ITS 소통정보 API(전국) / TOPIS 링크별 속도(서울)
  평소 교통 패턴    TOPIS 시간대별 통계, 링크별 이력 축적
  고도(DEM)         국토지리정보원 DEM 또는 브이월드 고도 API
  신호 주기         경찰청 신호운영 데이터(공공데이터포털) — 미제공 지역은
                    traffic.SIGNAL_PROFILES 의 통계적 기본값 사용
"""

import os

import httpx

ITS_TRAFFIC_URL = "https://openapi.its.go.kr:9443/trafficInfo"
KAKAO_LOCAL_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


async def search_kakao_places(query: str, limit: int = 10) -> list[dict] | None:
    """카카오 로컬 키워드 검색 → [{name, address, lat, lon, category}].

    KAKAO_REST_API_KEY 미설정 시 None 을 반환해 places.search_local 의
    내장 데이터 검색으로 폴백한다.
    """
    api_key = os.environ.get("KAKAO_REST_API_KEY")
    if not api_key:
        return None
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(
            KAKAO_LOCAL_URL,
            params={"query": query, "size": limit},
            headers={"Authorization": f"KakaoAK {api_key}"},
        )
        resp.raise_for_status()
        docs = resp.json().get("documents", [])
    return [
        {
            "name": d["place_name"],
            "address": d.get("road_address_name") or d.get("address_name", ""),
            "lat": float(d["y"]),
            "lon": float(d["x"]),
            "category": "장소",
        }
        for d in docs
    ]


async def fetch_its_link_speeds(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> dict[str, float]:
    """국가교통정보센터 실시간 소통정보 → {표준링크ID: 속도 km/h}.

    ITS_API_KEY 미설정 시 빈 dict 를 반환해 traffic.py 의 평소 프로파일로
    폴백한다.
    """
    api_key = os.environ.get("ITS_API_KEY")
    if not api_key:
        return {}
    params = {
        "apiKey": api_key,
        "type": "all",
        "minX": min_lon,
        "maxX": max_lon,
        "minY": min_lat,
        "maxY": max_lat,
        "getType": "json",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(ITS_TRAFFIC_URL, params=params)
        resp.raise_for_status()
        body = resp.json()
    items = body.get("body", {}).get("items", [])
    return {
        item["linkId"]: float(item["speed"])
        for item in items
        if item.get("linkId") and item.get("speed")
    }


def load_osm_graph(place: str, dem_path: str | None = None):
    """OpenStreetMap 실도로망 로더 (osmnx 설치 시 사용 가능).

    사용 예:
        graph = load_osm_graph("Gangnam-gu, Seoul, South Korea")

    - 신호등: highway=traffic_signals 노드. 간선(primary 이상)이 지나는
      교차로는 "major", 나머지는 "minor" 신호로 분류한다.
    - 고도: dem_path(GeoTIFF, 국토지리정보원 DEM 또는 SRTM)를 주면
      osmnx 로 노드 고도를 채운다. 없으면 0 (평지 가정).
    - 일방통행은 osmnx 방향 그래프가 이미 반영한다.
    """
    try:
        import osmnx as ox
    except ImportError as exc:
        raise RuntimeError(
            "실지도 로딩에는 osmnx 가 필요합니다: pip install osmnx"
        ) from exc

    from .graph import Graph, Node, Edge
    from .traffic import normalize_road_class

    g = ox.graph_from_place(place, network_type="drive")
    if dem_path:
        g = ox.elevation.add_node_elevations_raster(g, dem_path)

    # 노드별 최고 도로 등급을 먼저 파악해 신호 규모 분류에 사용
    majors = {"motorway", "trunk", "primary", "secondary"}
    node_has_major: set = set()
    edges: list[Edge] = []
    for u, v, attrs in g.edges(data=True):
        highway = attrs.get("highway", "tertiary")
        if isinstance(highway, list):
            highway = highway[0]
        road_class = normalize_road_class(str(highway))
        if road_class in majors:
            node_has_major.update((u, v))
        edges.append(
            Edge(
                from_id=str(u),
                to_id=str(v),
                length_m=float(attrs.get("length", 0.0)),
                road_class=road_class,
            )
        )

    graph = Graph()
    for osm_id, attrs in g.nodes(data=True):
        if attrs.get("highway") == "traffic_signals":
            signal = "major" if osm_id in node_has_major else "minor"
        else:
            signal = "none"
        graph.add_node(
            Node(
                id=str(osm_id),
                lat=attrs["y"],
                lon=attrs["x"],
                elev_m=float(attrs.get("elevation", 0.0)),
                signal=signal,
            )
        )
    for edge in edges:
        graph.add_edge(edge)
    return graph


def graph_to_json(graph) -> dict:
    """Graph → sample_graph.json 과 동일한 직렬화 형식."""
    return {
        "nodes": {
            n.id: {"lat": n.lat, "lon": n.lon, "elev": n.elev_m, "signal": n.signal}
            for n in graph.nodes.values()
        },
        "edges": [
            {"from": e.from_id, "to": e.to_id, "length": e.length_m, "road_class": e.road_class}
            for adj in graph.adjacency.values()
            for e in adj
        ],
    }
