# 손금 선 학습 데이터 후보 (2026-10-19 조사)

웹 검색 결과 요약만으로 작성했다. 이 개발 환경에서는 각 페이지를 직접 열 수 없어서
**라이선스·규모·라벨 형식을 내려받기 전에 원문에서 다시 확인해야 한다.** 사람 손 사진은
생체 정보이므로 연구용/비상업 조건, 재배포 금지, 얼굴·문신 등 식별 정보 포함 여부를 먼저 본다.

## 1. 손금 선 라벨이 있는 데이터

| 이름 | 규모 | 라벨 | 라이선스·조건 | 쓰는 법 |
|---|---|---|---|---|
| [Roboflow · Palm lines recognition (DSTU)](https://universe.roboflow.com/dstu-dfliv/palm-lines-recognition) | 약 2,959장 | 키포인트: 감정·두뇌·생명·**운명선** | CC BY 4.0 (검색 결과 기준) | 키포인트를 이어 폴리라인으로 그리면 4선 마스크가 된다(굵기 9px, `training/dataset.py` 형식). 운명선 학습(`--num_lines 4`)에 가장 유력한 후보 |
| [Roboflow · Palm Line Detection (Palm Reading Test)](https://universe.roboflow.com/palm-reading-test/palm-line-detection-9zzh0) | 약 110장 | 바운딩 박스: 감정·두뇌·생명선 등 | CC BY 4.0 (검색 결과 기준) | 박스라 마스크로 바로 쓸 수 없다. 의사 라벨의 선 종류 검증용 정도로만 쓴다 |
| [Efficient Palm-Line Segmentation (arXiv 2102.12127)](https://arxiv.org/pdf/2102.12127) 데이터 | 4,156쌍(증강 포함) | 비트맵 마스크(Supervisely) | 논문상 "과학 목적 공개 예정", 링크 `link.sun-asterisk.vn/palmlinedataset` | 원본 사진은 11K Hands 기반. 링크 생존과 라이선스를 확인해야 한다. 기존 `yeonsumia/palmistry` 보조 모델과 같은 계열 논문이다 |
| [Mendeley · palmistry 영감 데이터 (10.17632/9nhck5x748)](https://data.mendeley.com/datasets/9nhck5x748) | 미확인 | 12개 클래스 분류(선 특징) | 미확인 | 분류 라벨이라 분할 학습엔 직접 쓰기 어렵다. 11K Hands·BMPD·COEP 기반 |
| [MuntahaShams/palm-line-detection](https://github.com/MuntahaShams/palm-line-detection), [parkjichung/palm-line-detection](https://github.com/parkjichung/palm-line-detection) | 미확인 | 객체 검출(4선) | 저장소 확인 필요 | `data/` 폴더 공개 여부를 확인한다 |

## 2. 라벨 없는 손바닥 사진 (의사 라벨·도메인 확장용)

`generate_pseudo_labels.py`(teacher) 또는 현재 학생 모델로 의사 라벨을 만들고
`training/audit_labels.py` → `label_tool.py` 검수 흐름에 넣는 용도.

| 이름 | 규모 | 특징 | 조건 |
|---|---|---|---|
| [11K Hands (Afifi)](https://arxiv.org/pdf/1711.04322) | 11,076장, 190명, 1600×1200 | 손바닥/손등, 성별·나이·피부색 메타데이터. 균일한 흰 배경 | 학술 공정 이용(공식 라이선스 문서 미확인). [Lancaster ICVL 목록](https://wp.lancs.ac.uk/icvl/?p=968)에서 `sites.google.com/view/11khands` 링크 |
| [Tongji MPD (모바일 손금)](https://cslinzhang.github.io/MobilePalmPrint/) | 16,000장 | 여러 브랜드 스마트폰 촬영. **부스 촬영 조건과 가장 비슷** | 연구용 신청 형식으로 알려짐. 라벨은 ROI 키포인트이며 손금 선이 아니다 |
| [Tongji Contactless](https://cslinzhang.github.io/ContactlessPalm/contactlesspalm.pdf) | 12,000장, 600손 | 전용 비접촉 장비 | 연구용 |
| IITD Touchless | 약 2,600장, 230명 | 실내 비접촉 | 연구용 |
| CASIA Multispectral | 손바닥 가시광 4,800장 | 다중 파장 | 연구용 |
| [Kaggle · Open Palm Hand Images](https://www.kaggle.com/datasets/unidpro/open-palm-hand-images) | "500,000장"으로 소개 | 판매 업체 샘플일 가능성이 있음 | 상업 라이선스·샘플 범위 확인 필요 |

## 3. 합성 데이터

- [Canny2Palm (arXiv 2505.04922)](https://arxiv.org/html/2505.04922v1): 경계 지도에서 사실적인 손금 이미지를 생성해 대규모 사전학습에 쓰는 방법. 원하는 선 형태를 넣어 생성하면 마스크가 자동으로 따라온다. 특히 **생명선이 엄지를 감싸는 다양한 형태**를 충분히 만들 수 있다. 공개 코드·가중치 여부는 확인이 필요하다.

## 4. 부스 자체 데이터

실제 운영 분포와 가장 가깝지만, 현재 부스는 사진을 분석 후 삭제하도록 설계돼 있다.
수집하려면 **학습 사용에 대한 별도 명시 동의, 보관 기간, 삭제 요청 경로**를 새로 설계해야 하며
이번 변경에는 포함하지 않았다.

## 추천 순서

1. **DSTU 키포인트 데이터(CC BY 4.0)** → 폴리라인 마스크로 변환해 4선(운명선 포함) 라벨의 출발점으로 쓴다. 라이선스를 먼저 원문에서 확인한다.
2. **Tongji MPD**(스마트폰 사진) + 현재 학생 모델/teacher로 만든 의사 라벨 → `audit_labels.py`로 생명선이 의심스러운 라벨부터 검수한다.
3. 위 데이터에서 접사·어두움·흐림·회전 사진 100~200장을 골라 **하드 테스트 세트**(`evaluate.py --tags`)를 만든다. 학습에는 쓰지 않는다.
