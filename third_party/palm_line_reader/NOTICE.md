# palm-line-reader 3종 손금 분할 보조 모델

Source: https://github.com/samuelwbarber/palm-line-reader
Pinned commit: bc48939f4deee6d8ff842bfde499396dab9c4830
License: MIT (LICENSE-MIT.txt, Copyright (c) 2026 Sam Barber)

| 파일 | 크기 | SHA256 |
|---|---|---|
| models/student_fp32.onnx | 22,329,537 | 3c02b88b82e54889d0ab2bf2ba108aec554a1b50759f7c7aaa45f2f114ed24ff |
| models/student_fp16.onnx | 11,284,720 | e2c9f826676b3aaf0a715f3087fcd4fc0b4dccd8c53de05fd26696a8399f8dd6 |

- 모델: SMP UNet + mit_b0 인코더(5.55M 파라미터), 입력 RGB 512×512, 출력 4클래스
  (배경·감정선·두뇌선·생명선). 운명선 클래스는 없다.
- 학습 라벨: 근적외선 손 스캔으로 학습한 큰 교사 모델(mit_b5)의 후처리 결과를
  r/PalmReading 사진 수천 장에 적용한 의사 라벨 + 일부 수작업 검수. 원본 사진과 교사
  모델은 상류 저장소에 포함되지 않았다. 상류 보고 검증 Dice는 세 선 평균 0.81이다.
- 상류 README 스스로 일반 사진에서 교사의 생명선이 짧게 그려지는 문제를 언급한다.
  이 저장소의 실사진 3장 비교에서도 생명선 대신 손바닥 중앙의 세로 주름을 생명선으로
  표시하는 경우가 있었다.
- 모델 가중치는 저장소에 넣지 않는다(`*.onnx`는 gitignore). `scripts/fetch_line_segmenter.py`가
  고정 커밋에서 내려받아 SHA256을 대조한 경우에만 저장한다.

변경 사항: Python onnxruntime CPU 추론, 고정 SHA256 외 파일 거부, 전체 사진·손 시야(또는
축소 시야)·좌우 반전 중 하나의 시야를 골라 첫 전체 사진 좌표계에 그린 PNG 오버레이만 생성,
평균 softmax 기준 미달 선 생략. 손금 해석·운세·사진 거부·운명선 판단에 사용하지 않는다.
