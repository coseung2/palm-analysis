# 4선 모델 학습·검증

이 디렉터리의 도구는 **오프라인 학습 기반**이다. 현재 VM 소비자나 `PALM_LINE_MODEL_PATH`를 변경하지 않는다. 새로운 네 종류 손금 모델의 실제 학습·정확도 개선·서비스 활성화를 완료한 상태가 아니다. 네트워크 구조는 작은 독립 U-Net 기준선이며, 사전학습 가중치를 내려받지 않는다. 최상의 모델이라는 근거는 없다.

## 데이터 선행 조건

- 실제 학습에 사용할 사진, 사람이 확인한 네 선의 폴리라인과 관측 상태, 이용 권한 검토가 필요하다. 사진 처리 동의는 학습·보관 동의를 대신하지 않는다.
- Roboflow DSTU의 수량·4선 라벨·CC BY 4.0 주장은 아직 실물 확인 전이다. 2026-10-19 공개 페이지는 HTTP 403이었고 브라우저 실행은 도구 장애로 불가했다. 해당 데이터를 내려받거나 학습하지 않았다.
- PLSU는 11K Hands 원본 1,039장을 증강한 이진 마스크 4,156쌍이다. 네 종류 정답으로 간주하지 않는다. 11K Hands의 학술 공정 이용 문구는 서비스 학습 허가가 아니다.
- 추정한 데이터 출처·권한을 `true`로 채우지 않는다. 아래 검사는 기록의 존재·일관성을 확인할 뿐, 법적 허가나 라벨의 진실성을 자동으로 입증하지 않는다.
- 실제 사진·라벨·결과·가중치는 Git에 넣지 않고 `data/` 아래 또는 별도 접근 통제된 장소에 둔다. 기존 체험 사진 저장소를 학습용으로 복사하거나 만료 정책을 변경하지 않는다. 학습 데이터의 보관 기간·삭제 정책은 별도로 정한다.

## 입력 manifest v1

UTF-8 JSON 파일과 그 파일 기준 상대경로의 JPEG/PNG/WebP를 사용한다. 파일 SHA256을 기록하고, EXIF 방향을 **라벨링 전에** 정규화한다. 좌표는 정규화한 전체 이미지의 좌상단 원점, x 오른쪽·y 아래, 범위 0..1이다. 잘라낸 이미지에 라벨링했으면 그 이미지 자체를 입력으로 사용한다.

필수 최상위 필드:

- `version`: `1`
- `purpose`: 실제 데이터는 `training`, 합성 실행 검증은 `smoke`
- `coordinate_space`: `normalized_image`
- `sources`: `id`, `url`, `license`, `reviewed_by`, `reviewed_at`, `permission_reference`, `training_allowed`(true), `deployment_allowed`(boolean)를 갖는 출처 목록
- `samples`: 아래 레코드의 목록

샘플 레코드:

- `id`, `person_id`, `original_id`: 비식별 ID. `person_id`는 모든 출처에서 같은 실제 사람에 같은 값을 쓴다. 양손·다른 세션도 하나의 split에 둔다. 증강본은 같은 `original_id`다. 출처별 별명으로 동일 인물을 구분하면 이 검사가 누수를 발견하지 못하므로 수집자가 대조해야 한다.
- `source`: 출처 ID
- `split`: `train` / `val` / `test`
- `domain`: `booth` / `public`
- `consent_reference`: 부스 사진은 별도 학습 동의 기록의 비식별 참조값이 필수. 동의서나 개인정보 원문을 넣지 않는다.
- `image`: manifest 기준 상대경로
- `sha256`: 이미지 파일의 SHA256
- `reviewed_by`: 실제 라벨 검수자 식별자
- `lines`: `life`, `head`, `heart`, `fate` 각각에 `state`, `points` 지정

선 라벨의 예시 형식(실제 정답 예시가 아니라 스키마 설명):

```json
{
  "state": "visible",
  "points": [[0.2, 0.3], [0.3, 0.4], [0.35, 0.6]]
}
```

- `visible`: 2~256개 순서 있는 곡선 점. 양 끝점만으로 곡률을 알 수 없다면 실제 경로를 추가 검수한다. 자동 보간을 정답으로 확정하지 않는다.
- `not_visible`: 관측할 수 있는 영역에서 해당 선이 드러나지 않음. `points: []`. 물리적으로 선이 없다는 단정이 아니다.
- `unclear`: 흐림·가림·경로 불명확. `points: []`. 학습 손실·평가에서 해당 채널을 제외한다. 미라벨 영역을 음성 예제로 바꾸지 않는다.

끊긴 선을 한 폴리라인으로 연결해 빈 구간을 발명하지 않는다. 현재 v1은 선마다 단일 경로만 지원하므로 분기·가려짐·분절이 단일 경로로 정확히 표현되지 않으면 해당 선을 `unclear`로 두거나 다음 라벨 버전에서 다중 경로 지원을 먼저 구현한다.

사람 단위로 split을 확정한 후에만 학습 증강을 한다. 검사는 사람·원본 ID·파일 해시·디코딩 픽셀 중복의 split 간 누수와 시험 세트 원본 중복을 차단한다. 근접 중복이나 잘못 부여한 사람 ID를 자동 검출하지는 않는다.

## 실행 환경

기본 앱 의존성 외에 `torch`, `numpy`, `scikit-image`가 필요하며 `pyproject.toml`의 `training` 선택 의존성에 버전을 명시했다. 기본 앱 설치는 이 패키지를 가져오지 않는다. 모델/지표 테스트는 선택 의존성이 없으면 skip을 명시하며, 학습 기능 검증 완료로 세지 않는다. VM에는 기존 CPU PyTorch 2.8.0과 ridge 의존성이 있다. 로컬 `.venv`에는 실행 검증용 CPU PyTorch 2.8.0을 추가했다. 이 CPU 설치는 RTX 4070 학습 환경이 아니다. 실제 GPU 학습 전 PyTorch 공식 설치 지침에 맞는 CUDA 빌드를 별도 환경에 설치하고 `torch.cuda.is_available()`를 확인한다. CUDA를 명시했는데 사용 불가하면 자동 CPU 대체 없이 실패한다.

메인 앱과 학습 환경을 분리하는 것을 권장한다. `requirements-lines.lock`과 `requirements-ridge.lock`에는 networkx 버전 차이가 있으므로 둘을 한 번에 덮어 설치하지 않는다. 실행 검증은 기존 환경에서 수행하고 서버 런타임 패키지를 갱신하지 않는다.

설치된 프로젝트에서 다음 모듈을 호출한다. Windows는 `.venv/Scripts/python.exe`, VM은 `.venv/bin/python`을 사용한다. 예시 경로의 데이터는 사용자가 준비해야 하며 저장소에 포함되지 않는다.

```bash
.venv/Scripts/python.exe -m palm_training.cli validate --manifest data/training/manifest.json
```

```bash
.venv/Scripts/python.exe -m palm_training.cli train --manifest data/training/manifest.json --output data/training/runs/baseline-01 --device cpu --epochs 50 --size 512
```

GPU 환경을 별도로 검증한 경우:

```bash
python -m palm_training.cli train --manifest data/training/manifest.json --output data/training/runs/candidate-01 --device cuda --epochs 50 --size 512
```

출력 디렉터리가 있으면 덮어쓰지 않는다. `candidate.pt`, `candidate.json`, `run.json`, `history.json`을 새 디렉터리에 쓴다. 사진·라벨·ID·인증값은 콘솔이나 결과 보고서에 출력하지 않는다. manifest 원문과 입력 사진은 학습자만 접근하도록 보호한다.

현재 전처리는 RGB 0..1, 정사각형 resize, 라벨 폴리라인 rasterization이다. 입력 종횡비를 바꾸므로 향후 추론 어댑터도 같은 변환과 역좌표 변환을 써야 한다. 해상도·선폭은 검증 세트로 결정한다. 이 변환을 기존 256px 이진 보조 모델과 혼용하지 않는다.

- 독립된 4개 sigmoid 출력: 교차부에 선 종류가 중복될 수 있다.
- BCE + Dice, 불명확 채널은 완전 제외.
- 학습에만 좌우 반전·작은 회전·밝기·대비 증강. 선이 화면 밖으로 잘릴 수 있는 경계 사례는 라벨 검수와 함께 점검한다.
- 고정 seed, deterministic 연산, validation loss 최저 epoch 저장.
- 선별 임계값은 validation에서만 0.3~0.7을 비교한다. 점수는 중심선 F1에서 미관측 선 오검출률을 뺀 값이다. 시험 세트로 epoch·임계값을 고르지 않는다.
- `candidate.pt`는 `weights_only=True`와 strict matching으로 로드하며 자동 다운로드·실행하지 않는다. 모델 파일 해시를 보고서에 남긴다.

## 별도 시험과 비교

```bash
.venv/Scripts/python.exe -m palm_training.cli evaluate --manifest data/training/manifest.json --checkpoint data/training/runs/candidate-01/candidate.pt --output data/training/runs/candidate-01/test.json --device cpu
```

시험은 `test` 중 `domain=booth`만 사용한다. 공개 사진으로 부스 성능을 대신하지 않는다. 지표는 선별 양성 Dice·허용 거리 내 골격 중심선 F1·미관측 선 오검출률이다. 빈 정답/빈 예측을 Dice=1로 넣어 점수를 부풀리지 않는다. 기본 중심선 허용 거리는 출력 해상도에서 2픽셀, 미관측 오검출의 최소 예측 면적은 0.1%다. 임계값과 선폭·출력 해상도·허용 거리를 명시하고 비교 전 고정한다. 지연은 전처리·외부 AI를 제외한 모델 실행 실측이며 첫 추론을 포함한다.

```bash
.venv/Scripts/python.exe -m palm_training.cli qualify --candidate-report data/training/runs/candidate-01/test.json --baseline-report data/training/runs/baseline-01/test.json --output data/training/runs/candidate-01/qualification.json
```

현재 보수적인 **임시 엔지니어링 기준**:

- 실제 학습용 출처의 서비스 반영 허가가 명시되어 있어야 한다. `smoke` 보고서는 차단한다.
- 같은 manifest·평가 프로토콜·구조, 서로 다른 후보 가중치의 비교만 받는다.
- 부스 시험 인물 20명 이상, 각 선에서 관측 양성 20개·미관측 음성 20개 이상. 각 상태에 서로 다른 사람 10명 이상이 필요하다.
- 선별 중심선 F1 0.8 이상, 미관측 오검출률 0.1 이하.
- 어느 선도 중심선 F1·Dice가 0.01 초과 하락하거나 미관측 오검출률이 증가하면 안 된다.
- 평균 중심선 F1이 최소 0.01 개선되어야 한다.

기준 미달은 종료코드 2다. 이 숫자들은 과학적으로 검증된 서비스 합격 기준이나 신뢰구간이 아니다. 시험 인원·통계적 불확실성·피부톤/기기별 성능·사진 품질을 추가로 검토해야 한다. 보고서는 로컬 실험 기록이지 서명된 배포 권한이 아니며, 편집된 보고서를 신뢰하는 보안 경계로 쓰지 않는다. 반복적인 시험 점수 비교로 시험셋에 과적합하지 않도록 최종 미사용 시험셋을 따로 유지한다.

통과해도 `eligible_for_review`일 뿐이다. **현재 상용/개발 AI 파이프라인과 비교해 더 좋다는 뜻이 아니다.** 이 도구의 비교는 동일 네트워크 학습 후보끼리의 기준선이며, 서비스 채택 전에는 현행 분석 경로도 같은 정답셋으로 별도 평가해야 한다.

## 서버 반영 경계

이 패키지는 `palm_backend`와 분리되어 있으며 HTTP 엔드포인트, 사진 수집, DB·시크릿 접근, 서비스 재시작, 활성 모델 경로 변경을 하지 않는다. VM에 소스를 반영해도 새 모델은 켜지지 않는다.

새 모델 활성화 전 필요한 일:

1. 출처/권한·실사진 검수 완료 → 실제 학습과 독립 시험.
2. 현행 분석 경로 대비 품질·오검출 개선을 동일 정답셋에서 확인.
3. 대상 ARM64 VM에서 CPU 지연·메모리·장시간 실행 측정.
4. 새 전처리/좌표계에 맞는 별도 추론 어댑터, 체크포인트 고정 해시, 제한된 실패 복구 구현.
5. 원본과 대조하는 보조 후보로 제한해 단계적으로 검증. 숫자 신뢰도·임의 운명선 생성 금지.
6. 기존 모델·환경 설정을 백업하고 개발 부스에서 확인한 뒤 사용자 승인 범위 내 반영. production 차단과 비용 한도는 유지.

## 이번 검증의 의미

테스트는 자체 생성한 도형으로 수행한다. 학습/역전파, 가중치 저장·재로딩, 4채널 평가, unknown 손실 제외, 누수·권한 검사, 합성 후보의 승격 차단이 작동하는지 확인하는 용도다. 합성 도형의 점수는 실제 손금 정확도의 증거가 아니며 서비스에 사용할 가중치가 아니다.

## 로컬 선 추적기와 의사라벨 학습 실험 (2026-10-25)

위의 검수 manifest 파이프라인과 **별개인 실험 경로**다. 서버·VM·활성 모델 경로는 바꾸지 않았고, 결과는 로컬 확인용이다.

### 추적 파이프라인 (`src/palm_backend/line_tracer.py`)

1. MediaPipe 21개 랜드마크로 손바닥을 유사변환해 512px 정규 좌표계에 놓는다(엄지가 오른쪽이 되도록 좌우 반전). u는 새끼 MCP(0)→검지 MCP(1), v는 MCP 선(0)→손목(1).
2. GrabCut으로 손바닥 마스크, 음영 평탄화 + Sato/Frangi 리지 증거. 평탄화 전 원시 리지 대비(`ABSOLUTE_CONTRAST`)로 신뢰 계수를 곱해, 주름이 없는 손바닥의 잡음이 선으로 정규화되지 않게 한다.
3. 선마다 해부학 통로(`LINES`)를 펼친 띠에서 국소정렬 DP로 가장 근거가 강한 연속 경로를 찾는다. 끝은 낮은 문턱(`EXTEND_TAU`)으로만 연장한다. 근거가 부족하면 그리지 않고 미검출로 둔다.
4. **감정선·두뇌선 공동 배정**: "두뇌선 먼저→감정선은 그 위", "감정선 먼저→두뇌선은 그 아래" 두 순서를 모두 추적한다. 상대 선 쪽 금지 영역에는 주름 폭(손바닥 폭 8%)만큼 여유를 둬 같은 주름의 가장자리를 타지 못하게 한다. 한 주름을 두 조각으로 나눈 배정은 무효로 하고, 감정선 먼저 배정은 근거 합이 `JOINT_MARGIN`(1.1배)을 넘을 때만 택한다. 그 뒤 생명선→운명선→태양선 순으로 사용된 주름을 피해 추적한다.
5. 선택적 증거 모델(`palm_training.line_model`)이 선 무관 주름 확률과 선별 확률을 주면 리지 증거와 결합한다. 감정선·두뇌선에는 선별 확률을 쓰지 않는다(`classes=0`, 아래 편향 참고). 운명선·태양선은 학습 주름 맵 비중을 35%로 낮춰 가는 세로 주름을 사진 필터 근거로 잡는다.
6. **보조선**(`trace_minor`): 생명선 바깥 엄지 두덩의 가로 주름(장해선, 최대 3개)과 감정선 위 손날 쪽 짧은 가로 주름(결혼선, 최대 2개)을 사진 필터 근거에서 여러 개 찾는다. 길이·방향·평균 근거·직선도(`MAX_WIGGLE`) 조건으로 피부 결을 거르고, 평행하게 쪼개진 조각은 하나로 합친다.

확인용 렌더링: `python scripts/trace_lines.py OUT_DIR PHOTO... [--model CHECKPOINT]`

### 학습 데이터

- **PLSU** (arXiv 2102.12127, 11K Hands 실사진 1,039장 + 사람이 그린 이진 주름 마스크). Google Drive `PLSU.zip` 161,982,242 B, SHA256 `4b87b0f2…6f751f`. 명시 라이선스 없음(학술 공개). 개인 실험용으로만 사용하며 배포 허가로 보지 않는다.
- **palm-line-reader** (github.com/samuelwbarber/palm-line-reader, MIT, commit `bc48939f`): heart/head/life 3선 ONNX. 의사라벨의 **선 종류 배정에만** 교사로 사용했다.
- Roboflow의 4선 라벨 데이터(예: `luke-ndvwm/palm_final_v1`, 2,959장, CC BY 4.0 표기)는 무료 계정 API 키가 필요해 받지 않았다. 업로더가 표기한 라이선스이며 이미지 출처는 별도 확인이 필요하다.

`palm_training.pseudolabel.build_plsu`: 사람이 그린 주름 마스크를 추적기 증거로 쓰고 교사가 선 종류를 정한 뒤, 추적된 구간을 씨앗으로 같은 주름을 따라 측지 확장한다. 라벨 픽셀은 항상 사람이 그린 주름 위에만 있고, 추적되지 않은 선은 unknown(손실 제외)이다. 결과: 1,037장(손 미검출 2장 제외), 선별 라벨 수 두뇌 1,037 / 생명 995 / 감정 901 / 운명 428 / 태양 137, `index.json` SHA256 `310cfce5…`. **선 종류는 기계 배정이므로 검수된 정답이 아니다.** 파일명에 인물 ID가 없어 같은 사람이 train/val 양쪽에 들어갈 수 있다.

### 모델과 평가

- `palm_training.train_lines`: SMP U-Net(MiT-B0, ImageNet 사전학습), 6채널(head/heart/life/fate/sun/crease) sigmoid, 기존 `masked_loss`(BCE+Dice, unknown 제외). 증강은 흰 배경→무작위 질감, 회전·축척, 노출·색온도·채도·감마, 음영, **해상도 0.18~1배 축소**, 블러·잡음·JPEG로 작은 폰 사진을 흉내낸다. RTX 4070, 60에폭 중 val loss 최저 44에폭 저장(`lines.pt` SHA256 `c19e0056…`).
- `palm_training.eval_lines`: val 103장에서 **사진만 보고** 추적한 중심선을 라벨 골격과 6px(손바닥 폭 약 2%) 허용으로 비교. 미검출은 recall 0.

| 증거 구성 | 두뇌선 | 감정선 | 생명선 | 운명선 | 태양선 |
|---|---|---|---|---|---|
| 필터만 | 0.71 | 0.55 | 0.65 | 0.64 | 0.45 |
| 교사(palm-line-reader) | 0.77 | 0.70 | 0.80 | 0.66 | 0.45 |
| 자체 모델 `lines-01` | 0.84 | 0.72 | 0.88 | 0.75 | 0.66 |
| 자체 + 교사 | 0.83 | 0.71 | 0.89 | 0.75 | 0.66 |
| **최종 추적기**(공동 배정) + 필터만 | 0.69 | 0.61 | 0.65 | 0.67 | 0.49 |
| **최종 추적기** + `lines-01` | 0.80 | 0.71 | 0.87 | 0.74 | 0.79 |
| 최종 추적기 + `lines-02` | 0.79 | 0.71 | 0.87 | 0.73 | 0.68 |

위 네 줄은 공동 배정 도입 **이전** 추적기 기준이고, 아래 세 줄이 최종 추적기다. 이 점수는 **구성 간 상대 비교**다. 라벨 선 종류가 같은 추적기·교사로 배정됐고 인물 누수 가능성이 있어 실제 정확도나 서비스 합격 근거가 아니다. 특히 PLSU 라벨은 이전 두뇌선 통로·교사 배정을 따르므로, 그 규칙에서 벗어나는 변경은 PLSU 점수가 낮게 나온다.

### 대상 사진 검증 (`palm_training.score_reference`)

사용자가 준 실사진 3장(학습 미사용)에 정답선을 직접 표시해 채점했다. 표시는 Claude가 대비 강조한 정규 좌표 영상과 원본 컬러 사진을 대조해 만들었고, 전문가 검수는 아니다. 사진과 정답 JSON은 `data/training/reference/`(Git 제외)에 랜드마크와 함께 둔다. `unclear`는 채점 제외, `not_visible`은 그리지 않아야 정답, 보이는 선은 8px(손바닥 폭 약 3%) 허용 중심선 F1, 놓치면 0이다.

| 사진 | 감정선 | 두뇌선 | 생명선 | 운명선 | 태양선 |
|---|---|---|---|---|---|
| 1 (386×518) | 불명확 | 1.00 | 1.00 | 불명확 | 없음 ✓ |
| 2 (301×400) | 0.69 | 0.89 | 0.99 | 1.00 | 없음 ✓ |
| 3 (480×640) | 0.82 | 0.90 | 1.00 | 불명확 | 없음 ✓ |

평균 0.94(최종 구성 `lines-01` + 공동 배정). 같은 추적기·기준에서 필터만 쓰면 0.83, 감정선·두뇌선에 선별 확률을 쓰면 0.83이다.

- **감정선/두뇌선 편향**: 교사(palm-line-reader)와 그 라벨로 학습한 `lines-01`의 선별 채널은 긴 가로 주름 하나를 왼쪽=감정선, 오른쪽=두뇌선으로 나눈다. 사진 2에서는 감정선이 두뇌선 왼쪽 절반에 그려졌다(F1 0.19). 그래서 두 선은 주름 채널과 해부학 공동 배정만 쓴다.
- **운명선·태양선**: 대비 강조·L/a*/G 채널 확대로 확인한 결과 운명선은 사진 2에만 뚜렷하다. 사진 3은 짧은 조각, 사진 1은 근거가 없다. 태양선은 세 장 모두 근거가 없다. 추적기는 사진 2의 운명선을 정확히 그리고(F1 1.00), 근거 없는 선은 그리지 않는다. 참고 도식처럼 모든 선을 채워 그리는 방식은 택하지 않았다.
- **사진 1 감정선**: 원본에서 가장 뚜렷한 가로 주름은 정규 y≈202~223 하나다. 그 위 감정선 자리에는 필터·주름 맵·육안 모두 근거가 없어 불명확으로 두었다. 손바닥 중앙의 밝은 반사 경계가 리지로 잡혀 "감정선 먼저" 배정과 점수가 비슷해지는 경우가 있어 `JOINT_MARGIN`을 두었다.
- **보조선**: 사진 3의 엄지 두덩 가로 주름 2개가 장해선으로 정확히 잡힌다. 사진 2의 2개는 옅지만 실제 주름 위에 있다. 결혼선은 세 장 모두 미검출이다. 보조선은 정답 표시·채점 대상이 아니며 육안 확인만 했다.

### 학습 데이터 라운드 비교

| 라벨 | 선 종류 배정 | 모델 | 대상 3장 평균 |
|---|---|---|---|
| `plsu_lines` | 사람 주름 마스크 + 추적기 + 교사 | `lines-01` (val loss 0.280) | **0.94** |
| `plsu_lines_v3` | 사람 주름 마스크 + 공동 배정 추적기, 교사 없음 | `lines-02` (val loss 0.311) | 0.72 |

교사 없이 해부학 규칙만으로 선 종류를 배정한 3차 라벨은 오히려 나빴다. 사진 2·3의 감정선을 놓쳤고, PLSU 일부에서는 넓은 두뇌선 통로가 감정선의 손날 쪽 구간을 가져갔다. 교사의 선 종류 정보는 편향이 있어도 독립 신호로 가치가 있어 최종 모델은 `lines-01`이다. `plsu_lines_v2`는 공동 배정 이전 규칙의 중간 결과다.

### 재현

```bash
# 별도 학습 환경 (CUDA PyTorch, mediapipe 0.10.18, onnxruntime, segmentation-models-pytorch 0.5.0)
uv venv data/training/venv --python 3.12
uv pip install --python data/training/venv/Scripts/python.exe torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
uv pip install --python data/training/venv/Scripts/python.exe mediapipe==0.10.18 numpy==1.26.4 opencv-contrib-python==4.11.0.86 scikit-image==0.25.2 scipy pillow segmentation-models-pytorch==0.5.0 timm onnxruntime-gpu==1.22.0
```

```bash
PYTHONPATH=src python -c "from palm_training.pseudolabel import build_plsu; from palm_training.line_model import load_evidence_model; build_plsu('data/training/external/plsu/PLSU', 'data/training/plsu_lines', load_evidence_model('data/training/external/palm-line-reader/repo/models/student_fp32.onnx'), shard=(0, 1))"
```

```bash
PYTHONPATH=src python -m palm_training.train_lines --data data/training/plsu_lines --output data/training/runs/lines-01 --epochs 60 --workers 3
```

```bash
PYTHONPATH=src python -m palm_training.eval_lines --data data/training/plsu_lines --photos data/training/external/plsu/PLSU/img --config filter= --config ours=data/training/runs/lines-01/lines.pt --output data/training/reports/val.json
```

```bash
PYTHONPATH=src python -m palm_training.score_reference --photos data/training/reference --reference data/training/reference/reference.json --model data/training/runs/lines-01/lines.pt
```

Windows에서는 데이터로더 워커마다 CUDA DLL이 올라가 페이징 파일 한도를 넘을 수 있으므로 워커를 3개 이하로 둔다. 의사라벨 생성은 CPU 전용이라 `shard=(i, n)`으로 나눠 병렬 실행할 수 있다.

### 서버 분석 경로 연결 (로컬 검증만, 2026-10-25)

`PALM_LINE_TRACER_MODEL_PATH`에 `lines-01/lines.pt`를 지정하면(`src/palm_backend/traced_lines.py`, SHA256 `c19e0056…98ce` 고정) 관찰 단계가 다음처럼 바뀐다. 지정하지 않으면 기존 동작 그대로다.

1. 정규화한 전체 사진에서 추적기를 먼저 실행한다(보조선 생략, `line_trace` 타이밍 단계).
2. 추적에 성공하면 추적선을 전체 사진에 그린 이미지와 "추적된 선" 목록을 AI에 보내고 trace는 빈 배열로 받는다. 이전 256px 실험 오버레이는 함께 보내지 않는다.
3. AI 응답 후 좌표를 교체한다(최대 24점 균등 추출). 추적된 life·head·heart는 AI 판정과 관계없이 visible로 두고 그린다. 추적된 fate는 AI도 visible로 판단할 때만 그린다. AI가 visible이라 했지만 추적되지 않은 선은 그리지 않는다. 프롬프트도 추적된 life·head·heart를 visible로 두고 그 주름을 기술하도록 바꿨다.
   - 근거(2026-10-25): 첫 VM 종단 실행에서 기준상 4선이 모두 보이는 사진 2의 3선을 AI가 unclear/not_visible로 판정해 1선만 그려졌다. PLSU 검증 103장에서 lines-01이 라벨 없는 곳에 선을 그린 횟수는 life 4·head 0·heart 0·fate 34라 fate만 AI 확인을 유지한다.
   - 대상 3장에서 visible 라벨의 life·head·heart는 모두 추적됐다(F1 0.69~1.0, 누락 없음). 같은 종단 판정에 새 규칙을 적용하면 사진 2는 life·head·heart 3선이 그려진다(fate는 AI가 not_visible로 판정해 제외). 바뀐 프롬프트에 대한 실제 AI 응답은 아직 확인하지 않았다.
4. 의존성 부재·손 미검출·해시 불일치·예외 시 `None`을 반환해 기존 AI 좌표 경로로 돌아간다.
5. 지연 단축(2026-10-25): 추적에 성공하면 Meijering 주름 지도를 보내지 않고, 관찰 호출의 추론 강도를 `PALM_OCX_TRACED_OBSERVATION_EFFORT`(기본 low)로 낮춘다. 해석 호출도 `PALM_OCX_NARRATION_EFFORT`(기본 low)를 명시한다. 추적 실패 시 관찰은 기존 `PALM_OCX_OBSERVATION_EFFORT`(기본 high)와 주름 지도를 그대로 쓴다. 근거: 2번째 VM 종단 실행에서 소비자 31.2초 중 관찰 호출이 19.9초였다.

로컬 검증: 학습 venv(CUDA torch, CPU로 추론)에서 서버 함수 `trace_lines`의 사진 좌표 출력을 저장된 랜드마크로 정규 좌표계에 되돌려 대상 3장을 채점했다. 4선 평균 0.918(오프라인 추적기 같은 기준 0.921, 감정선 사진 2는 24점 추출 후 0.69→0.64). 지연은 이 PC CPU에서 사진당 2.8~3.7초, 첫 호출은 import·모델 로드·검출기 시작으로 약 15초(디스크 콜드 상태에서 52초 관측)라 앱·클라우드 워커 시작 시 백그라운드 warm-up을 한다. 실제 AI 호출을 포함한 종단 실행과 VM(ARM64) 측정은 하지 않았다. VM 반영에는 mediapipe·opencv-contrib·scikit-image·scipy·segmentation-models-pytorch·timm 설치(ARM64 휠 확인), 체크포인트 배치, 지연·메모리 측정, 앱 경로의 `analysis_timeout_seconds`(45초) 내 여유 확인이 필요하다.

### 남은 일

- 사람이 선 종류까지 검수한 독립 시험셋(부스 사진, 학습 동의)으로 재평가.
- 선 종류 채널의 감정선/두뇌선 편향은 검수 라벨 또는 Roboflow 4선 라벨(무료 계정 API 키 필요)로 해결해야 한다. 키가 준비되면 `palm_final_v1`을 받아 선 종류 라벨을 교체하고 재학습한다.
- 대상 사진 정답은 3장, 표시자 1인(Claude)이다. 부스 사진으로 정답셋을 늘리고 사람이 검수해야 한다.
- 재운선·권력선은 다루지 않았다. 결혼선은 손날에 있어 정면 사진에서 근거가 약하다.
- 서버 코드 연결과 해시 고정은 했지만 VM에는 반영하지 않았다. VM(ARM64 CPU) 의존성·지연·메모리 측정이 먼저 필요하다.
