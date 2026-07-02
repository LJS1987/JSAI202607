"""통합검색용 장소 데이터와 로컬 검색.

카카오 로컬 API 키(KAKAO_REST_API_KEY)가 있으면 providers 의 실검색을
우선 사용하고, 없으면 내장 POI + 행정구역(시/군/구) 이름 매칭으로
폴백한다. POI 는 데모 도로망(강남 일대) 중심의 주요 지점이다.
"""

from dataclasses import dataclass

from .regions import REGIONS


@dataclass(frozen=True)
class Place:
    name: str
    address: str
    lat: float
    lon: float
    category: str  # "장소" | "지역"


POIS: list[Place] = [
    Place("강남역", "서울 강남구 강남대로", 37.4979, 127.0276, "장소"),
    Place("신논현역", "서울 강남구 봉은사로", 37.5046, 127.0250, "장소"),
    Place("논현역", "서울 강남구 학동로", 37.5109, 127.0214, "장소"),
    Place("학동역", "서울 강남구 논현로", 37.5145, 127.0316, "장소"),
    Place("압구정역", "서울 강남구 압구정로", 37.5270, 127.0286, "장소"),
    Place("역삼역", "서울 강남구 테헤란로", 37.5006, 127.0364, "장소"),
    Place("언주역", "서울 강남구 봉은사로", 37.5072, 127.0336, "장소"),
    Place("선릉역", "서울 강남구 테헤란로", 37.5045, 127.0489, "장소"),
    Place("선정릉", "서울 강남구 선릉로", 37.5100, 127.0490, "장소"),
    Place("삼성역", "서울 강남구 테헤란로", 37.5088, 127.0631, "장소"),
    Place("코엑스", "서울 강남구 영동대로 513", 37.5115, 127.0595, "장소"),
    Place("봉은사", "서울 강남구 봉은사로 531", 37.5148, 127.0577, "장소"),
    Place("청담역", "서울 강남구 학동로", 37.5192, 127.0536, "장소"),
    Place("강남구청", "서울 강남구 학동로 426", 37.5172, 127.0473, "장소"),
    Place("도산공원", "서울 강남구 도산대로45길", 37.5240, 127.0354, "장소"),
    Place("양재역", "서울 서초구 남부순환로", 37.4837, 127.0343, "장소"),
    Place("잠실역", "서울 송파구 올림픽로", 37.5133, 127.1001, "장소"),
    Place("서울역", "서울 중구 한강대로 405", 37.5547, 126.9707, "장소"),
    Place("김포공항", "서울 강서구 하늘길 76", 37.5629, 126.8014, "장소"),
    Place("인천공항", "인천 중구 공항로 272", 37.4602, 126.4407, "장소"),
    Place("부산역", "부산 동구 중앙대로 206", 35.1151, 129.0403, "장소"),
    Place("해운대해수욕장", "부산 해운대구 우동", 35.1587, 129.1604, "장소"),
]


def _norm(text: str) -> str:
    return text.replace(" ", "").lower()


def search_local(query: str, limit: int = 10) -> list[Place]:
    """내장 POI + 시/군/구 이름에서 부분 일치 검색."""
    q = _norm(query)
    if not q:
        return []

    results: list[Place] = [p for p in POIS if q in _norm(p.name)]

    for sido, info in REGIONS.items():
        if q in _norm(sido):
            results.append(Place(sido, sido, info["lat"], info["lon"], "지역"))
        for gu, (lat, lon) in info["districts"].items():
            full = f"{sido} {gu}"
            if q in _norm(gu) or q in _norm(full):
                results.append(Place(full, full, lat, lon, "지역"))

    return results[:limit]
