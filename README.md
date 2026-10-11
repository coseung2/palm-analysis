# Palm Analysis Web App

손금 부스 아티팩트의 별빛·금빛 분위기를 옮긴 **로컬 운영자용 웹앱 + FastAPI 백엔드**입니다. 원본 아티팩트는 수정하지 않습니다.

## 웹앱

서버 실행 후 `http://127.0.0.1:8000/`에서 사용합니다. FastAPI가 프론트와 API를 같은 origin으로 제공합니다.

- 운영자가 `운영`에서 기존 운영자 키로 연결합니다. 키를 소스에 넣거나 브라우저 저장소에 보관하지 않습니다. 연결 해제/새로고침 시 메모리에서 사라집니다.
- 사진 촬영/선택 → 분석 → 오락용 전생 이야기 → 네 가지 손금 결과를 표시합니다.
- 서버의 실제 상태·오류를 따르며, 실패를 고정 성공 결과로 바꾸지 않습니다. 시연 모드는 실제 사진 검출이 아니라는 표시를 유지합니다.
- 재촬영/다음 손님/취소 시 기존 세션 삭제를 요청합니다. 삭제 확인에 실패하면 성공으로 표시하지 않습니다.
- 실제 AI 모드에서는 사진의 외부 서비스 전송 동의를 받아야 합니다. 숫자 신뢰도와 임의의 선 좌표는 표시하지 않습니다.
- 운영 설정의 제목·이야기 테마·잔상 대기 시간은 백엔드에 저장하며 다음 세션부터 적용합니다.

**운영자용 부스입니다. 운영자 키를 방문객에게 공유하지 마세요.** 아래 Cloudflare 배포는 사진을 전송하지 않는 시연 모드이며, 실제 AI 분석을 제공하지 않습니다. 기존 Python 서버의 사진 분석 경로는 로컬 환경용으로 유지합니다.

## Cloudflare + Supabase 배포

- URL: https://palm-analysis.mdownloader.workers.dev
- Cloudflare Worker `palm-analysis`가 같은 origin에서 정적 화면과 `/v1/*` API를 제공합니다.
- Supabase `palm-analysis` (`pyugqoogcoynvywihgym`)에 설정·세션·시연 결과를 저장합니다. 세션은 기본 1시간 후 접근 차단, 15분 cron 및 API 호출에서 만료 행 삭제입니다. 취소는 결과·요청 키를 즉시 제거합니다. DB 백업/WAL의 완전 삭제까지 보장하지 않습니다.
- 기존 시연 배포는 사진 없는 시연 전용입니다. 현재 소스의 `cloudflare/worker.mjs`는 별도 development 실제 모드도 지원합니다. `/health`의 `demo_without_photo: true`로 사진 선택·업로드를 비활성화합니다. 클라우드 분석 요청은 `{ "demo": true }` JSON만 허용합니다. 로컬 Python의 이미지 분석 요청 계약과 다릅니다.
- 테이블 RLS 활성화, `anon`·`authenticated` 테이블/RPC 권한 제거를 실제 DB에서 검증했습니다. `palm_booth` RPC는 SECURITY INVOKER이며 서버용 `service_role`만 호출합니다. 토큰 원문 대신 SHA-256 해시를 보관합니다.
- 세션 생성 한도·설정 버전·상태 변경은 DB 트랜잭션에서 직렬화합니다. Worker 인스턴스 메모리를 영구 저장소로 사용하지 않습니다.
- Infisical Development `/`의 4개 시크릿은 `scripts/with-infisical.ps1`로 필요한 로컬 자식 프로세스에만 주입합니다. 집 PC 기존 DPAPI 인증을 사용하고 사용자 로그인 세션에 의존하지 않습니다.
- Cloudflare 서버 시크릿은 `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `OPERATOR_KEY`입니다. 관리 액세스 토큰과 DB 비밀번호는 Worker에 설치하지 않습니다. 서버용 API 키는 관리 API에서 메모리로 읽어 stdin으로 주입합니다. 운영자 키는 기존 로컬 `.env`의 키를 사용하며 브라우저 코드에 포함하지 않습니다.
- 재배포: `npx --yes wrangler@4.149.0 deploy`. 시크릿 갱신은 `scripts/with-infisical.ps1`에서 Python `scripts/cloud_setup.py secrets`를 실행합니다. 갱신 전에 대상 계정·프로젝트를 확인하세요.
- 스키마 원본: `supabase/schemas/booth.sql`. CLI의 `migration new`가 `Unsupported Config Type`로 실패하여 최초 적용은 Management API로 수행했습니다. **마이그레이션 이력 파일은 생성되지 않았습니다.** 다음 스키마 변경 전 현 DB와 선언 파일을 비교하고 정상 CLI 환경에서 이력을 정리하세요. `cloud_setup.py apply`는 기존 테이블이 있으면 중단합니다.
- 실제 AI 활성화, 공개 방문객 인증, 비용 예산·속도 제한, 정밀 선 검출, 커스텀 도메인은 포함하지 않습니다. 시연 서버는 운영자 인증 뒤에만 결과를 생성합니다.

## 운영 전환 요구사항 변경 (2026-10-12)

- 방문객은 로그인 없이 사용합니다. 이전 계획의 운영자 로그인 의무는 이 요청으로 변경됐습니다. 설정·삭제 관리 권한은 방문객에게 공개하지 않습니다. 로컬 Python은 `PALM_PUBLIC_SESSIONS=true`에서 공개 시작/설정 조회를 제공하고 SQLite에 저장되는 전역 분당 시작 제한을 적용합니다(기본 6회). 재시작으로 제한이 초기화되지 않습니다. 기본값은 false이며 단일 프로세스·단일 worker 범위입니다. 브라우저에서 로그인 창 없이 준비 화면 진입 및 무인증 세션 생성 201을 확인했습니다.
- 별도 직접 유료 AI API 대신 기존 VM OCX를 사용합니다. 외부 자원 생성은 무료 범위에서만 허용됐습니다.
- Python `PALM_ANALYSIS_MODE=ocx`와 서버 전용 `PALM_OCX_BASE_URL`, `PALM_OCX_API_KEY`, `PALM_OCX_MODEL`을 지원합니다. 기존 VM 데이터 키·origin·모델을 승인된 Infisical Development에 저장·재조회했습니다. 브라우저나 평문 설정 파일에는 넣지 않았습니다.
- OCX 요청은 `/v1/responses`, `X-OpenCodex-API-Key`, `stream=true`, `store=false` 계약을 사용합니다. 관찰에는 EXIF를 제거한 JPEG만, 이야기 생성에는 관찰 JSON만 보냅니다. 스트림의 완료 이벤트·출력 구조를 검증하고 실패를 시연 결과로 대체하지 않습니다. `store=false`는 OCX/상류 공급자의 로그·보관 전체를 보장하지 않습니다.
- 기존 Windows 자격증명 저장소의 VM 데이터 키를 메모리에서만 사용해 모델 목록 조회 및 `gpt-6.1-sol` 합성 이미지 관찰을 검증했습니다. 실제 HTTP 200 스트림과 유효한 네 선 구조, 단색 사진 재촬영 판정을 확인했습니다. 실사진·이야기 생성·현장 품질·비용/할당량은 별도 검증해야 합니다.
- 카메라 미리보기·촬영·끄기·페이지 이동/숨김 시 트랙 해제 코드를 추가했습니다. 브라우저 pane은 카메라 접근을 차단하므로 실제 기기 촬영 성공은 미검증입니다. 차단 안내·사진 선택 대체 경로·375px 가로 넘침 없음은 확인했습니다.
- Cloudflare 시연에만 `PALM_PUBLIC_DEMO=true` 공개 시작 옵션을 추가했습니다. 설정 조회/시연 세션 생성만 공개되며 설정 변경은 운영자 인증, 세션 접근은 개별 토큰을 요구합니다. 세션 생성은 `PUBLIC_SESSION_LIMITER` 바인딩과 Cloudflare 클라이언트 주소가 없으면 차단합니다. 제한기는 전역 비용 한도를 대신하지 않습니다. 이 시연용 플래그·바인딩은 기존 시연 배포에 적용하지 않았습니다. 실제 모드는 별도 개발 URL과 DB 기반 요청 제한을 사용합니다.
- 이전 Supabase 로그인 모듈은 검증용 기반으로 남아 있으나 로그인 없는 체험의 완료 증거가 아닙니다.

### 개발 배포와 작업 큐·할당량·삭제 기반

개발 URL: https://palm-analysis-development.mdownloader.workers.dev

Chrome의 기존 로그인에서 Cloudflare Workers Free를 확인한 뒤 별도 개발 Worker를 배포했습니다. `PALM_RUNTIME_READY=true`, 부스당 UTC 일일 상류 호출 20회, 대기 2개, 실행 1개로 개발 체험을 활성화했습니다. 기존 시연 배포와 production 설정은 변경하지 않았습니다. 실제 배포 URL의 로그인 없는 진입·OCX 상태·설정 인증 차단·375px 레이아웃을 확인했습니다. 배포 URL에서 단색 합성 사진의 업로드→VM→OCX 재촬영 판정→취소 경로도 재검증했으며 성공한 검증의 소요 시간은 약 11.7초였습니다. 실사진 정확도·실기기 촬영·현장 평가를 대신하지 않습니다.

최종 자동화 검증: Python 65개, JavaScript/SQL 38개 통과. Python에는 기존 Starlette 사용 중단 경고 1건이 있습니다.

`supabase/schemas/jobs.sql`은 신규 `palm_runtime` 비공개 스키마 후보입니다. 기존 시연 테이블과 별개이며 기존 DB에 적용하지 않았습니다. 부스는 기본 비활성, 호출 한도 0입니다. 요청당 관찰/이야기 2회를 미리 예약하고 단계별 dispatch로 차감합니다. 이는 금액 예산이 아니라 **상류 호출 횟수 한도**입니다. 사용자가 선택한 VM OCX의 구독/할당량/보관 조건 확인은 별도 항목입니다.

작업 중복 키+사진 해시, 부스 잠금, 작업 lease, 단계별 호출 fencing, 취소 결과 차단, 재시작 복구, 사진 삭제 lease/재처리를 구현했습니다. dispatch 이후 실행 여부가 불명확한 작업은 `interrupted_unknown`으로 종료하며 자동 호출을 반복하지 않습니다. 공급자 호출과 DB 커밋 사이의 exactly-once는 보장하지 않습니다.

`src/palm_backend/worker.py`는 소비자 핵심이며 `cloud_worker.py`는 개발 RPC/비공개 사진 저장소 어댑터입니다. VM 사용자 서비스 `palm-analysis-development.service`에 설치했고, 서비스 active 및 실제 RPC 연결을 확인했습니다. 개발 런타임 플래그는 true입니다. production은 차단 상태입니다. 공개 gateway 코드는 `cloudflare/visitor.mjs`입니다. 임의 테스트 부스·단색 합성 사진으로 gateway→비공개 업로드→동일 요청 재전송→VM→OCX 재촬영→실제 사진 삭제→세션 격리를 검증하고 테스트 행을 정리했습니다. 이후 개발 Worker를 별도로 배포·활성화했습니다. 운영 출시를 완료한 상태는 아닙니다. SQL은 PGlite 0.3.14의 격리 PostgreSQL로 실행 검증했습니다. 실제 Supabase와 다중 프로세스 동시성 검증을 대체하지 않습니다. `package.json`/`package-lock.json`에 고정 개발 의존성을 기록했습니다. `npm ci --ignore-scripts` 후 `npm test`로 Worker·SQL 테스트를 모두 실행하며 의존성 누락을 성공/skip으로 숨기지 않습니다.

2026-10-12 승인 후 자원 변경: 대상 조직 Free 플랜과 전체 조회 가능한 활성 프로젝트 수를 재확인한 뒤 `palm-analysis-development` (`ihkbmxwidahgbrvxmrrk`)를 생성했습니다. 응답 상태 ACTIVE_HEALTHY를 확인했으며 기존 시연 프로젝트는 변경하지 않았습니다. 새 DB 비밀번호·ref·URL은 Infisical Development `/`의 `PALM_DEV_DB_PASSWORD`, `PALM_DEV_PROJECT_REF`, `PALM_DEV_SUPABASE_URL`로 저장·재조회했습니다. 개발 DB에 검증한 `jobs.sql`, `worker_api.sql`, `visitor_api.sql`을 별도 체크섬 이력으로 적용하고 RLS·브라우저 실행 권한 차단을 확인했습니다. `palm-uploads`는 비공개, 5 MiB, JPEG/PNG/WebP 제한입니다. DB-backed 작업 큐를 사용하므로 별도 Cloudflare Queues 자원을 만들지 않았습니다. 별도 개발 Worker는 배포·활성화했으며 운영 출시·production 활성화는 하지 않았습니다.

사용자 승인에 따라 기존 공유 머신 `devspace-testauram-vm`의 palm-analysis 프로젝트 역할을 Viewer에서 Member로 변경했습니다. 기본 제공 역할 중 쓰기를 제공하는 가장 낮은 역할이며 Admin은 아닙니다. 공유 PC/VM 양쪽에 적용됩니다. 새 인증 생성·회전은 하지 않았습니다. PC 머신 인증의 실제 쓰기는 `PALM_RUNTIME_READY=false` 생성/재조회로 검증했습니다. VM 쪽도 기존 Agent/래퍼로 신규 시크릿 조회를 검증했고 실제 소비자의 환경에서 관리 토큰·DB 비밀번호·Infisical 토큰이 제외된 것을 확인했습니다.

기존 VM OCX 데이터 키·origin·모델은 Infisical의 `PALM_OCX_API_KEY`, `PALM_OCX_BASE_URL`, `PALM_OCX_MODEL`로 저장·재조회했습니다. 인증을 새로 만들거나 회전하지 않았으며 값은 로그/파일에 출력하지 않았습니다. OCX origin은 Tailscale 사설 주소이므로 공용 Cloudflare Worker가 직접 호출하는 구조로 사용하지 않습니다. VM 소비자가 호출해야 합니다. 기존 `scripts/cloud_setup.py secrets`는 시연 전용으로 유지합니다.

운영·복구 절차와 남은 출시 차단 항목은 [OPERATIONS.md](OPERATIONS.md)를 참고하세요. 스키마 체크섬 이력은 공식 Supabase CLI 이력 복구와 별개이며, CLI 오류·실사진 품질·현장 검증은 미완료입니다.

## 실제 운영 전환 — 기반 구현 및 격리 통합 검증

방문객 로그인은 사용자 요청에 따라 제외했습니다. 개발 부스의 세션 격리·설정 변경 보호를 구현했지만, 실기기·실사진·현장 검증과 운영 전환 판단은 남아 있습니다.

- 기본 Worker `palm-analysis`는 기존 **시연 환경**입니다. 기존 DB ref는 시연 전용으로 취급합니다.
- `wrangler.jsonc`에 `development`, `staging`, `production`을 별도 Worker 이름으로 선언했습니다. development만 별도 DB와 Worker를 생성·배포했습니다. staging/production은 설정 선언만 있고 배포하지 않았습니다.
- development는 workers.dev 공개 체험과 `PALM_RUNTIME_READY=true`로 활성화됐고 cron 없이 VM 소비자가 정리합니다. staging/production은 API와 공개 workers.dev가 비활성입니다. 기존 시연 DB ref·시크릿을 복사하지 마세요. 기존 `cloud_setup.py secrets`는 시연 배포용이며 새 환경용으로 사용하지 않습니다.
- API는 명시적인 환경 이름, 문자열 `PALM_API_ENABLED=true`, `PALM_SUPABASE_PROJECT_REF`, 정확히 일치하는 HTTPS Supabase URL, 서버 시크릿이 모두 있어야 실행합니다. development/staging에서 기존 시연 DB를 지정하면 차단합니다. 기존 운영자 키 방식은 demo에서만 허용합니다.
- 로그인 없는 development는 배포된 `PALM_AUTH_MODE=public_booth` 경로를 사용합니다. 초기 인증 기반으로 남아 있는 `PALM_AUTH_MODE=supabase`는 `SUPABASE_PUBLISHABLE_KEY`와 서버의 `PALM_OPERATOR_ALLOWLIST`가 필요합니다. 허용 목록 형식은 `[{"user_id":"<Auth 사용자 UUID>","role":"admin 또는 operator","booths":["<부스 UUID>"]}]`입니다. 실제 허용 계정은 아직 등록하지 않았습니다.
- `GET /v1/operator`는 Bearer 액세스 토큰을 Supabase Auth 서버에서 검증한 뒤 허용된 사용자·부스·역할만 반환합니다. 익명 사용자, 비허용 사용자, 만료 토큰, Auth 장애는 차단합니다. user_metadata의 역할/부스 정보는 권한 판단에 사용하지 않습니다.
- `requireBooth` 정책에서 일반 운영자는 설정 변경이 금지되고 admin도 자신의 허용 부스에만 접근합니다. **정책 단위 테스트는 통과했지만 부스별 DB RPC에 연결된 상태는 아닙니다.** Supabase 인증 모드에서는 기존 전역 설정/세션 RPC와 cron을 차단합니다. 로그인 화면·부스별 DB 연결 완료 전까지 실제 체험을 시작할 수 없습니다.
- production은 플래그와 시크릿이 있어도 코드에서 차단합니다. 운영자 로그인·허용 목록·부스 격리 검증 이후 별도 변경으로 해제해야 합니다.
- `/health`는 설정이 부족하면 `503`와 `status=not_ready`를 반환합니다. `ok`는 로컬 설정 검사 통과만 의미하며 DB 연결 성공을 증명하지 않습니다.
- 이 보호는 잘못된 연결 설정을 방지하기 위한 것입니다. 관리 권한을 가진 사람이 설정과 코드를 바꾸는 것을 막는 보안 경계는 아닙니다. development와 staging 사이의 별도 DB 매핑도 아직 확정하지 않았습니다.

로컬 Cloudflare 개발 미리보기는 `.claude/launch.json`의 `palm-cloud-development`를 사용합니다. 기본 상태에서는 화면만 제공하고 API는 503으로 차단합니다. 실제 시연 DB·유료 AI에 연결하지 않습니다.

Worker 회귀 테스트:

```bash
node --test cloudflare/worker.test.mjs cloudflare/operators.test.mjs
```

2026-10-12 읽기 전용 DB 감사: 대상 프로젝트 이름/ref와 ACTIVE_HEALTHY 확인, 선언 SQL과 열 자료형/RPC 본문 일치, 테이블 RLS 및 브라우저 역할 접근 차단, RPC SECURITY INVOKER 확인. **마이그레이션 이력 테이블은 존재하지 않습니다.** 인덱스·기본값·제약조건 전체 비교와 기준 마이그레이션 정리는 아직 남아 있습니다. 감사 도구는 `scripts/audit_schema.py`이며 기존 Infisical 래퍼에서 `-CommandArguments`를 명시해 실행합니다. 세션 행·사진·비밀값을 조회하지 않습니다.

남은 작업: 카메라 권한 허용 후 실기기 촬영, 실사진 품질·현장 검증, 상류 공급자 이용·보관 조건 확인, 운영 관측·알림 및 공식 마이그레이션 이력 정리. 2026-10-12 사용자 요청으로 개발은 여기서 중단하고 현재 상태를 로컬 Git에 보관합니다. 기존 개발 서비스·자원은 삭제하거나 종료하지 않았습니다.

## 범위

- FastAPI HTTP API, SQLite 세션·결과·운영 설정 보관
- 운영자 인증으로 세션 생성, 세션별 토큰으로 분석·조회·취소
- JPEG/PNG/WebP 실제 디코딩, MIME 검증, 용량·해상도 제한, EXIF 제거
- `demo`: 외부 호출 없이 고정된 **시연용 결과** 반환. 손 존재·흐림·손금 검출을 하지 않음
- `claude`: 외부 사진 처리 동의를 받은 세션만 사진 전송. 관찰과 해석을 별도 호출
- 모호하거나 보이지 않는 선은 해석 보류. 신뢰도 숫자·수명/건강 예측 없음
- 중복 요청 방지, 세션당 최대 3회 분석, 동시 분석·보관 세션 한도
- 취소 시 진행 중 호출 중단 및 결과 제거. 늦게 도착한 결과는 저장하지 않음
- 서버 재시작 시 남은 `analyzing` 세션을 재시도 가능한 `failed`로 복구
- 설정 변경은 버전 비교로 충돌 방지. 체험 중인 세션의 설정은 바뀌지 않음

**전용 손금 검출 모델이나 과학적으로 검증된 분석기가 아닙니다.** Claude 모드도 비보정 시각 묘사 + 오락용 창작입니다. 프론트는 `result.is_demo`와 `result.disclaimer`를 반드시 표시해야 합니다. 프롬프트의 안전 지침은 유해한 출력을 완전히 보장하는 필터가 아니므로, 공개 운영 전 실사진·출력 품질 검증이 필요합니다.

## 설치와 실행 (Windows / Git Bash)

Python 3.12 이상. 이 프로젝트에는 `.venv`와 개발 의존성이 설치되어 있습니다. 새 환경에서는:

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python.exe -m pip install -r requirements.lock -e '.[dev]'
```

초기화 스크립트로 `.env.example`에서 로컬 `.env`를 생성합니다. 운영자 키는 암호학적 난수로 생성하며 화면에 출력하지 않습니다. 기존 `.env`는 덮어쓰지 않습니다. 키를 저장소나 공유 문서에 올리지 마세요.

```bash
.venv/Scripts/python.exe scripts/init_env.py
```

```bash
.venv/Scripts/python.exe -m uvicorn palm_backend.app:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

- 상태: `http://127.0.0.1:8000/health`
- API 명세/테스트: `http://127.0.0.1:8000/docs`
- 기본 모드는 `demo`. 로컬 운영자 키만 초기화하며, 실제 외부 AI API 키는 생성·읽기·저장하지 않았습니다.
- 브라우저 프론트를 붙일 때만 `.env`의 `PALM_CORS_ORIGINS`에 정확한 origin을 JSON 배열로 넣습니다. `*`는 금지입니다.

### 실제 이미지 분석 활성화

`.env`에서 아래 세 값을 설정합니다.

```dotenv
PALM_ANALYSIS_MODE=claude
PALM_ANTHROPIC_API_KEY=<운영자가 직접 설정>
PALM_ANTHROPIC_MODEL=claude-opus-5-5
```

세션 생성 시 `external_processing_consent: true`가 필요합니다. **사진이 외부 AI 서비스로 전달된다는 설명과 동의 UI는 호출하는 프론트/운영자가 책임집니다.** boolean만으로 이용자가 실제로 동의했는지 서버가 입증할 수는 없습니다. provider의 보관 정책·이용 조건도 공개 운영 전에 확인하세요.

실제 모드에는 요청당 관찰 1회 + 이야기 생성 1회가 발생합니다. 재촬영 판정이면 이야기 호출은 하지 않습니다. 자동 유료 재시도·무동의 외부 전송·실패를 데모 성공으로 바꾸는 fallback은 없습니다. 계정의 모델 접근 권한과 비용은 별도 확인이 필요합니다.

## API 계약

모든 응답은 `Cache-Control: no-store`. 토큰은 URL이나 요청 본문이 아니라 `Authorization: Bearer ...`에 보냅니다.

| Method | 경로 | 인증 | 역할 |
|---|---|---|---|
| GET | `/health` | 없음 | 상태와 실행 모드 |
| GET | `/v1/config` | 운영자 | 설정 조회 |
| PUT | `/v1/config` | 운영자 | 동일 `version`으로 수정 요청; 성공 시 버전 증가 |
| POST | `/v1/sessions` | 운영자 | 체험 생성, 세션 접근 토큰 1회 반환 |
| GET | `/v1/sessions/{id}` | 해당 세션 토큰 | 상태·결과 조회 |
| POST | `/v1/sessions/{id}/analysis` | 해당 세션 토큰 | 사진 검증 → 관찰 → 해석 → 결과 저장 |
| DELETE | `/v1/sessions/{id}` | 해당 세션 토큰 | 취소·결과 제거, 진행 중 호출 중단 요청 |

### 세션 생성

본문:

```json
{"external_processing_consent": false}
```

응답(201)은 `id`, `access_token`, `status`, `created_at`, `expires_at`, `config`, `attempts`, `result`, `error`, `external_processing_consent`를 포함합니다. `access_token`은 생성 응답에만 포함됩니다. 서버에는 토큰 원문 대신 SHA-256 해시가 저장됩니다.

**운영자 키를 공개 방문객 페이지·아티팩트 코드에 넣지 마세요.** 신뢰할 수 있는 운영자 도구나 로컬 부스 제어 프로세스가 세션을 생성하고 세션 토큰만 체험 화면에 전달해야 합니다. 세션 토큰도 해당 사진·결과에 접근할 수 있는 비밀입니다.

### 사진 분석

- `Content-Type`: `image/jpeg`, `image/png`, `image/webp`
- 본문: **사진 바이너리 자체**. multipart나 JSON/base64가 아닙니다.
- `Idempotency-Key`: 영숫자, `_`, `-`로 구성된 8–128자 문자열
- 기본 제한: 5 MiB, 단일 프레임, 최소 짧은 변 256 px, 최대 1,600만 화소
- EXIF 회전 반영 → RGB → 최대 1024 px JPEG로 정규화한 뒤 분석

분석 요청은 최대 설정된 timeout 동안 결과를 기다립니다. 첫 요청 중 연결이 끊겨도 서버가 살아 있는 동안 이미 시작된 작업은 이어지고 GET으로 조회할 수 있습니다. **내구성 있는 작업 큐는 아닙니다.** 서버 종료·재시작을 넘어 작업이 계속되지는 않습니다.

같은 키 + 같은 정규화 사진을 다시 보내면 기존 상태/결과를 반환하며 추가 모델 호출을 하지 않습니다. 진행 중 중복은 202, 완료/실패는 200입니다. 같은 키 + 다른 사진은 409입니다. 재촬영이나 명시적 재시도에는 **새 키**를 사용합니다. 완료된 세션에서 다른 사진을 분석하려면 새 세션을 만듭니다. 같은 손의 다른 사진을 동일 인물로 식별하지 않습니다.

### 상태

```text
awaiting_image → analyzing → completed
                    └────→ failed → analyzing (새 요청 키, 재시도 가능 오류만)
모든 상태 ────────────────→ cancelled
만료: 조회 불가(404), 주기 정리
```

세션 결과 구조:

```json
{
  "mode": "demo",
  "is_demo": true,
  "hand": "unknown",
  "lines": [
    {
      "name": "life",
      "visibility": "unclear",
      "trait": "시연 예시 · 실제 검출 아님",
      "description": "사진 속 손금은 분석하지 않았습니다. 부스 연결 확인용 예시입니다.",
      "reading": "시연용 문구입니다. 실제 손금 해석은 보류합니다."
    }
  ],
  "visions": ["오락용 창작 문구"],
  "disclaimer": "손금 해석과 전생 이야기는 오락용 창작이며, 건강·수명·미래에 대한 사실 판단이 아닙니다.",
  "config_version": 1
}
```

위 예시는 구조 설명을 위해 선 하나만 표시했습니다. 실제 결과에는 `life`, `head`, `heart`, `fate` 네 개가 각각 한 번씩 포함됩니다. `visibility`는 `visible` / `unclear` / `not_visible`; `hand`는 `left` / `right` / `unknown`입니다. `visibility`는 검증된 검출 신뢰도가 아닙니다.

분석 자체의 실패는 세션 `status=failed`, `error={code,message,retryable}`로 반환합니다. 요청·인증·업로드 오류는 4xx와 동일한 `error` 구조를 반환합니다. 200만 보고 성공으로 표시하지 말고 반드시 `status`를 확인하세요.

대표 오류: `retake_required`, `analysis_timeout`, `provider_busy`, `provider_configuration`, `interrupted`, `invalid_provider_result`, `analysis_busy`, `attempt_limit`, `consent_required`, `session_not_found`, `idempotency_conflict`.

프론트는 내부 요청 ID·준비 단계를 별도 사용자 버튼으로 만들 필요가 없습니다. 시작과 재시도는 사용자 결정, 분석·기록은 시스템 상태입니다. ‘다음 손님’에서는 이전 세션 취소와 로컬 토큰 제거 후 새 세션을 사용하세요.

## 보관·운영 한계

- 원본·정규화 사진은 요청/작업 메모리에만 존재합니다. 업로드 폴더·사진 DB·이미지 URL은 없습니다.
- 결과·관찰 문구·동의 여부·설정 스냅샷은 SQLite에 저장됩니다. 기본 TTL 1시간, 만료 즉시 접근 차단, 정상 실행 중 15초마다 행 정리. 시작할 때도 정리합니다.
- 취소 시 결과/오류/사진 해시/요청 키 제거. 세션 최소 메타데이터는 TTL까지 남습니다.
- DB 행 삭제는 디스크·WAL·백업의 보안 완전 삭제를 보장하지 않습니다. DB는 민감 데이터로 취급하고 접근 권한·암호화·백업 보관 정책을 별도 적용하세요.
- **로컬 단일 프로세스 / 단일 worker** 전용입니다. SQLite + 메모리 작업 관리라 다중 worker, 다중 인스턴스, 서버리스, Vercel 임시 파일시스템에서는 운영하지 마세요.
- 공개 배포 전: 공유 DB·내구성 큐, TLS, 운영자/단말 인증, 요청 속도 제한, 전체 비용 예산, 관측/알림, 동의·삭제 정책 검토가 필요합니다. 현재 동시/시도/세션 한도는 일일 비용 제한이 아닙니다.
- QR 공개 공유, 이메일·이름 수집, 프린터, 정밀 선 좌표 검출은 포함하지 않습니다.
- 운영자 키는 서버 시작 시 필수입니다. CORS는 인증을 대체하지 않습니다. 기본 바인딩은 loopback입니다.

## 검증

```bash
.venv/Scripts/python.exe -m pytest -q
```

```bash
.venv/Scripts/python.exe -m ruff check src tests
```

인메모리 ASGI 통합 테스트와 임시 SQLite를 사용합니다. 사진은 테스트에서 생성하는 단색 이미지이며 실제 손 사진이 아닙니다. Claude 어댑터는 HTTP 모킹으로 요청 형식과 실패 처리만 검증합니다. 실제 모델 정확도·외부 계정 연결·현장 성능은 미검증입니다. 웹앱은 격리된 demo 서버와 합성 PNG 사진으로 운영자 인증 실패/성공, 설정 저장, 업로드→결과 4개, 재촬영·취소, 연결 해제·새로고침, 375px 모바일 가로 넘침 없음까지 브라우저 통합 검증했습니다. 실제 손 사진이나 유료 AI 호출은 사용하지 않았습니다.

실제 API 형식 근거:
- https://platform.claude.com/docs/en/api/messages/create
- https://platform.claude.com/docs/en/build-with-claude/structured-outputs
