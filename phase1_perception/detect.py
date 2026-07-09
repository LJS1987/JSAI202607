"""
Phase 1 인지(Perception) 첫 실습:
주행 영상(휴대폰/블랙박스)에 YOLO 객체 검출 + 차선 인식을 돌려보는 스크립트.

사용법:
    python detect.py 주행영상.mp4                # 결과를 주행영상_result.mp4 로 저장
    python detect.py 주행영상.mp4 --show        # 처리하면서 화면에도 표시 (q로 종료)
    python detect.py 주행영상.mp4 -o out.mp4    # 저장 파일명 지정
    python detect.py 주행영상.mp4 --no-lane     # 차선 인식 끄고 YOLO만

- YOLO: 학습이 끝난 yolo11n 모델을 자동 다운로드해서 차량/보행자/신호등 등을 검출
- 차선 인식: 고전 컴퓨터비전 방식 (Canny 엣지 + 허프 변환)
  → 딥러닝이 아니라서 곡선/야간/역광에 약하지만, 원리를 배우기에 가장 좋다
"""

import argparse
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO


def region_of_interest(edges: np.ndarray) -> np.ndarray:
    """화면에서 차선이 있을 법한 영역(하단 사다리꼴)만 남기고 나머지는 지운다.

    하늘, 가로수, 옆 차선 건물 등에서 나오는 엣지를 걸러내기 위한 마스크.
    카메라 장착 위치에 따라 아래 비율(0.45, 0.6 등)은 조정이 필요할 수 있다.
    """
    h, w = edges.shape
    polygon = np.array([[
        (int(w * 0.05), h),            # 왼쪽 아래
        (int(w * 0.45), int(h * 0.6)), # 왼쪽 위
        (int(w * 0.55), int(h * 0.6)), # 오른쪽 위
        (int(w * 0.95), h),            # 오른쪽 아래
    ]], dtype=np.int32)
    mask = np.zeros_like(edges)
    cv2.fillPoly(mask, polygon, 255)
    return cv2.bitwise_and(edges, mask)


def average_line(lines: list, h: int) -> tuple | None:
    """같은 쪽(왼쪽 또는 오른쪽)으로 분류된 여러 선분을 하나의 대표 직선으로 평균낸다.

    반환: 화면 맨 아래(y=h)부터 화면 62% 높이까지 이어지는 선의 양 끝점.
    """
    if not lines:
        return None
    slopes, intercepts = [], []
    for x1, y1, x2, y2 in lines:
        slope = (y2 - y1) / (x2 - x1)
        slopes.append(slope)
        intercepts.append(y1 - slope * x1)
    slope = np.mean(slopes)
    intercept = np.mean(intercepts)
    y1, y2 = h, int(h * 0.62)
    x1 = int((y1 - intercept) / slope)
    x2 = int((y2 - intercept) / slope)
    return (x1, y1), (x2, y2)


def detect_lanes(frame: np.ndarray) -> np.ndarray:
    """한 프레임에서 좌/우 차선을 찾아 초록색 선과 주행 영역을 그려서 반환한다."""
    h, w = frame.shape[:2]

    # 1) 흑백 변환 + 블러: 색 정보를 버리고 노이즈를 줄인다
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)

    # 2) Canny 엣지: 밝기가 급격히 변하는 곳(차선 경계)만 남긴다
    edges = cv2.Canny(blur, 50, 150)

    # 3) 관심 영역(도로 부분)만 남긴다
    roi = region_of_interest(edges)

    # 4) 허프 변환: 엣지 점들을 직선 후보로 묶는다
    lines = cv2.HoughLinesP(roi, rho=2, theta=np.pi / 180, threshold=50,
                            minLineLength=40, maxLineGap=100)

    # 5) 기울기로 왼쪽/오른쪽 차선을 분류
    #    (영상 좌표는 y가 아래로 갈수록 커지므로, 왼쪽 차선은 기울기가 음수)
    left, right = [], []
    if lines is not None:
        # OpenCV 버전에 따라 (N,1,4) 또는 (N,4) 형태로 반환되므로 통일한다
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            if x2 == x1:  # 수직선은 기울기 계산 불가 → 제외
                continue
            slope = (y2 - y1) / (x2 - x1)
            if abs(slope) < 0.4:  # 거의 수평인 선은 차선이 아님 (그림자, 정지선 등)
                continue
            if slope < 0 and x1 < w * 0.55:
                left.append((x1, y1, x2, y2))
            elif slope > 0 and x1 > w * 0.45:
                right.append((x1, y1, x2, y2))

    left_lane = average_line(left, h)
    right_lane = average_line(right, h)

    # 6) 결과를 반투명 오버레이로 그린다
    overlay = frame.copy()
    for lane in (left_lane, right_lane):
        if lane:
            cv2.line(overlay, lane[0], lane[1], (0, 255, 0), 8)
    if left_lane and right_lane:  # 양쪽 다 찾으면 주행 영역을 채운다
        pts = np.array([left_lane[0], left_lane[1], right_lane[1], right_lane[0]],
                       dtype=np.int32)
        cv2.fillPoly(overlay, [pts], (0, 180, 0))
    return cv2.addWeighted(overlay, 0.35, frame, 0.65, 0)


def main():
    parser = argparse.ArgumentParser(description="주행 영상 YOLO 객체 검출 + 차선 인식")
    parser.add_argument("video", help="입력 영상 파일 (mp4, avi 등)")
    parser.add_argument("-o", "--output", help="결과 저장 파일명 (기본: 입력명_result.mp4)")
    parser.add_argument("--model", default="yolo11n.pt",
                        help="YOLO 모델 (기본 yolo11n.pt, 정확도를 원하면 yolo11s.pt)")
    parser.add_argument("--show", action="store_true", help="처리하면서 화면에 표시")
    parser.add_argument("--no-lane", action="store_true", help="차선 인식 비활성화")
    args = parser.parse_args()

    video_path = Path(args.video)
    if not video_path.exists():
        raise SystemExit(f"영상 파일을 찾을 수 없습니다: {video_path}")
    out_path = args.output or str(video_path.with_name(video_path.stem + "_result.mp4"))

    model = YOLO(args.model)  # 처음 실행 시 모델 파일(~6MB) 자동 다운로드

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))

    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1

        # 차선 인식 (고전 CV)
        if not args.no_lane:
            frame = detect_lanes(frame)

        # YOLO 객체 검출: 차량, 보행자, 자전거, 신호등 등 (COCO 80종)
        results = model(frame, verbose=False)
        frame = results[0].plot(img=frame)  # 검출 박스를 프레임 위에 그린다

        writer.write(frame)
        if args.show:
            cv2.imshow("perception", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
        if frame_idx % 30 == 0:
            print(f"진행: {frame_idx}/{total} 프레임")

    cap.release()
    writer.release()
    cv2.destroyAllWindows()
    print(f"완료! 결과 저장: {out_path}")


if __name__ == "__main__":
    main()
