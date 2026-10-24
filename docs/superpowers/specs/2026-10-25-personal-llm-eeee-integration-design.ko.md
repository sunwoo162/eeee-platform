# EEEE 개인화 LLM provider 통합 설계

## 의도

완성된 `eeee-personal-llm` 서비스를 EEEE의 기본 대화 provider로 연결한다. 사용자는 기존 EEEE 대화 화면과 conversation 저장소를 그대로 사용하고, 실제 답변 생성만 로컬 개인화 LLM 서비스가 담당하게 한다.

현재 개인화 LLM은 별도 저장소에서 운영되는 로컬 HTTP 서비스다.

- 서비스 주소: `http://127.0.0.1:8765`
- 상태 확인: `GET /health`, `GET /v1/model/status`
- 대화 API: `POST /v1/chat`
- 사용자 경계: `X-Personal-User-Id` 헤더
- 기본 보안: `proxy_auto` 외부 자동 전송 금지, 승인된 profile/memory만 사용

EEE의 기존 provider 선택기에는 `chatgpt_web`, `ollama`, `auto`가 있고, conversation service는 모든 provider를 `stream()` 계약으로 소비한다. 개인화 LLM API는 비스트리밍 typed 응답을 반환하므로 EEEE adapter가 응답 전체를 하나의 delta로 전달한다.

## 목표

- EEEE가 `personal_llm` provider를 선택할 수 있게 한다.
- 기본 설치의 대화 provider를 로컬 개인화 LLM으로 전환한다.
- EEEE의 conversation context와 사용자 ID를 개인화 LLM에 명시적으로 전달한다.
- provider와 model provenance를 기존 EEEE 메시지 기록에 남긴다.
- 개인화 LLM 미실행, timeout, malformed response, HTTP 오류를 성공으로 가장하지 않고 기존 fail-closed 오류 흐름으로 전달한다.
- ChatGPT Web과 Ollama를 제거하지 않고 명시적으로 선택 가능한 provider로 보존한다.

## 비목표

- 개인화 LLM 코드를 EEEE 저장소로 복사하거나 Python dependency로 vendoring하지 않는다.
- 개인화 LLM의 SQLite profile/memory를 EEEE DB와 병합하지 않는다.
- EEEE가 자동으로 ChatGPT Web에 fallback하여 대화 내용을 외부로 보내지 않는다.
- 이번 통합에서 개인화 LLM 서버의 자동 프로세스 시작/종료를 구현하지 않는다.
- 스트리밍 응답을 새로 발명하지 않는다. 현재 API 계약에 맞춰 완성된 답변을 하나의 delta로 전달한다.
- Gleave UI가 개인화 LLM API를 직접 호출하게 하지 않는다. UI는 계속 EEEE API만 호출한다.

## 접근 방법

### A. EEEE provider adapter로 loopback API 연결 — 선택

EEE에 `PersonalLlmConversationProvider`를 추가하고, `ConversationProvider` 인터페이스 뒤에서 개인화 LLM의 typed HTTP API를 호출한다. 개인화 LLM 저장소와 실행 환경은 독립적으로 유지한다.

- 장점: 현재 provider 선택기와 conversation service를 재사용하고, 사용자 경계·오류 처리·provenance를 EEEE 경계에서 통제할 수 있다.
- 단점: 첫 단계에서는 HTTP 요청이 비스트리밍이며 개인화 LLM 서버를 별도로 실행해야 한다.

### B. 개인화 LLM 패키지를 EEEE 프로세스에 직접 내장

- 장점: 프로세스 하나로 보일 수 있다.
- 단점: Python dependency, 모델 메모리, registry DB, 장애 수명이 결합되고 EEEE의 현재 provider 경계와 맞지 않는다. 독립 서비스로 검증된 개인화 LLM을 다시 포장하게 된다.

### C. Gleave UI에서 개인화 LLM API 직접 호출

- 장점: 화면에서 빠르게 연결할 수 있다.
- 단점: EEEE의 conversation persistence, 사용자 격리, approval, ClaimLatch와 별도 경로가 생긴다. 메인 제품의 신뢰 경계를 우회하므로 채택하지 않는다.

선택한 방식은 A다. EEEE를 단일 사용자-facing 진입점으로 유지하면서, 개인화 LLM은 로컬 model provider로만 붙인다.

## 동작 설계

### Provider 선택

- `conversation_provider`에 `personal_llm`을 추가한다.
- 기본값은 `personal_llm`으로 바꾼다.
- `EEEE_CONVERSATION_PROVIDER=chatgpt_web` 또는 `ollama`로 기존 provider를 명시적으로 선택할 수 있다.
- `auto`는 개인화 LLM이 ready일 때 개인화 LLM을 우선 선택한다. 개인화 LLM이 unavailable이면 외부 ChatGPT Web으로 조용히 넘기지 않고, 기존의 안전한 unavailable/builtin 경로를 사용한다.
- 개인화 LLM을 선택했을 때 서버가 없으면 상태에 `personal_llm_unavailable`과 해결 가능한 메시지를 남긴다.

### 요청 매핑

EEE가 보유한 conversation context를 다음처럼 개인화 LLM `ChatRequest`로 매핑한다.

| EEEE | Personal LLM |
| --- | --- |
| request ID | `requestId` |
| conversation user ID | `userId`와 `X-Personal-User-Id` |
| EEEE conversation ID | `conversationId` |
| context messages | `messages` |
| 기본 대화 모드 | `mode=assistant` |
| 첫 통합 단계 | `profileRevision=0`, `approvedMemoryIds=[]` |

개인화 adapter 자체의 학습된 말투는 그대로 사용하고, 대화의 최신 context와 EEEE 사용자 경계는 EEEE가 제공한다. 별도 profile/memory 동기화는 후속 범위로 남긴다.

### 응답과 provenance

- `ChatResponse.status=completed`이고 `text`가 비어 있지 않을 때만 답변을 기록한다.
- 응답 텍스트는 `stream()`에서 하나의 delta로 yield한다.
- `provider_name`은 `personal_llm`, `model`은 `/v1/model/status`의 `modelVersion`으로 기록한다.
- `needsUserConfirmation`과 action proposal은 이번 conversation provider 경계에서 실행하지 않는다. EEEE의 기존 action/approval 흐름이 계속 소유한다.
- `backend_error`, `profile_revision_mismatch`, HTTP 4xx/5xx, 잘못된 JSON, 빈 답변은 `ConversationProviderError`로 변환한다.

### 설정

추가 설정은 다음과 같다.

- `EEEE_PERSONAL_LLM_BASE_URL` — 기본 `http://127.0.0.1:8765`
- `EEEE_PERSONAL_LLM_CONNECT_TIMEOUT_SECONDS` — loopback 연결 timeout
- `EEEE_PERSONAL_LLM_GENERATION_TIMEOUT_SECONDS` — `/v1/chat` timeout
- `EEEE_PERSONAL_LLM_CONTEXT` 또는 기존 conversation context budget — EEEE가 보낼 context를 제한하는 기존 정책을 재사용

개인화 LLM의 model/adapter 선택은 개인화 LLM 저장소의 환경변수와 registry가 소유한다. EEEE는 model 파일 경로나 adapter artifact를 직접 알지 않는다.

## 변경 범위

- `apps/eeee/app/config.py`: provider literal과 개인화 LLM URL/timeout 설정
- `apps/eeee/app/agent/personal_llm_runtime.py`: typed HTTP status/chat adapter
- `apps/eeee/app/conversations/providers.py`: provider class와 selection wiring
- `apps/eeee/app/main.py`: provider 생성 및 상태 보관
- `apps/eeee/app/api/conversation_routes.py` 또는 provider 상태 응답: 선택된 provider/model 노출이 필요한 지점만 수정
- `apps/eeee/tests/agent/`: transport, status, payload, 오류 매핑 테스트
- `apps/eeee/tests/conversations/test_providers.py`: selection, user scope, provenance, unavailable 테스트
- `apps/eeee/tests/core/test_paths.py` 및 설정 테스트: 기본 provider와 alias 검증
- `.env.example`, EEEE 운영 문서: 개인화 LLM 실행과 연결 방법

개인화 LLM 저장소의 코드는 수정하지 않는다. 통합 검증은 fake HTTP transport와 별도 loopback smoke를 분리한다.

## 검증 기준

1. 설정 없이도 기존 test suite가 깨지지 않고, 명시적 기존 provider 선택이 유지된다.
2. 개인화 LLM status가 ready이면 EEEE selection이 `personal_llm`과 model version을 표시한다.
3. 실제 POST payload에 context, request ID, conversation ID, 사용자 header가 정확히 포함된다.
4. 다른 사용자 ID가 개인화 LLM 경계를 넘지 않는다.
5. timeout/connection failure/HTTP 오류/잘못된 응답/빈 답변은 assistant 성공 메시지를 만들지 않는다.
6. cancel 요청 이후 늦게 도착한 응답은 저장되지 않는다.
7. 개인화 LLM adapter를 fake server로 검증하고, 실제 loopback 서버가 실행 가능한 경우 health/status/chat smoke를 수행한다.
8. EEEE의 기존 전체 검증 명령과 diff hygiene가 통과한다.

## 구현 후 남는 일

첫 통합이 안정화된 뒤에만 다음을 별도 설계한다.

- EEEE 승인 profile/memory를 개인화 LLM의 user-scoped store와 동기화하는 계약
- 개인화 LLM의 비스트리밍 API를 진짜 cancelable streaming으로 확장하는 계약
- EEEE desktop runtime이 개인화 LLM process lifecycle을 관리하는 계약
- 개인화 LLM 답변을 ClaimLatch와 연결하는 release/action 검증 정책
