"""OpenStreetMap 실도로망을 내려받아 서버용 그래프 JSON 으로 변환한다.

사용법 (인터넷 연결된 PC 에서, pip install osmnx 후):

    python scripts/build_osm_graph.py "Gangnam-gu, Seoul, South Korea" \
        -o backend/data/gangnam.json
    python scripts/build_osm_graph.py "Seoul, South Korea" \
        -o backend/data/seoul.json --dem seoul_dem.tif

만든 파일은 환경 변수로 지정해 서버가 로드한다:

    EV_NAV_GRAPH=backend/data/gangnam.json uvicorn backend.app.main:app

--dem 은 GeoTIFF 고도 래스터(국토지리정보원 DEM, SRTM 등). 생략하면
고도 0(평지)으로 저장되며 회생제동 경사 계산이 비활성화되는 것과 같다.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.providers import graph_to_json, load_osm_graph  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("place", help='지역명 (예: "Gangnam-gu, Seoul, South Korea")')
    parser.add_argument("-o", "--output", required=True, help="저장할 JSON 경로")
    parser.add_argument("--dem", help="고도 GeoTIFF 경로 (선택)")
    args = parser.parse_args()

    print(f"OSM 도로망 다운로드 중: {args.place}")
    graph = load_osm_graph(args.place, dem_path=args.dem)
    signals = sum(1 for n in graph.nodes.values() if n.signal != "none")
    edges = sum(len(a) for a in graph.adjacency.values())
    print(f"노드 {len(graph.nodes):,}개 (신호등 {signals:,}개), 링크 {edges:,}개")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(graph_to_json(graph), ensure_ascii=False), encoding="utf-8")
    print(f"저장 완료: {out}")
    print(f"실행: EV_NAV_GRAPH={out} uvicorn backend.app.main:app")


if __name__ == "__main__":
    main()
