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


def load_osm_graph(place: str):
    """OpenStreetMap 실도로망 로더 (osmnx 설치 시 사용 가능).

    사용 예:
        graph = load_osm_graph("Gangnam-gu, Seoul, South Korea")

    osmnx 가 신호등 노드(highway=traffic_signals)와 도로 등급을 함께
    제공하므로 graph.Graph 형식으로 변환해 반환한다.
    """
    try:
        import osmnx as ox
    except ImportError as exc:
        raise RuntimeError(
            "실지도 로딩에는 osmnx 가 필요합니다: pip install osmnx"
        ) from exc

    from .graph import Graph, Node, Edge

    g = ox.graph_from_place(place, network_type="drive")
    graph = Graph()
    for osm_id, attrs in g.nodes(data=True):
        signal = "minor" if attrs.get("highway") == "traffic_signals" else "none"
        graph.add_node(
            Node(
                id=str(osm_id),
                lat=attrs["y"],
                lon=attrs["x"],
                elev_m=float(attrs.get("elevation", 0.0)),
                signal=signal,
            )
        )
    for u, v, attrs in g.edges(data=True):
        highway = attrs.get("highway", "tertiary")
        if isinstance(highway, list):
            highway = highway[0]
        graph.add_edge(
            Edge(
                from_id=str(u),
                to_id=str(v),
                length_m=float(attrs.get("length", 0.0)),
                road_class=str(highway),
            )
        )
    return graph
