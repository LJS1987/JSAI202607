# 논문용 그래프 목록

수소-천연가스 혼소 SI 엔진 (DE12T, CR 13, CAM -108) — 1800 rpm / 80 kW 정출력 실험.
H₂ 혼합률(체적) 0 / 20 / 40%, λ = 1.0~1.6 (H₂ 40%는 1.9까지), 각 조건 점화시기 스윕.

- **최적점 정의**: 노킹(kp) 미발생 운전점 중 BTE 최대점
- 데이터 원본: `data/실험결과정리_raw.xlsx` (git 미포함) → `scripts/extract_data.py`로 정리
- 그래프 생성: `scripts/make_figures.py` (PNG 300 dpi + PDF 벡터)

## 점화시기 스윕 (λ별 패널, 빈 마커 = 노킹 발생점)

| 파일 | 내용 |
|---|---|
| fig01_sweep_bte | 점화시기에 따른 제동열효율(BTE) |
| fig02_sweep_nox | 점화시기에 따른 NOx [g/kWh] |
| fig03_sweep_thc | 점화시기에 따른 THC [g/kWh] |
| fig04_sweep_texh | 점화시기에 따른 배기가스 온도 |

## 최적점 비교 (x = λ)

| 파일 | 내용 |
|---|---|
| fig05_opt_bte | 최적점 BTE |
| fig06_opt_spark | 최적 점화시기 (MBT, 노킹 제약 반영) |
| fig07_opt_emissions | NOx / THC / CH₄ / CO |
| fig08_opt_intake_exhaust | MAP / 배기온도 / 체적효율 / CO₂ |
| fig09_opt_bte_nox_tradeoff | BTE–NOx 트레이드오프 |

색상: NG 100% 파랑(●), H₂ 20% 초록(■), H₂ 40% 빨강(▲) — 색각이상 안전 조합 검증 완료.
