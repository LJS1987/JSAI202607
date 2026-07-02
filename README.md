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
- **3D 주행 시뮬레이션**: 경로 계산 후 `🚗 3D 주행 시뮬레이션 보기`를 누르면
  Three.js 기반 3D 뷰(`/3d`)에서 차량이 전비 경로를 주행합니다 — 신호등
  현시가 실시간 애니메이션되고, GLOSA 권장 속도로 감속해 무정차 통과하는
  과정과 에너지 절약량을 HUD 로 보여줍니다. 체이스/버드뷰, 1×/5×/20× 배속.
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

### 2. 교통신호 모델 (`traffic.py` 통계 / `signals.py` 시뮬레이터)

- **통계 모드**(`signal_mode=stats`): 신호 교차로마다 정차 확률 × (재가속
  순손실 + 대기 중 보조 전력)을 기대값으로 반영. 정차 1회 순손실은
  `½·m·v²·(1/η_drive − η_regen)`.
- **시뮬레이터 모드**(`signal_mode=sim`, 기본): 교차로마다 (주기·녹색시간·
  오프셋)을 부여한 결정적 가상 신호로 **도착 시각의 현시를 확정 판정**하는
  시간 의존 탐색. 실시간 신호 API(경찰청 UTIC)와 같은 질문에 답하는
  인터페이스라, 협약 후 실데이터로 교체해도 경로·GLOSA 로직은 그대로다.
  시간 의존 탐색은 신호에 덜 걸리는 시각·경로를 자연히 선호한다(그린 웨이브).

### 2-1. GLOSA 녹색 신호 최적 속도 안내 (`glosa.py`)

정차가 확정된 신호마다 "미리 감속해 녹색 시작에 정확히 도착"하는 권장
속도를 계산합니다. 통과 시각이 원래 정차 후 출발 시각과 같아 하류 타이밍이
변하지 않고, 정차 순손실만 사라집니다. 한 구간 감속으로 부족하면 접근
구간을 앞으로 확장(최대 3구간)하며, 이때 중간 신호들이 새 도착 시각에도
녹색인지 검증합니다. 안내 하한은 원속도의 50%(최저 15km/h)로 교통류
방해를 방지합니다.

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
| `GET /api/route?start_lat&start_lon&end_lat&end_lon&hour&vehicle&signal_mode` | 전비 최적 + 최소 시간 경로 비교, GLOSA 안내, 커버리지 경고 |
| `GET /api/network` | 3D 렌더링용 도로망 전체 (노드 고도·신호 타이밍 포함) |
| `GET /api/search?q=` | 통합검색 — 카카오 로컬 API(`KAKAO_REST_API_KEY` 설정 시) → 내장 POI·행정구역 폴백 |
| `GET /api/regions` | 시/도 → 시/군/구 목록과 근사 중심 좌표 |
| `GET /api/vehicles` | 차종 프리셋 목록 |
| `GET /` | 지도 UI |

## 실서비스 데이터 연동 로드맵 (`backend/app/providers.py`)

데모는 합성 도로망과 평균 프로파일로 동작하며, 실데이터 연동 지점이 코드에
준비되어 있습니다. API 키는 환경 변수(`.env`, git 미추적)로 주입합니다.

| 데이터 | 소스 | 상태 |
|---|---|---|
| 전국 도로망 | OpenStreetMap (`scripts/build_osm_graph.py`, osmnx) 또는 표준노드링크 | **CLI 구현** — 아래 사용법 참고 |
| 실시간 소통 속도 | 국가교통정보센터 ITS 오픈 API (`providers.fetch_its_link_speeds`), 서울 TOPIS | 커넥터 구현, 키 필요 |
| 장소 검색(지오코딩) | 카카오 로컬 API (`providers.search_kakao_places`) | 커넥터 구현, 키 없으면 내장 POI·시군구 폴백 |
| 신호등 위치 | OSM `highway=traffic_signals` 태그 | 로더에 포함 |
| 신호 주기 | 경찰청 신호운영 데이터(공공데이터포털) | 미연동 — 통계 기본값 사용 |
| 고도(DEM) | 국토지리정보원 DEM, 브이월드 고도 API | 미연동 — 샘플 지형 사용 |
| 평소 교통 패턴 | TOPIS 시간대별 통계, 링크별 이력 축적 | 시간대 프로파일로 근사 |

### 실지도(OSM) 도로망으로 실행하기

인터넷이 되는 PC 에서 (이 개발 샌드박스는 OSM 서버 접근이 차단되어 있음):

```bash
pip install osmnx
python scripts/build_osm_graph.py "Gangnam-gu, Seoul, South Korea" -o backend/data/gangnam.json
# 고도 반영(선택): --dem <국토지리정보원 DEM 또는 SRTM GeoTIFF>
EV_NAV_GRAPH=backend/data/gangnam.json uvicorn backend.app.main:app
```

신호등 위치(OSM `highway=traffic_signals`)와 도로 등급·일방통행이 자동
반영되고, 신호 시뮬레이터·GLOSA·3D 뷰가 실도로망 위에서 그대로 동작합니다.

## 프로젝트 구조

```
backend/
  app/
    energy.py      # 물리 기반 전비 모델 (주행저항 + 회생 + 신호 정차)
    traffic.py     # 도로 등급·시간대별 흐름, 신호 통계 프로파일
    signals.py     # 신호 시뮬레이터 (주기·녹색·오프셋 결정적 현시)
    glosa.py       # GLOSA 녹색 신호 최적 속도 안내
    graph.py       # 도로망 그래프 (노드=교차로, 엣지=링크)
    routing.py     # 전위 보정 다익스트라 + 시간 의존 신호 판정 (eco / fastest)
    sample_data.py # 강남 일대 샘플 도로망 생성기
    regions.py     # 전국 시/도·시/군/구 근사 좌표 (주소 선택용)
    places.py      # 통합검색 내장 POI + 로컬 검색
    providers.py   # ITS·TOPIS·OSM·카카오 로컬 실데이터 커넥터
    vehicles.py    # 차종 물리 파라미터 프리셋
    main.py        # FastAPI 서버
  tests/           # 물리 타당성·경로 최적성 테스트
scripts/
  build_osm_graph.py # OSM 실도로망 다운로드 → 그래프 JSON 변환 CLI
frontend/
  index.html       # Leaflet 지도 UI (경로 비교·GLOSA·절약량 표시)
  3d.html          # Three.js 3D 주행 시뮬레이션 (신호 애니메이션·GLOSA HUD)
  vendor/          # Leaflet·Three.js 로컬 번들 (오프라인 동작)
```
