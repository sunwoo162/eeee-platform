# EEEE Core 재설계 구현 계획

> 이 계획은 승인된 설계 문서
> `docs/superpowers/specs/2026-10-15-eeee-core-redesign-design.md` 및
> `docs/superpowers/specs/2026-10-15-eeee-core-redesign-design.ko.md`를
> 구현하기 위한 실행 순서다.

## 목표

EEEE를 다음 구조로 완성한다.

```text
Desktop Shell ──localhost API──> EEEE Core ──> Ollama
                                      │
                                      ├── SQLite transcript/memory/state
                                      ├── policy/router/events
                                      └── 필요할 때만 capability worker
```

이번 계획의 완료 대상은 EEEE Core와 Desktop Shell이다. Chat History,
ISEOL, ChatGPT Web 자동화, 외부 provider connector 자체 개발은 Core가
안정화된 뒤에 다시 시작한다.

## 작업 원칙

- 작업 디렉터리는 `C:\Users\user\Documents\eeee-core-redesign`를 사용한다.
- 현재 `main`의 사용자 변경과 별도 plugin 작업을 이 브랜치에 섞지 않는다.
- 기존 project/request/run/memory 테이블과 endpoint를 파괴적으로 지우지 않는다.
- 새 대화 경로가 실제로 통과하기 전까지 legacy project 경로를 삭제하지 않는다.
- Core가 기본 provider를 자동으로 ChatGPT Web로 바꾸지 않는다.
- 각 단계는 코드와 해당 단계의 테스트를 같은 변경 단위로 만든다.
- 완료 보고에서 결정론적 테스트와 실제 Ollama/Desktop 테스트를 분리한다.

## 변경하지 않는 영역

다음 영역은 EEEE Core v1이 acceptance를 통과할 때까지 기능 변경을 하지 않는다.

- `apps/eeee/app/agent/iseol_runtime.py`
- `apps/eeee/app/agent/chatgpt_web_runtime.py`
- `apps/eeee/app/agent/openhands_runtime.py`
- `packages/iseol`
- `eeee-chat-history-plugin` worktree
- 외부 provider의 실제 업무 API 구현

기존 코드가 새 Core API와 충돌할 때만 compatibility adapter 또는 lazy factory를
추가한다.

## Phase 0 — 기준선 고정과 격리

### 작업

1. 현재 브랜치에서 `apps/eeee` 테스트를 문서화된 위치에서 실행한다.
2. baseline 결과를 다음 증거 등급으로 기록한다.
   - deterministic: 기존 Python unit/API/contract suite
   - local runtime: 아직 미실행이면 `not run`
   - packaged desktop: 아직 미실행이면 `not run`
   - live provider/connector: 아직 미실행이면 `not run`
   - user-flow: 아직 미실행이면 `not run`
3. `apps/eeee`의 테스트 기준 working directory와 명령을 README 또는 계획에
   기록한다.
4. 기존 SQLite 파일의 schema/table 목록과 데이터 경로를 snapshot으로 저장한다.

### 확인 대상

- `apps/eeee/README.md`
- `apps/eeee/pyproject.toml`
- `apps/eeee/tests/`
- `apps/eeee/app/storage/sqlite.py`
- `apps/eeee/app/config.py`

### 완료 조건

- 기준선 명령이 재현 가능하다.
- 기존 DB를 삭제하지 않고 현재 table 목록을 확인했다.
- baseline을 전체 완성으로 표현하지 않는다.

## Phase 1 — Core 설정과 사용자 데이터 경로

### 변경 파일

- `apps/eeee/app/config.py`
- `apps/eeee/.env.example`
- `apps/eeee/app/core/__init__.py` 신규
- `apps/eeee/app/core/paths.py` 신규
- `apps/eeee/app/core/lock.py` 신규
- `apps/eeee/tests/test_config.py` 신규 또는 확장
- `apps/eeee/tests/core/test_paths.py` 신규
- `apps/eeee/tests/core/test_lock.py` 신규

### 작업

1. 현재 상대경로 기본값인 `data_dir = Path(".gleave")`를 사용자별 안정적인
   EEEE 데이터 경로로 변경한다.
2. Windows 기본 경로는 `%LOCALAPPDATA%` 아래로 정하고, test/portable 실행을
   위한 명시적인 override를 제공한다.
3. `EEEE_OLLAMA_BASE_URL`, `EEEE_OLLAMA_MODEL`, connection timeout, generation
   timeout, maximum context tokens를 설정 모델에 추가한다.
4. `agent_runtime` 기본값을 새 local conversation 경로가 선택되도록 바꾸되,
   기존 project runtime 선택은 compatibility 설정으로 보존한다.
5. data directory에 Core process lock을 만들고, 같은 경로를 사용하는 두 번째
   Core가 명확한 오류로 종료되게 한다.
6. credential 값은 설정/로그/대화 payload에 출력하지 않는다.

### 테스트

- 임시 HOME/LOCALAPPDATA에서 경로가 안정적으로 계산되는지 확인
- portable override가 기본 경로를 덮어쓰는지 확인
- 두 process가 같은 lock을 얻지 못하는지 확인
- Ollama가 없어도 설정 생성과 `/health` 준비가 실패하지 않는지 확인
- secret이 repr/log payload에 노출되지 않는지 확인

## Phase 2 — SQLite migration 기반과 대화 저장소

### 변경 파일

- `apps/eeee/app/storage/sqlite.py`
- `apps/eeee/app/storage/migrations.py` 신규
- `apps/eeee/app/conversations/__init__.py` 신규
- `apps/eeee/app/conversations/models.py` 신규
- `apps/eeee/app/conversations/store.py` 신규
- `apps/eeee/app/conversations/state.py` 신규
- `apps/eeee/tests/storage/test_migrations.py` 신규
- `apps/eeee/tests/conversations/test_store.py` 신규
- `apps/eeee/tests/conversations/test_state.py` 신규

### 작업

1. 기존 `SQLiteStore.init()`의 무조건적인 table 생성 흐름을 번호가 있는
   transactional migration runner 뒤로 이동한다.
2. 기존 schema가 있는 DB에서 migration을 적용하고, 이미 적용된 migration은
   다시 실행하지 않게 한다.
3. 다음 table을 추가한다.
   - `schema_migrations`
   - `conversations`
   - `messages`
   - `assistant_requests`
   - `assistant_events`
4. `messages`에는 role, content, status, sequence, request/provider/model,
   error code, created/completed timestamp를 저장한다.
5. `assistant_requests`에는 request state, original user message ID,
   parent request ID, attempt number, cancellation/recovery timestamp를 저장한다.
6. `assistant_events`에는 event ID, request ID, sequence, type, payload,
   created timestamp를 저장한다.
7. `(conversation_id, client_message_id)` unique constraint로 중복 제출을
   막는다.
8. foreign key, WAL, busy timeout, bounded query를 공통 SQLite 연결 설정으로
   만든다.
9. cursor pagination을 `sequence` 또는 event cursor 기준으로 구현한다.
10. 기존 project/request/memory API는 새 테이블과 별개로 계속 동작하게 한다.

### 테스트

- 빈 DB에 migration 전체 적용
- 기존 DB fixture에 migration 적용 후 기존 table/data 보존
- migration 두 번 실행해도 schema가 중복되지 않음
- message sequence 순서와 cursor pagination
- 동일 client message 중복 제출의 idempotency
- 완료 message가 timer나 request cleanup으로 삭제되지 않음

## Phase 3 — Ollama adapter와 Core conversation service

### 변경 파일

- `apps/eeee/app/agent/ollama_runtime.py` 신규
- `apps/eeee/app/agent/protocol.py` 확장 또는 local provider protocol 분리
- `apps/eeee/app/conversations/service.py` 신규
- `apps/eeee/app/conversations/context.py` 신규
- `apps/eeee/app/conversations/errors.py` 신규
- `apps/eeee/app/assistant/router.py`
- `apps/eeee/app/assistant/registry.py`
- `apps/eeee/app/assistant/service.py`
- `apps/eeee/tests/agent/test_ollama_runtime.py` 신규
- `apps/eeee/tests/conversations/test_service.py` 신규
- `apps/eeee/tests/conversations/test_context.py` 신규
- `apps/eeee/tests/assistant/test_router_compatibility.py` 신규

### 작업

1. Ollama HTTP adapter를 구현한다.
   - model readiness 확인
   - streaming delta 수신
   - timeout 분리
   - cancellation event 전달
   - malformed response 처리
2. provider 오류를 다음과 같이 구분한다.
   - `ollama_unavailable`
   - `ollama_model_missing`
   - `ollama_timeout`
   - `ollama_cancelled`
   - `ollama_invalid_response`
   - `ollama_shutdown`
3. Core conversation service를 구현한다.
   - request ID 생성
   - user message 선저장
   - context 구성
   - provider 호출
   - delta 저장/발행
   - terminal assistant message 저장
4. context builder가 최근 message와 승인된 memory만 token budget 안에서 선택하게 한다.
5. 모델 응답 형식을 일반 답변/clarification/typed action proposal로 제한한다.
6. typed action proposal은 실행하지 않고 policy service로 전달한다.
7. provider 실패를 정상 assistant text로 변환하지 않는다.
8. 기존 keyword router는 project capability compatibility 경로로 유지하고,
   일반 대화는 새 conversation service로 보낸다.
9. 새 경로에는 ChatGPT Web/OpenHands 자동 fallback을 넣지 않는다.

### 테스트

- fake Ollama stream으로 delta 순서와 최종 message 저장
- provider 없음/model 없음/timeout/cancel/malformed 응답
- context token 상한
- 승인되지 않은 action proposal이 실행되지 않음
- 일반 질문이 keyword router의 fake planning response로 끝나지 않음
- provider 오류가 `completed`로 저장되지 않음

## Phase 4 — API v1과 durable event stream

### 변경 파일

- `apps/eeee/app/api/routes.py`
- `apps/eeee/app/api/service.py`
- `apps/eeee/app/api/models.py` 신규 또는 기존 assistant models 확장
- `apps/eeee/app/contracts/events.py`
- `apps/eeee/app/core/events.py` 신규
- `apps/eeee/tests/api/test_conversation_routes.py` 신규
- `apps/eeee/tests/api/test_request_events.py` 신규
- `apps/eeee/tests/api/test_request_recovery.py` 신규

### 작업

1. `/health`가 Core version, schema version, process status를 반환하게 한다.
2. `GET /v1/runtime`에서 Core, Ollama, model, optional capability 상태를 분리해
   반환한다.
3. 다음 endpoint를 추가한다.
   - `POST /v1/conversations`
   - `GET /v1/conversations`
   - `GET /v1/conversations/{id}/messages`
   - `POST /v1/conversations/{id}/turns`
   - `GET /v1/requests/{requestId}/events`
   - `POST /v1/requests/{requestId}/cancel`
   - `POST /v1/requests/{requestId}/retry`
4. request state transition을 한 곳에서 검사한다.
5. event에 `eventId`, `requestId`, `sequence`, `createdAt`를 넣는다.
6. SSE 또는 동일한 cursor semantics를 가진 streaming transport를 사용한다.
7. 재연결 client가 마지막 cursor 이후 event를 replay할 수 있게 한다.
8. cancel/retry endpoint는 idempotent하게 만든다.
9. client가 terminal state를 직접 만들 수 없게 한다.
10. 기존 project/assistant route 응답은 compatibility 기간 동안 유지한다.

### 테스트

- 모든 endpoint의 schema와 status code
- legal/illegal state transition
- event cursor replay와 out-of-order event 차단
- 동일 `clientMessageId` 재전송
- cancel이 terminal request를 변경하지 않음
- retry가 원 user message를 중복하지 않음
- 연결을 끊었다가 재연결한 client의 event 복구

## Phase 5 — Startup recovery와 Core 수명주기

### 변경 파일

- `apps/eeee/app/core/lifecycle.py` 신규
- `apps/eeee/app/core/recovery.py` 신규
- `apps/eeee/app/main.py`
- `apps/eeee/app/runtime/store.py` compatibility 연동
- `apps/eeee/tests/core/test_lifecycle.py` 신규
- `apps/eeee/tests/core/test_recovery.py` 신규
- `apps/eeee/tests/test_health.py`
- `apps/eeee/tests/test_runtime_entrypoint.py`

### 작업

1. `create_app()`에서 Core storage, migration, lock, recovery 순서를 명시한다.
2. Core가 시작할 때 stale `generating`, `streaming`, `executing` request를
   `interrupted`로 바꾼다.
3. `/health`는 Ollama와 optional worker가 없어도 응답한다.
4. 정상 종료 lifecycle에서 새 request를 막고 provider cancel, event flush,
   lock release를 수행한다.
5. Core 중복 실행은 HTTP port 충돌이 아닌 명확한 data lock 오류로 표현한다.
6. 기존 embedded API 방식은 compatibility로 유지하되, Desktop이 Core API와
   분리될 수 있는 구조를 만든다.

### 테스트

- 시작 시 migration/recovery 순서
- 강제 종료 fixture 후 interrupted 복구
- 정상 종료 중 새 turn 거부
- Core 두 개 실행 차단
- Ollama 없이 health 성공
- 재연결 후 event replay

## Phase 6 — Thin Desktop Shell 전환

### 변경 파일

- `apps/eeee/app/desktop/client.py`
- `apps/eeee/app/desktop/session.py`
- `apps/eeee/app/desktop/worker.py`
- `apps/eeee/app/desktop/chat_window.py`
- `apps/eeee/app/desktop/presentation.py`
- `apps/eeee/app/desktop/window.py`
- `apps/eeee/app/desktop/runtime.py`
- `apps/eeee/app/desktop/__main__.py`
- `apps/eeee/tests/desktop/test_client.py`
- `apps/eeee/tests/desktop/test_session.py`
- `apps/eeee/tests/desktop/test_chat_window.py`
- `apps/eeee/tests/desktop/test_presentation.py`
- `apps/eeee/tests/desktop/test_runtime.py`

### 작업

1. Desktop client가 `/v1` API만 호출하도록 바꾼다.
2. Desktop 코드에서 Ollama, SQLite repository, provider runtime,
   project execution class 직접 import를 제거한다.
3. Desktop presentation state를 `idle`, `input`, `submitting`, `streaming`,
   `answer`, `error`, `hidden`으로 명시한다.
4. 입력 제출 시 다음 흐름을 보장한다.
   - 입력 text를 먼저 중앙 표시
   - Core request 접수
   - 입력 bubble을 assistant streaming bubble로 교체
   - 최종 response 또는 오류 표시
5. 답변 bubble click은 기존 timer를 연장하지 않고 fresh input을 생성한다.
6. 말풍선 layout을 텍스트 측정 영역과 asset padding 영역으로 분리한다.
7. 고정 24px height, 고정 one-line height, 고정 본문 영역을 제거한다.
8. streaming/focus/approval 중에는 auto-hide timer를 시작하거나 실행하지 않는다.
9. terminal answer/error 뒤에만 5초 timer를 시작한다.
10. timer는 bubble만 숨기고 message/request는 삭제하지 않는다.
11. Desktop이 외부 창을 raise/activate하지 않게 한다.
12. Core가 끊기면 draft를 보존하고 reconnect/error를 표시한다.
13. 창 위치는 사용자의 마지막 안전 위치를 저장하고, 기본 위치가 기존 작업
    화면을 가리지 않도록 한다.

### 테스트

- Enter 제출과 중앙 정렬
- 답변 click 후 새 input
- 1줄/3줄/10줄/장문 답변의 실제 높이와 줄바꿈
- streaming 중 말풍선 유지
- terminal 응답 후 5초 숨김
- 답변 bubble click 시 timer만 연장되지 않음
- Core 오류 시 draft 보존
- 외부 창/브라우저/터미널 미생성 및 focus 보존

## Phase 7 — Capability 경계와 기존 기능 lazy loading

### 변경 파일

- `apps/eeee/app/capabilities/` 신규 package
- `apps/eeee/app/assistant/registry.py`
- `apps/eeee/app/assistant/service.py`
- `apps/eeee/app/kernel/capabilities.py`
- `apps/eeee/app/main.py`
- `apps/eeee/app/plugins/models.py`
- `apps/eeee/app/plugins/manifest.py`
- `apps/eeee/app/plugins/host.py`
- `apps/eeee/app/runtime/store.py`
- `apps/eeee/tests/capabilities/` 신규
- `apps/eeee/tests/plugins/test_lifecycle_states.py` 신규

### 작업

1. `conversation`, `memory`, `desktop-presence`를 실제 Core capability로 등록한다.
2. `project-execution`은 선택된 request에서만 ISEOL/project runtime을 import한다.
3. startup import graph에서 Node/Playwright/ISEOL/OpenHands가 로드되지 않게 한다.
4. capability 상태를 `not_installed`, `installed`, `auth_required`, `ready`,
   `degraded`, `running`, `failed`, `removed`로 통일한다.
5. 현재 plugin 상태값과 새 상태를 compatibility mapping으로 연결한다.
6. manifest에 protocol version, action schema, permission, side-effect level,
   auth, health, memory scope를 검증한다.
7. worker crash와 timeout을 Core failure로 기록하되 Core를 종료하지 않는다.
8. capability가 설치되지 않은 경우 실제 상태를 반환하고 가짜 completed를
   반환하지 않는다.
9. Chat History plugin은 Core API client로만 연결될 수 있도록 boundary test를
   추가한다.

### 테스트

- idle startup에서 optional module이 import되지 않음
- uninstalled/installed/auth_required/ready/failed/removed 상태 전이
- 잘못된 manifest 거부
- permission 미승인 호출 차단
- worker crash/timeout 격리
- project execution을 선택하기 전 ISEOL process가 시작되지 않음

## Phase 8 — Memory와 대화의 명확한 분리

### 변경 파일

- `apps/eeee/app/memory/store.py`
- `apps/eeee/app/memory/models.py`
- `apps/eeee/app/memory/pipeline.py`
- `apps/eeee/app/memory/compiler.py`
- `apps/eeee/app/conversations/context.py`
- `apps/eeee/app/api/routes.py`
- `apps/eeee/tests/memory/test_conversation_boundary.py` 신규
- `apps/eeee/tests/api/test_memory_api.py`

### 작업

1. raw conversation은 자동으로 active memory가 되지 않게 한다.
2. explicit user memory와 verified outcome memory의 source ID/provenance를 저장한다.
3. memory 검색은 우선 FTS5 또는 기존 bounded search를 사용한다.
4. memory promotion, edit, revoke, supersede API를 명확히 분리한다.
5. context builder가 현재 conversation과 허용 memory를 구분해서 model에 전달한다.
6. memory promotion 실패가 일반 대화 완료로 보이지 않게 한다.

### 테스트

- 일반 conversation이 memory로 자동 승격되지 않음
- explicit remember/forget/edit/revoke
- source message/artifact 없는 memory promotion 차단
- revoked/superseded memory가 context에 포함되지 않음
- 긴 transcript를 context에 전부 넣지 않음

## Phase 9 — 패키징 분리와 실제 런타임 검증

### 변경 파일

- `apps/eeee/pyproject.toml`
- `apps/desktop/gleave-desktop.spec`
- `apps/eeee/Dockerfile`
- `apps/eeee/docker-compose.yml`
- `apps/eeee/README.md`
- `apps/eeee/scripts/` 아래 smoke/benchmark script
- `apps/eeee/tests/smoke/` 신규
- `apps/eeee/tests/packaging/` 신규

### 작업

1. Core package에서 PySide6, Node, Playwright, ISEOL, OpenHands, provider
   SDK가 startup dependency가 되지 않게 한다.
2. Desktop package에만 PySide6를 포함한다.
3. optional runtime asset이 Core package에 들어가지 않는지 build artifact를
   검사한다.
4. Core route overhead benchmark를 warm process 기준으로 추가한다.
5. Core process count, Desktop process count, idle child process를 측정한다.
6. 실제 Ollama가 있는 환경에서 local runtime smoke를 실행한다.
7. Ollama가 없는 환경에서도 Core health/명확한 unavailable 상태를 검증한다.
8. Desktop package를 실행하여 idle 때 Chrome/Node/ISEOL이 없는지 확인한다.

### 검증 명령

구체적인 명령은 구현 시 환경에 맞춰 README에 고정하되 최소한 다음 종류를
포함한다.

```powershell
Set-Location C:\Users\user\Documents\eeee-core-redesign\apps\eeee
$env:PYTHONPATH = "."
python -m pytest tests -q
python scripts/benchmark_core.py
python scripts/smoke_ollama.py
python scripts/smoke_restart_recovery.py
```

Ollama나 패키징 도구가 없는 환경에서는 명령을 억지로 성공 처리하지 않고
`not run` 또는 `blocked: dependency unavailable`로 보고한다.

## Phase 10 — EEEE v1 acceptance와 다음 작업으로의 handoff

### 작업

1. 설계 문서의 12개 acceptance criteria를 체크리스트로 실행한다.
2. 검증 결과를 deterministic/local runtime/persistence/packaged desktop/UI/
   capability boundary 등급별로 기록한다.
3. 실패한 항목은 “완료”라고 표시하지 않고 request ID, 로그, 재현 단계와 함께
   수정한다.
4. Core와 Desktop이 안정화된 뒤에만 Chat History plugin 작업을 재개한다.
5. Chat History가 Core API를 사용하고 자체 AI/DB를 만들지 않는지 확인한다.
6. 그 다음 ISEOL을 `project-execution` optional capability로 연결한다.

### 완료 조건

- EEEE v1 acceptance 전체 통과
- 결정론적 테스트와 실제 runtime 테스트가 별도로 보고됨
- Core가 Ollama unavailable을 거짓 답변으로 숨기지 않음
- Desktop이 외부 작업 화면을 가리지 않음
- 재실행 후 대화/상태/중단 turn 복구
- Chat History와 ISEOL을 연결해도 Core의 single process/database 원칙이 유지됨

## 구현 중 절대 금지할 회귀

- 기본 provider를 다시 ChatGPT Web로 바꾸기
- 말풍선에 고정 높이 또는 고정 본문 줄 수 넣기
- 답변 timer가 streaming 중 실행되어 텍스트를 숨기기
- 답변 click을 timer 연장으로 처리하고 새 input을 열지 않기
- UI가 직접 SQLite/AI/provider를 호출하기
- 새 plugin마다 Ollama 또는 database를 시작하기
- Core 오류를 “완료됨” assistant 문장으로 바꾸기
- 기존 사용자 DB를 삭제하고 새 DB로 조용히 시작하기
- unit test 통과만으로 실제 실행 성공이라고 보고하기

