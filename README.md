# EV 전비 최적 내비게이션 (JSAI202607)

대한민국 도로 지도, 교통신호, 평소 교통 흐름을 고려해 **전비(km/kWh)·연비(km/L)를
극대화하는 경로**를 안내하는 내비게이션 프로토타입입니다. 같은 출발지·도착지에
대해 **최소 시간 경로**와 **전비/연비 최적 경로**를 함께 계산해 절약량과
추가 소요 시간을 비교해 보여줍니다. 전기차뿐 아니라 가솔린·디젤 차량도
선택할 수 있으며, 신호에 걸리지 않는 속도(GLOSA)와 연비에 유리한 순항 속도를
함께 안내합니다.

![구조] 백엔드 FastAPI(경로 엔진) + 프론트엔드 Leaflet 지도 UI

## 빠른 시작

```bash
pip install -r requirements.txt
uvicorn backend.app.main:app --reload
# 브라우저에서 http://localhost:8000 접속
```

- **출발지**: `현재 위치 사용` 버튼(브라우저 Geolocation) 또는 지도 클릭
- **도착지**: 통합검색(장소·역·지역 키워드) 또는 주소로 찾기(시/도 → 시/군/구 선택)
- 차종(EV 4종: 아이오닉5/EV6/모델3/레이EV, ICE 2종: 쏘나타 가솔린/싼타페 디젤)과
  출발 시각을 바꾸면 결과가 즉시 갱신됩니다. ICE 선택 시 결과가 kWh/km·kWh
  대신 L/km·L 단위로 표시됩니다.
- 데모 도로망(강남 일대) 밖의 목적지를 고르면 가장 가까운 도로망 지점으로
  안내하며 경고를 표시합니다.
- **3D 주행 시뮬레이션**: 경로 계산 후 `🚗 3D 주행 시뮬레이션 보기`를 누르면
  Three.js 기반 3D 뷰(`/3d`)에서 차량이 전비 경로를 주행합니다 — 신호등
  현시가 실시간 애니메이션되고, GLOSA 권장 속도로 감속해 무정차 통과하는
  과정과 에너지 절약량, 그리고 **연비 최적 순항 속도**를 HUD 로 보여줍니다.
  체이스/버드뷰, 1×/5×/20× 배속.
- **실주행 GPS 기록**(`/live`): 폰 브라우저로 열어 실제 주행 중 GPS를 추적,
  신호 교차로 근처 위치만 서버에 기록합니다. 쌓인 기록으로 개인화된 신호
  타이밍을 추정합니다 — 아래 "개인 GPS 신호학습" 참고.
첫 실행 시 서울 강남 일대를 근사한 샘플 도로망(`backend/data/sample_graph.json`)이
자동 생성됩니다.

테스트:

```bash
python -m pytest backend/tests
```

## 동작 원리

### 1. 물리 기반 전비/연비 모델 (`backend/app/energy.py`)

도로 링크별 소비 에너지를 주행저항 방정식으로 계산합니다. EV·가솔린·디젤
모두 같은 수식을 쓰되 차량 프리셋(`vehicles.py`)의 계수 해석만 다릅니다.

- **구름저항** `Crr·m·g·cosθ` + **공기저항** `½·ρ·Cd·A·v²` + **경사** `m·g·Δh`
- 구동 시 구동계 종합효율(η, EV≈0.90 / ICE는 엔진 열효율×구동계≈0.25~0.32)로
  나누고, 내리막에서는 **회생제동 회수율**(η_regen, EV≈0.65 / ICE=0.0 —
  회생 없이 연료분사만 끊는 근사)을 곱해 EV는 음수(충전), ICE는 0으로 처리
- 공조 등 **보조 전력**은 주행·대기 시간에 비례해 가산 — ICE 는 여기에 공회전
  연료소비 환산분이 포함돼(수 kW 급) 신호 대기 손실이 EV보다 훨씬 큽니다
- ICE 는 계산된 Wh 를 `wh_per_liter`(연료 발열량 환산)로 나눠 리터로 표시

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

### 2-2. 연비 최적 속도 (`energy.optimal_cruise_speed_ms`)

구름저항은 속도 무관, 공기저항(∝v²)과 보조전력/공회전 비용(거리당 1/v)의
트레이드오프만으로 소비/거리 최소점을 해석적으로 구합니다:
`v* = (P_aux · η_drive / (ρ·Cd·A)) ** (1/3)`. 차량마다 고정된 상수 하나이며
(도로 구간과 무관), `/api/vehicles`·경로 응답의 `eco_speed_kmh`로 노출되고
현재 도로 등급 제한속도를 넘지 않도록 구간별로 잘립니다. **주의**: 이 모델의
단순화(부하 무관 상수 효율)를 그대로 반영한 값이라 제조사 공인연비 시험의
"최적속도"와는 다를 수 있습니다 — 앱 자체 물리 근사 기준의 참고값입니다.

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
| `GET /api/vehicles` | 차종 프리셋 목록(EV/가솔린/디젤), `eco_speed_kmh` 포함 |
| `POST /api/trip/ping` | 실주행 GPS 핑 기록 (`/live`) — 신호 노드 근처만 저장 |
| `POST /api/trip/relearn` | 누적 GPS 로그로 개인 신호 타이밍 추정 재계산 |
| `GET /` | 지도 UI |
| `GET /3d` | 3D 주행 시뮬레이션 |
| `GET /live` | 실주행 GPS 기록 |

## 실서비스 데이터 연동 로드맵 (`backend/app/providers.py`)

데모는 합성 도로망과 평균 프로파일로 동작하며, 실데이터 연동 지점이 코드에
준비되어 있습니다. API 키는 환경 변수(`.env`, git 미추적)로 주입합니다.

| 데이터 | 소스 | 상태 |
|---|---|---|
| 전국 도로망 | OpenStreetMap (`scripts/build_osm_graph.py`, osmnx) 또는 표준노드링크 | **CLI 구현** — 아래 사용법 참고 |
| 실시간 소통 속도 | 국가교통정보센터 ITS 오픈 API (`providers.fetch_its_link_speeds`), 서울 TOPIS | 커넥터 구현, 키 필요 |
| 장소 검색(지오코딩) | 카카오 로컬 API (`providers.search_kakao_places`) | 커넥터 구현, 키 없으면 내장 POI·시군구 폴백 |
| 신호등 위치 | OSM `highway=traffic_signals` 태그 | 로더에 포함 |
| 신호 주기 | 경찰청 신호운영 데이터(공공데이터포털, 서울 한정) (`providers.fetch_police_signal_timings`) | 커넥터 구현, 키·검증 필요 — 아래 참고 |
| 고도(DEM) | 국토지리정보원 DEM, 브이월드 고도 API | 미연동 — 샘플 지형 사용 |
| 평소 교통 패턴 | TOPIS 시간대별 통계, 링크별 이력 축적 | 시간대 프로파일로 근사 |

### 경찰청 신호운영 데이터로 실제 신호 타이밍 반영하기

`POLICE_API_KEY`(공공데이터포털 발급키)와 `POLICE_REGION_CODE`(지역코드, 예:
서울 `L01`)를 설정하면, 서버 시작 후 첫 요청 때 해당 지역 교차로의 실제
주기·옵셋·현시 정보를 조회해 `SignalSimulator` 에 주입합니다. 그래프의
신호 노드와는 좌표 최근접 매칭(기본 30m 이내)으로 연결되며, 매칭되지 않거나
키가 없는 노드는 기존 결정적 가상 시뮬레이션으로 자동 폴백합니다 — 경로
탐색·GLOSA 로직은 실측/가상 여부와 무관하게 동일하게 동작합니다.

```bash
POLICE_API_KEY=<발급받은 키> POLICE_REGION_CODE=L01 uvicorn backend.app.main:app
```

**주의**: `providers.py` 의 교차로 위치 조회(`getCrossRoadInfoList`)는
공공데이터포털 문서로 확인된 엔드포인트지만, 신호 운영계획(주기/옵셋/현시별
시간) 오퍼레이션명(`POLICE_PLAN_OPERATION`, 기본값 `getPlanCRTodInfo`)과
응답 필드명(`CYCLE`/`OFFSET`/`A_RING_1..8`)은 포털의 상세 기술문서(키 발급
후 다운로드 가능)로 아직 검증하지 못한 자리표시자입니다. 실제 키를 받으면
기술문서와 대조해 `POLICE_PLAN_OPERATION` 환경변수 또는
`providers._fetch_police_signal_plans` 의 파싱 부분만 맞춰 고치면 됩니다.

**커버리지**: 경찰청 교차로기반/계획정보서비스는 **서울시 주요 교차로 한정**입니다.
서울 밖 지역(OSM 실도로망을 확장해도 마찬가지)은 매칭될 실데이터가 없어
`SignalSimulator` 의 결정적 가상 시뮬레이션으로 자동 폴백합니다 — 서비스가
끊기거나 오류가 나지는 않고, 다만 그 지역 신호는 실측이 아닌 통계적 근사치로
표시됩니다.

### 개인 GPS 신호학습 (`/live`, `tripdb.py`, `signal_learning.py`)

경찰청 데이터가 없는 지역(서울 밖)을 위해, 실제 내가 다닌 기록으로 신호
타이밍을 스스로 추정합니다. `/live` 페이지에서 `watchPosition`으로 위치를
추적하며 신호 교차로 40m 이내 위치만 `POST /api/trip/ping`으로 서버에
전송·SQLite(`backend/data/trips.db`)에 누적합니다. 같은 교차로를 여러 번
지난 기록을 "방문" 단위로 묶어(`signal_learning.extract_visits`, 2분 이상
간격이면 새 방문) 정차/통과 여부를 신호가 하루 주기로 반복된다는 가정 아래
(주기·녹색시간·오프셋) 그리드 서치로 설명력이 가장 높은 조합을 찾습니다
(`estimate_timing`). 표본이 10회 미만이거나 설명 적중률이 75% 미만이면
추정하지 않고 기존 가상 시뮬레이션 폴백을 유지합니다.

우선순위는 **경찰청 실측 > 개인 학습 추정 > 가상 시뮬레이션**이며, `POST
/api/trip/relearn`으로 누적된 로그를 반영해 강제 재계산할 수 있습니다.
혼자 쓰는 경우 표본이 쌓이기까지(같은 교차로를 열 번 이상 지나야 함) 수 주가
걸릴 수 있습니다.

### (로드맵) C-ITS SPaT 실시간 신호 연동

티맵 등이 대전-세종 C-ITS 시범구간에서 보여주는 신호 잔여시간은 이 프로젝트가
쓰는 공공데이터포털 배치 API와는 다른 종류입니다 — 노변장치(RSU)가 초 단위로
쏘는 SPaT(Signal Phase and Timing) V2X 메시지이며, 대전-세종 C-ITS
시범사업센터(042-722-6191~2)와 별도 협약이 있어야 접근할 수 있어 셀프서비스
키 발급 대상이 아닙니다. 향후 실데이터 연동을 대전-세종 구간까지 넓히려면
이 협약이 선행 조건이며, 연동 시에는 배치 API처럼 `providers.py` 에 커넥터를
추가하고 `SignalSimulator.real_timings` 인터페이스는 그대로 재사용하면 됩니다
(초 단위 갱신이므로 캐시 주기만 훨씬 짧게 가져가야 함).

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
    energy.py          # 물리 기반 전비/연비 모델 (주행저항 + 회생/공회전 + 신호 정차 + 연비 최적 속도)
    traffic.py         # 도로 등급·시간대별 흐름, 신호 통계 프로파일
    signals.py         # 신호 시뮬레이터 (주기·녹색·오프셋 결정적 현시, 실측 타이밍 오버라이드)
    signal_learning.py # 개인 GPS 로그 → 방문 추출·신호 타이밍 그리드서치 추정
    tripdb.py          # 개인 GPS 로그 SQLite 저장소
    glosa.py           # GLOSA 녹색 신호 최적 속도 안내
    graph.py           # 도로망 그래프 (노드=교차로, 엣지=링크), 최근접 신호 노드 매칭
    routing.py         # 전위 보정 다익스트라 + 시간 의존 신호 판정 (eco / fastest)
    sample_data.py     # 강남 일대 샘플 도로망 생성기
    regions.py         # 전국 시/도·시/군/구 근사 좌표 (주소 선택용)
    places.py          # 통합검색 내장 POI + 로컬 검색
    providers.py       # ITS·TOPIS·OSM·카카오 로컬·경찰청 실데이터 커넥터
    vehicles.py        # 차종 물리 파라미터 프리셋 (EV/가솔린/디젤)
    main.py            # FastAPI 서버
  tests/               # 물리 타당성·경로 최적성·신호학습·API 테스트
scripts/
  build_osm_graph.py # OSM 실도로망 다운로드 → 그래프 JSON 변환 CLI
frontend/
  index.html       # Leaflet 지도 UI (경로 비교·GLOSA·절약량 표시, EV/ICE 단위 전환)
  3d.html          # Three.js 3D 주행 시뮬레이션 (신호 애니메이션·GLOSA·연비 최적 속도 HUD)
  live.html        # 실주행 GPS 기록 페이지
  vendor/          # Leaflet·Three.js 로컬 번들 (오프라인 동작)
```
