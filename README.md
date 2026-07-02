# EV 전비 최적 내비게이션 (JSAI202607)

대한민국 도로 지도, 교통신호, 평소 교통 흐름을 고려해 **전기차 전비(km/kWh)를
극대화하는 경로**를 안내하는 내비게이션 프로토타입입니다. 같은 출발지·도착지에
대해 **최소 시간 경로**와 **전비 최적 경로**를 함께 계산해 에너지 절약량과
추가 소요 시간을 비교해 보여줍니다.

![구조] 백엔드 FastAPI(경로 엔진) + 프론트엔드 Leaflet 지도 UI

## 빠른 시작

```bash
pip install -r requirements.txt
uvicorn backend.app.main:app --reload
# 브라우저에서 http://localhost:8000 접속
```

- **출발지**: `현재 위치 사용` 버튼(브라우저 Geolocation) 또는 지도 클릭
- **도착지**: 통합검색(장소·역·지역 키워드) 또는 주소로 찾기(시/도 → 시/군/구 선택)
- 차종(아이오닉5/EV6/모델3/레이EV)과 출발 시각을 바꾸면 결과가 즉시 갱신됩니다.
- 데모 도로망(강남 일대) 밖의 목적지를 고르면 가장 가까운 도로망 지점으로
  안내하며 경고를 표시합니다.
첫 실행 시 서울 강남 일대를 근사한 샘플 도로망(`backend/data/sample_graph.json`)이
자동 생성됩니다.

테스트:

```bash
python -m pytest backend/tests
```

## 동작 원리

### 1. 물리 기반 전비 모델 (`backend/app/energy.py`)

도로 링크별 배터리 소비를 주행저항 방정식으로 계산합니다.

- **구름저항** `Crr·m·g·cosθ` + **공기저항** `½·ρ·Cd·A·v²` + **경사** `m·g·Δh`
- 구동 시 파워트레인 효율(η≈0.90)로 나누고, 내리막에서는 **회생제동
  회수율**(η≈0.65)을 곱해 음수(충전) 에너지를 허용
- 공조 등 **보조 전력**은 주행·대기 시간에 비례해 가산

### 2. 교통신호 모델 (`backend/app/traffic.py`, `energy.signal_stop_energy_wh`)

신호 교차로마다 **정차 확률 × (재가속 순손실 + 대기 중 보조 전력)** 을 기대값으로
반영합니다. 정차 1회의 순손실은 `½·m·v²·(1/η_drive − η_regen)` — 속도가 높은
간선에서 신호에 걸리는 것이 전비에 특히 불리하다는 점이 자연스럽게 모델링됩니다.
교차 도로 등급에 따라 신호 주기·대기 시간 프로파일을 달리 적용합니다.

### 3. 평소 교통 흐름 (`backend/app/traffic.py`)

도로 등급별 제한속도(안전속도 5030 반영)에 **시간대별 혼잡 계수**(출근 07–09시,
퇴근 18–20시 정체가 깊은 서울 평일 패턴)를 곱해 기대 주행 속도를 산출합니다.
속도가 곧 공기저항과 신호 손실을 좌우하므로 출발 시각에 따라 최적 경로가 달라집니다.

### 4. 전비 최적 경로 탐색 (`backend/app/routing.py`)

내리막 회생 때문에 링크 비용(Wh)이 음수가 될 수 있어 다익스트라를 그대로 쓸 수
없습니다. 고도 기반 **전위 함수** `φ(n) = −η_regen·m·g·h(n)` 으로 비용을
보정하면(회생 회수량은 위치에너지 낙차의 η_regen배를 넘을 수 없음이 물리적으로
보장) 모든 보정 비용이 비음수가 되어 최적성이 유지됩니다. 최소 시간 모드는 링크
통과 시간 + 신호 기대 대기를 비용으로 동일한 탐색기를 사용합니다.

## API

| 엔드포인트 | 설명 |
|---|---|
| `GET /api/route?start_lat&start_lon&end_lat&end_lon&hour&vehicle` | 전비 최적 + 최소 시간 경로 비교 (커버리지 경고 포함) |
| `GET /api/search?q=` | 통합검색 — 카카오 로컬 API(`KAKAO_REST_API_KEY` 설정 시) → 내장 POI·행정구역 폴백 |
| `GET /api/regions` | 시/도 → 시/군/구 목록과 근사 중심 좌표 |
| `GET /api/vehicles` | 차종 프리셋 목록 |
| `GET /` | 지도 UI |

## 실서비스 데이터 연동 로드맵 (`backend/app/providers.py`)

데모는 합성 도로망과 평균 프로파일로 동작하며, 실데이터 연동 지점이 코드에
준비되어 있습니다. API 키는 환경 변수(`.env`, git 미추적)로 주입합니다.

| 데이터 | 소스 | 상태 |
|---|---|---|
| 전국 도로망 | OpenStreetMap 한국 추출본 (`providers.load_osm_graph`, osmnx) 또는 표준노드링크 | 로더 구현됨 (osmnx 옵션) |
| 실시간 소통 속도 | 국가교통정보센터 ITS 오픈 API (`providers.fetch_its_link_speeds`), 서울 TOPIS | 커넥터 구현, 키 필요 |
| 장소 검색(지오코딩) | 카카오 로컬 API (`providers.search_kakao_places`) | 커넥터 구현, 키 없으면 내장 POI·시군구 폴백 |
| 신호등 위치 | OSM `highway=traffic_signals` 태그 | 로더에 포함 |
| 신호 주기 | 경찰청 신호운영 데이터(공공데이터포털) | 미연동 — 통계 기본값 사용 |
| 고도(DEM) | 국토지리정보원 DEM, 브이월드 고도 API | 미연동 — 샘플 지형 사용 |
| 평소 교통 패턴 | TOPIS 시간대별 통계, 링크별 이력 축적 | 시간대 프로파일로 근사 |

## 프로젝트 구조

```
backend/
  app/
    energy.py      # 물리 기반 전비 모델 (주행저항 + 회생 + 신호 정차)
    traffic.py     # 도로 등급·시간대별 흐름, 신호 프로파일
    graph.py       # 도로망 그래프 (노드=교차로, 엣지=링크)
    routing.py     # 전위 보정 다익스트라 (eco / fastest)
    sample_data.py # 강남 일대 샘플 도로망 생성기
    regions.py     # 전국 시/도·시/군/구 근사 좌표 (주소 선택용)
    places.py      # 통합검색 내장 POI + 로컬 검색
    providers.py   # ITS·TOPIS·OSM·카카오 로컬 실데이터 커넥터
    vehicles.py    # 차종 물리 파라미터 프리셋
    main.py        # FastAPI 서버
  tests/           # 물리 타당성·경로 최적성 테스트
frontend/
  index.html       # Leaflet 지도 UI (경로 비교·절약량 표시)
  vendor/          # Leaflet 1.9.4 로컬 번들 (오프라인 동작)
```
