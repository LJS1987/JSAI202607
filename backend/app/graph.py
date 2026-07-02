"""도로망 그래프 자료구조와 로더.

노드 = 교차로(위경도, 고도, 신호 유형), 엣지 = 방향성 도로 링크(길이,
도로 등급). JSON 파일 형식:

{
  "nodes": {"<id>": {"lat": .., "lon": .., "elev": .., "signal": "major|minor|none"}},
  "edges": [{"from": "..", "to": "..", "length": <m>, "road_class": ".."}]
}
"""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 위경도 사이의 대원거리(m)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class Node:
    id: str
    lat: float
    lon: float
    elev_m: float
    signal: str  # "major" | "minor" | "none"


@dataclass(frozen=True)
class Edge:
    from_id: str
    to_id: str
    length_m: float
    road_class: str


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    adjacency: dict[str, list[Edge]] = field(default_factory=dict)

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node
        self.adjacency.setdefault(node.id, [])

    def add_edge(self, edge: Edge) -> None:
        self.adjacency.setdefault(edge.from_id, []).append(edge)

    def nearest_node(self, lat: float, lon: float) -> Node:
        """주어진 좌표에서 가장 가까운 노드(맵 매칭 단순화)."""
        return min(
            self.nodes.values(),
            key=lambda n: haversine_m(lat, lon, n.lat, n.lon),
        )

    @classmethod
    def from_json(cls, path: Path) -> "Graph":
        raw = json.loads(path.read_text(encoding="utf-8"))
        graph = cls()
        for node_id, attrs in raw["nodes"].items():
            graph.add_node(
                Node(
                    id=node_id,
                    lat=attrs["lat"],
                    lon=attrs["lon"],
                    elev_m=attrs.get("elev", 0.0),
                    signal=attrs.get("signal", "none"),
                )
            )
        for e in raw["edges"]:
            graph.add_edge(
                Edge(
                    from_id=e["from"],
                    to_id=e["to"],
                    length_m=e["length"],
                    road_class=e.get("road_class", "tertiary"),
                )
            )
        return graph
