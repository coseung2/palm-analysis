# palm-line-reader 학습 팩 (업그레이드판)

`src/palm_backend/line_segmenter.py`가 쓰는 3종 손금 분할 모델을 다시 학습하기 위한 코드다.
[samuelwbarber/palm-line-reader](https://github.com/samuelwbarber/palm-line-reader)
(`bc48939`, MIT, `LICENSE`)의 `training/`과 `pipeline/label_tool.py`를 가져와 고쳤다.
원본 그대로의 상태는 바로 이전 커밋에 있다. 원래 설계 문서는 `plan.md`, 학습 데이터 후보는
[`DATASETS.md`](DATASETS.md)에 정리했다.

**학습된 새 모델은 아직 없다.** 원본 학습 사진과 teacher 체크포인트가 상류에 공개되지 않아서,
데이터를 먼저 모아야 한다. 이 변경은 학습·검수·평가 도구를 준비한 것이다.

## 왜 고쳤나: 실사진 3장에서 본 문제

| 관찰 | 원인으로 본 것 | 바꾼 것 |
|---|---|---|
| 생명선이 없거나, 손바닥 중앙의 세로 주름(운명선 자리)을 생명선으로 표시 | teacher 의사 라벨의 짧은 생명선(상류 `plan.md`에 언급), 세 선 평균 점수로 고른 체크포인트 | 생명선 손실 가중치 2배(`--class_weights 1,1,1,2`), 가장 약한 선 기준 체크포인트 선택(`--select_metric min_line_dice`), 의심 라벨 순위화(`audit_labels.py`) |
| 손바닥 접사는 그대로 넣으면 거의 아무것도 못 찾음. 패딩으로 축소해야 검출 | 학습 변형이 크기 0.85~1.0, 회전 ±10°뿐 | 축소(0.55~0.9 + 패딩)·접사(30~60% 크롭)·회전 ±25°·흐림·노이즈·JPEG·노출 변형(`build_train_transform(strong=True)`) |
| 정확도 0.81이 생명선 약점을 가림 | 세 선 평균 Dice 한 숫자만 보고 | 선별 Dice·clDice·단일 연결 비율, 태그별(접사·어두움 등) 분석(`evaluate.py`) |
| 운명선을 아예 모름 | 4클래스(배경+3선) 고정 | `--num_lines 4`와 라벨 도구의 운명선(4번, 노랑) |

## 흐름

```bash
cd ml/palm_line_reader/training
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124  # GPU에 맞게
pip install -r requirements.txt

# 1) 의사 라벨 검수 우선순위: 생명선이 짧음/곧음/두뇌선과 동떨어짐 → 위쪽
python audit_labels.py --data_dir data --out audit.csv

# 2) audit.csv 위쪽부터 수정·승인·거절 (운명선은 4번 키)
python ../label_tool.py --data_dir data

# 3) 학습 (3선, 기본값이 업그레이드 설정)
python train.py --data_dir data --out_dir runs/exp3 --epochs 150 --batch_size 16
#    운명선까지: 마스크에 4번이 충분히 칠해진 뒤
python train.py --data_dir data --out_dir runs/exp4 --num_lines 4 --class_weights 1,1,1,2,1.5
#    원본 exp2 설정과 비교(ablation)
python train.py --data_dir data --out_dir runs/exp2-repro --no-strong_aug --class_weights "" --select_metric fg_dice

# 4) 내보내기 (checkpoint의 num_lines를 읽음)
python export_onnx.py --checkpoint runs/exp3/checkpoints/best.pt --out exported/student.onnx

# 5) 하드 테스트 세트에서 선별 평가 (학습에 쓰지 않은 접사·어두운·회전 사진)
python evaluate.py --model exported/student.onnx --data_dir hard_set --tags hard_set/tags.csv --mirror_tta
```

새 모델을 앱에 쓰려면 `src/palm_backend/line_segmenter.py`의 `MODEL_SHA256`에 해시를 추가하고
`PALM_LINE_SEGMENTER_PATH`로 지정한다. 4선 모델은 출력 채널이 5개라 앱 쪽 `LINES`/`COLORS`와
프롬프트 문구도 함께 바꿔야 한다(현재 앱은 3선 전용).

## 검증한 것 / 안 한 것

- CPU·합성 24장으로 3선·4선 각각 2 epoch 학습 → 체크포인트 → ONNX 내보내기(fp32 parity OK) →
  `evaluate.py`·`audit_labels.py`까지 끝까지 실행됨. 합성 데이터라 점수 자체는 의미 없다.
- `tests/test_training_upgrades.py`: 라벨 검수 규칙(중앙 세로 "생명선" 탐지), 클래스 가중치,
  강한 변형의 크기·라벨 값 보존. `pytest ml/palm_line_reader/tests`.
- 실제 데이터 학습, 새 설정이 실사진 정확도를 올리는지는 **검증하지 않았다.**
- 상류 fp16 내보내기 parity 기준(1e-2)은 짧게 학습한 모델에서 초과(0.0137)할 수 있다. 상류 기존 동작이다.
