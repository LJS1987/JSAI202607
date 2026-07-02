"""통합검색·행정구역 데이터 검증."""

from backend.app.places import search_local
from backend.app.regions import REGIONS


def test_search_finds_poi():
    names = [p.name for p in search_local("코엑스")]
    assert "코엑스" in names


def test_search_ignores_spaces_and_case():
    assert search_local("선릉 역")
    assert search_local("COEX".lower()) == search_local("coex")


def test_search_finds_district_by_partial_name():
    results = search_local("강남구")
    assert any(p.category == "지역" and "강남구" in p.name for p in results)


def test_search_empty_query_returns_nothing():
    assert search_local("") == []
    assert search_local("존재하지않는곳12345") == []


def test_regions_cover_all_17_sido():
    assert len(REGIONS) == 17


def test_region_coordinates_are_inside_korea():
    for sido, info in REGIONS.items():
        for gu, (lat, lon) in info["districts"].items():
            assert 33.0 < lat < 38.7, f"{sido} {gu} 위도 이상"
            assert 124.5 < lon < 131.0, f"{sido} {gu} 경도 이상"


def test_seoul_has_25_districts():
    assert len(REGIONS["서울특별시"]["districts"]) == 25
