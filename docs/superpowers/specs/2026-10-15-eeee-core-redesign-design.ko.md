# EEEE Core 재설계 설계안

## 상태

2026-10-15 사용자로부터 접근 방식 2의 방향 승인을 받았다.
이 문서는 구현을 시작했다는 의미가 아니다. 먼저 이 설계 문서를 검토하고,
그 다음 별도의 구현 계획을 작성한다. 설계 평가 후에는 v1 범위, API, AI
공급자, 저장소, 프로세스 수명주기, 검증 계약을 명시적으로 보완했다.

## 결정 사항

접근 방식 2인 **EEEE Core + 얇은 Desktop Shell + 선택적 기능 모듈**을
사용한다.

EEEE Core는 항상 실행 가능한 가벼운 로컬 개인 비서 서비스다. Core가
대화, 로컬 AI 라우팅, 메모리, 정책, 영속 상태, 작업 이벤트를 소유한다.
Desktop Shell은 표시와 입력만 담당한다. 프로젝트 실행, 이설, ChatGPT Web,
브라우저 자동화, 외부 커넥터, 향후 플러그인은 필요할 때만 로드되는 선택적
기능이다.

사용자에게는 하나의 EEEE 제품으로 보이지만, 책임에 따라 런타임은 분리한다.
여기서 “분리”는 기능을 설치·비활성화·삭제할 수 있다는 뜻이지, 모든 기능이
영구적으로 별도의 AI 서버나 데이터베이스를 실행한다는 뜻이 아니다.

## 1. 현재 상태 감사

이 절은 저장소에 실제로 존재하는 내용을 기록한다. 현재 제품이 완성됐다는
뜻이 아니다.

### 1.1 현재 존재하는 것

- `apps/eeee`에 FastAPI 애플리케이션, SQLite 기반 프로젝트 상태,
  메모리 수명주기 코드, 실행 envelope, 신뢰 게이트, 플러그인 subprocess
  호스트, 모바일 브리지, 프로젝트 생성 기능, PySide6 데스크톱 화면이 있다.
- `KernelService`가 라우팅 실행, capability 정책, 승인 상태, 프로젝트
  식별자, revision 검사, 신뢰 결정을 기록하고 적용한다.
- 프로젝트 요청은 프로젝트, workspace, request, 프로젝트 프로필,
  connector plan, run 기록, 프로젝트 증거 경계를 만들 수 있다.
- OpenHands, ISEOL Project Runtime, ISEOL ChatGPT Web bridge용 agent
  runtime adapter가 있다.
- 프로젝트 메모리는 candidate/active/superseded/revoked 상태를 가지며,
  결정론적 QA, 식별자, ClaimLatch 증거가 없으면 승격을 거부한다.
- `PluginHost`가 manifest를 발견하고 등록하며, 권한 승인, 로컬 프로세스
  health check, invoke, disconnect, registration 제거를 수행할 수 있다.
- Desktop이 embedded local API를 시작하고 API를 통해 assistant/project
  요청을 보낼 수 있다.

### 1.2 실제로 아직 완성되지 않은 것

- 기본 EEEE runtime은 Ollama가 아니라 `chatgpt_web`이다. `apps/eeee/app/agent`
  안에는 Ollama adapter가 없다. ISEOL의 다른 위치에 로컬 Ollama adapter가
  있어도 EEEE의 기본 대화 경로로 연결되어 있지 않다.
- 라우팅은 결정론적 trigger phrase 매칭이다. 일반적인 자연어 비서 라우터가
  아니다.
- `personal-secretary`, `knowledge-documents`, `presence`는 계획 capability다.
  선택/계획 응답은 반환하지만 아직 캘린더, 파일, 리마인더, 기기 작업을
  실제로 수행하지 않는다.
- 대화 turn은 EEEE의 1급 데이터 모델이 아니다. 현재 영속 데이터는
  프로젝트 요청, task, run, event, evidence, 프로젝트 memory에 집중되어 있다.
- 프로젝트 memory는 chat memory와 다르다. 검증된 프로젝트 결과를 저장하지만
  사용자가 보는 완전한 대화 archive는 제공하지 않는다.
- Notion과 GitHub는 부분적인 adapter 경로만 있다. Gmail과 Google Calendar는
  EEEE Core의 완전한 capability가 아니다.
- PluginHost는 protocol/lifecycle 기반일 뿐, 최종 사용자를 위한 marketplace나
  GPT와 같은 설치/로그인 catalog는 아니다.
- ClaimLatch 기본값은 advisory mode다. ClaimLatch adapter가 없다고 해서
  일반 로컬 계획이 검증된 claim이 되는 것은 아니며, full production trust
  enforcement라고 표현해서도 안 된다.
- 프로젝트 자동 실행 기본값은 false다. 프로젝트를 만들 수는 있지만 agent
  run이 자동으로 실행된다는 뜻은 아니다.
- 현재 Desktop build wiring은 무거운 선택적 runtime asset도 같은 패키징
  경로에 포함한다. 따라서 Core가 진짜 가볍다고 할 수 없다.
- 감사에 사용한 working tree는 dirty 상태였다. EEEE/ISEOL 추적 파일에
  미커밋 변경이 있었고 임시 테스트 폴더도 많았다. 이 변경들은 사용자의
  작업이며 이 설계에 몰래 포함하지 않는다.

### 1.3 검증 범위

`apps/eeee`에서 EEEE 테스트를 실행한 결과는 **450 passed, 1 skipped,
1 warning**이었다. 이는 해당 환경의 결정론적 Python unit/API/contract
   suite가 통과했다는 것만 증명한다. 실제 Ollama 응답, ChatGPT Web 로그인,
실제 외부 커넥터 동작, 패키징된 Desktop 시작, 운영 credential을 사용한
전체 프로젝트 실행까지 증명하지 않는다.

따라서 테스트 결과는 다음의 별도 증거 등급으로 보고해야 한다.

1. 결정론적 unit 및 contract 테스트
2. 로컬 runtime smoke 테스트
3. 패키징된 Desktop smoke 테스트
4. 실제 provider/connector 테스트
5. 사용자 흐름 acceptance 테스트

초록색 unit 테스트 개수를 다섯 등급 전체의 증거로 보고하면 안 된다.

## 2. 목표 제품 경계

### 2.1 EEEE Core가 담당하는 것

- 하나의 로컬 assistant 정체성과 대화 수명주기
- 모든 사용자 메시지와 assistant 응답의 영속 저장
- 로컬 Ollama 연결 및 모델 상태
- 가벼운 intent 분류와 capability 선택
- 최근 대화와 승인된 memory를 사용한 context 구성
- 로컬 작업 수명주기와 재개 가능한 상태
- workspace, network, 외부 side effect 이전의 사용자 승인
- memory 후보, 명시적 사용자 memory, 검색, 수정, 취소
- 이벤트, 알림, 오류, 재실행 복구
- Desktop, Chat History, Mobile, plugin이 사용하는 안정적인 로컬 API
- connector/plugin metadata, 권한 선언, health 상태

### 2.2 EEEE Core가 담당하지 않는 것

- Gmail, Calendar, Notion, GitHub 또는 기타 provider API의 업무 로직
- 일반 실행 시 Chrome 또는 ChatGPT Web 구동
- plugin마다 두 번째 database 생성
- ISEOL의 Agent 분해 및 실행 내부 구현
- kernel 안에서 Desktop UI 렌더링
- LLM의 자연어 문장을 작업 완료 증거로 취급하는 것
- 알 수 없는 코드를 조용히 설치하거나 provider 권한을 부여하는 것

### 2.3 Desktop Shell이 담당하는 것

- 고양이/pet 화면, 입력 focus, 말풍선, tray 상태, 로컬 알림
- assistant 업무 로직을 소유하지 않고 Core API 호출
- streaming, completed, failed, cancelled, interrupted 상태 렌더링
- 사용자가 요청했을 때만 여는 선택적 control center
- 일반 응답 중 focus를 뺏거나 외부 browser/window를 자동으로 열지 않음
- 사용자의 마지막 안전 위치와 표시 설정 보존

Desktop Shell은 Ollama를 직접 생성하지 않고, SQLite table을 직접 쓰지 않고,
provider API를 직접 호출하지 않고, 응답이 신뢰 가능한지 스스로 결정하지
않는다.

## 3. 목표 런타임 구조

```text
                ┌──────────────────────────────┐
                │ EEEE Core                    │
                │ loopback API + SQLite        │
                │ Ollama adapter               │
                │ 대화 + memory                │
                │ router + policy + events     │
                └──────────────┬───────────────┘
                               │ localhost protocol
              ┌────────────────┼────────────────┐
              │                │                │
       Desktop Shell     Chat History       Mobile/Plugins
       PySide6 전용      선택적 UI          선택적 client

       필요할 때만 시작되는 선택적 capability worker:
       ISEOL / ChatGPT Web / Gmail / Calendar / Notion / GitHub
```

Core process는 하나이고 SQLite source of truth도 하나다. 선택적 worker는
격리 subprocess일 수 있지만 설치되거나 선택되지 않은 worker는 Core boot 때
시작하지 않는다.

## 4. Core 요청 및 응답 로직

모든 사용자 turn은 다음의 영속 상태 머신을 따른다.

```text
received
  -> persisted_user_message
  -> classified
  -> awaiting_approval | generating | executing
  -> streaming
  -> completed | failed | cancelled | interrupted
```

### 4.1 들어온 turn 처리

1. Core가 `requestId`를 만들고 AI provider를 호출하기 전에 사용자 메시지를
   저장한다.
2. 현재 conversation의 제한된 최근 context와 명시적으로 허용된 memory만
   읽는다.
3. 결정론적 safety pre-router가 명시적인 capability 요청과 side-effect
   동사를 감지한다. model이 제안했다고 바로 action을 실행하지 않는다.
4. 일반 대화 또는 모호한 의도는 local Ollama adapter에 구조화된 prompt
   contract로 전달한다.
5. model은 일반 응답, clarification 요청, typed action proposal 중 하나를
   반환할 수 있다. 구조화 결과가 잘못되면 오류/clarification이 되고,
   성공을 꾸며내지 않는다.
6. side effect 수준상 승인이 필요한 action proposal은 plan으로 보여주고
   승인 전 대기한다.
7. Core가 답변 텍스트를 client에 streaming하고 최종 assistant message를
   상태와 metadata와 함께 저장한다.
8. Core가 영속 lifecycle event를 발행해 재시작한 UI도 현재 상태를 복원한다.

### 4.2 재시작 및 오류 처리

- model이 unavailable이어도 사용자 메시지는 유실되지 않는다.
- Core 중단 당시 `streaming`이던 응답은 다음 시작 때 `interrupted`가 되고
  retry가 가능하다.
- timeout은 명확한 retryable error code를 가진 실패다.
- provider 오류를 일반 assistant 답변으로 바꾸지 않는다.
- 완료된 응답은 5초 UI 말풍선 timer 때문에 삭제되지 않는다.

## 5. 데이터 모델

Conversation transcript와 장기 memory는 의도적으로 분리한다.

### 5.1 Conversation table

`conversations`:

- `id`, `title`, `created_at`, `updated_at`, `archived_at`
- `active_message_id` 및 선택적 UI metadata

`messages`:

- `id`, `conversation_id`, `sequence`
- `role`: `user`, `assistant`, `system`, `tool`
- `content`, `status`, `created_at`, `completed_at`
- `request_id`, `provider`, `model`, `error_code`, 제한된 metadata

DB에는 전체 transcript text를 로컬 저장한다. API 응답은 cursor pagination을
사용하며, UI나 model context에 무제한 conversation을 한 번에 로드하지 않는다.

### 5.2 장기 memory

Memory는 명시적인 종류와 상태를 가진다.

- 사용자 선호
- 사용자 사실
- 프로젝트 사실
- 검증된 성공/실패 패턴
- QA/regression 규칙
- revoked 또는 superseded memory

Raw conversation을 자동으로 memory로 승격하지 않는다. 명시적인 사용자 지시
또는 provenance가 있는 검증된 결과가 있어야 한다. active memory에는 source
message/artifact ID, scope, confidence, 취소 metadata를 남긴다.

첫 검색 구현은 SQLite FTS5로 한다. 실제 retrieval 측정에서 FTS5가 부족하다고
확인되기 전까지 vector database는 사용하지 않는다.

## 6. Capability 및 plugin 경계

첫 번째 내장 capability는 다음과 같다.

- `conversation`: 실제 로컬 Ollama 대화
- `memory`: 승인된 memory 확인, 저장, 수정, 삭제, 검색
- `desktop-presence`: 로컬 UI 상태만 담당
- `project-execution`: ISEOL을 사용할 때만 로드되는 후순위 capability

외부 서비스는 plugin으로 취급한다. plugin은 다음을 선언한다.

- identity/version 및 entry point
- actions와 schema
- permissions와 side-effect level
- authentication flow
- health check와 protocol version
- memory read/write scope

설치, 인증, 연결, 호출, 실패, 제거는 각각 다른 상태다. plugin을 제거해도
conversation이나 audit history는 제거하지 않는다.

첫 번째 Chat History plugin은 Core conversation API를 사용한다. 두 번째
Ollama process나 두 번째 transcript database를 시작하거나 소유하지 않는다.

## 7. Desktop 동작 계약

Desktop Shell은 다음 표시 상태를 가진다.

- `idle`: 고양이 표시, 말풍선 숨김
- `input`: 말풍선 focus 및 편집 중
- `submitting`: 요청 접수 중 입력 잠금
- `streaming`: 답변 생성 중, 말풍선 숨김 금지
- `answer`: 최종 답변 표시
- `error`: 조치 가능한 오류 표시
- `hidden`: 상태를 삭제하지 않고 말풍선만 숨김

규칙:

- 말풍선 높이는 content-driven이며 고정 24px/한 줄 높이를 사용하지 않는다.
- 텍스트 전용 layout 영역에서 텍스트를 먼저 측정하고, 가로·세로 padding을
  더한 뒤 asset/background 크기를 정한다.
- 사용자 입력과 assistant 출력은 동일한 중앙 정렬 text layout 계약을 쓴다.
- 답변을 클릭하면 기존 답변 timer만 연장하지 않고 새로운 input 상태를 연다.
- 5초 timer는 terminal response 상태가 된 뒤에만 시작한다.
- input focus, active streaming, pending approval 중에는 자동 숨김을 멈춘다.
- timer는 말풍선만 숨기며 Core 요청을 취소하거나 저장된 message를 삭제하지
  않는다.
- 일반 응답에서 Core가 window activation/raise를 호출하지 않는다.
- 긴 작업은 ChatGPT, Chrome, terminal을 띄우는 대신 tray/status indicator와
  사용자가 요청할 때만 여는 control center를 사용한다.

## 8. 가벼운 패키징 및 성능

### Core 배포물

- Python/FastAPI/SQLite/Ollama adapter만 포함
- PySide6 의존성 없음
- Node, Playwright, ISEOL, OpenHands, provider SDK를 startup 때 import하지 않음
- 선택적 capability는 lazy import
- loopback service 하나와 database 하나

### Desktop 배포물

- PySide6는 Desktop Shell package에만 포함
- Shell은 하나의 Qt process이며 localhost로 Core를 호출
- 설치된 plugin마다 별도의 전체 Qt runtime을 시작하지 않음
- 격리가 필요한 경우 shared host 또는 thin client를 사용

### 런타임 목표

- Ollama, ISEOL, Node, Chrome, plugin이 없어도 Core가 시작하고 `/health`에
  응답해야 한다.
- Desktop startup 때 Node, Chrome, ChatGPT Web, ISEOL, 선택적 plugin을
  시작하지 않는다.
- 일반 대화에서 project runtime을 초기화하지 않는다.
- Ollama 시간을 제외한 warm Core route overhead를 local benchmark로 측정하고
  p95 100ms 이하로 유지한다.
- UI network call이 Qt event loop를 block하지 않는다.
- conversation rendering과 API read는 cursor/page 단위로 제한한다.

## 9. 신뢰 및 안전 규칙

- 일반 로컬 대화는 검증된 외부 사실이 아니라 assistant output이라고 표시한다.
- workspace write, command, network call, 외부 메시지, 삭제, publish, deploy는
  typed action plan과 approval policy를 거쳐야 한다.
- release, 외부 side effect, memory promotion에는 ClaimLatch와 결정론적 QA가
  필수다. harmless local greeting에는 실행하지 않는다.
- provider credential은 conversation content, event payload, plugin log에
  들어가지 않는다.
- model output이 임의 executable, path, plugin command를 선택할 수 없다.
- 알 수 없는 plugin code는 명시적인 설치 승인이 필요하다.

## 10. 마이그레이션 전략

기존 project data를 보존하고 파괴적인 rewrite를 피한다.

1. 기존 agent runtime 옆에 Core conversation/message contract와 Ollama
   adapter를 추가한다.
2. 새 conversation capability를 기본 assistant 경로로 만든다.
3. 재시작에 안전한 request 상태와 transcript 저장을 추가한다.
4. 현재 keyword router를 compatibility adapter 뒤로 이동하고 구조화된
   local router 경로를 추가한다.
5. Desktop Shell을 추출해 Core API만 호출하게 한다.
6. project execution, ChatGPT Web, OpenHands 생성을 lazy capability factory
   뒤로 이동한다.
7. 마이그레이션 기간 동안 기존 project/request endpoint를 유지하고
   compatibility surface라고 표시한다.
8. Core package에 optional runtime이 들어가지 않도록 패키징을 분리한다.
9. 실제 local Ollama, packaged Desktop, restart, user-flow 테스트를 추가한다.
10. EEEE Core가 안정화된 뒤에야 Chat History와 ISEOL 작업을 재개한다.

어떤 마이그레이션 단계도 기존 SQLite database를 삭제하거나 project identity와
conversation identity를 조용히 초기화해서는 안 된다.

## 11. 완료 기준

다음 항목을 모두 보여주기 전에는 EEEE Core 재설계가 완료된 것으로 보지 않는다.

1. 깨끗한 Core 설치가 ISEOL, ChatGPT Web, Node, Chrome, PySide6, plugin 없이
   시작된다.
2. local model이 설정되어 있으면 Ollama가 기본 대화 provider가 된다. Ollama가
   없으면 명확한 대기/오류 상태를 보여준다.
3. 사용자 message가 generation 전에 저장되고, assistant response가 완료 또는
   실패 후 저장된다.
4. Core 재시작 후 transcript가 남고, 중단된 turn은 retry 가능하다.
5. 긴 response도 clipping, 고정 높이 잘림, 예상치 못한 말풍선 사라짐 없이
   렌더링된다.
6. 답변을 클릭하면 새로운 input turn이 시작된다.
7. 일반 response가 외부 window를 열거나 focus를 빼앗지 않는다.
8. personal-secretary, memory, conversation flow가 실제 동작하거나 capability가
   설치되지 않았다고 명시적으로 보고한다. 가짜 completed result를 반환하지 않는다.
9. project execution은 optional runtime이 설정된 경우에만 가능하고, 일반 대화를
   깨뜨리지 않으면서 상태가 보인다.
10. 외부 action과 memory promotion은 필요한 승인/증거가 없으면 fail closed 한다.
11. Core와 Desktop package 크기/프로세스 수를 별도로 측정하고, Core package에
   optional ISEOL/Playwright asset이 없다.
12. 검증 보고서가 deterministic test, local runtime smoke, packaged desktop smoke,
   live provider test, user-flow acceptance를 구분한다.

## 12. 이 재설계의 명시적 비목표

- EEEE Core 안에 ISEOL Agent team을 만드는 것
- Core 안에 Gmail, Calendar, Notion, GitHub 또는 provider 업무 로직을 구현하는 것
- hosted EEEE account나 cloud database를 만드는 것
- public plugin marketplace를 만드는 것
- SQLite FTS5가 부족하다고 측정하기 전에 vector database를 추가하는 것
- unit test 통과를 live AI 또는 connector 동작의 증거라고 주장하는 것

## 13. 구현 전 고정해야 할 계약

이 절은 아키텍처를 구현 제약으로 구체화한다. 특정 Python module 구조를
강제하지 않으면서도 테스트 가능한 수준으로 명시한다.

### 13.1 EEEE v1 범위

첫 구현 milestone은 완성된 plugin ecosystem이 아니라 완성된 EEEE Core와
Desktop Shell이다. 이 milestone의 “완성”은 다음을 뜻한다.

1. 하나의 local Core process가 시작·health 보고·정상 종료를 수행한다.
2. 일반 대화 provider는 Ollama 하나뿐이다.
3. 사용자가 conversation을 생성/선택하고, message를 보내고, streaming 답변을
   받고, 실패 turn을 retry하고, 진행 중 turn을 cancel할 수 있다.
4. Core와 Desktop 재시작 후 사용자/assistant message가 남는다.
5. 중단된 turn이 보이고 retry 가능하다.
6. Desktop Shell이 input, streaming, answer, error, hidden 상태를 외부 앱의
   focus를 빼앗지 않고 표시한다.
7. 5초 말풍선 규칙과 content-driven layout이 짧은/긴 message 모두에서 동작한다.
8. project execution, external connector, memory action이 설치되지 않았으면
   Core가 사용할 수 없음을 명확히 보고한다.

다음 기능은 EEEE Core 안정화 뒤로 미룬다: 별도 Chat History client, ISEOL
project execution, ChatGPT Web automation, external provider connector, public
plugin discovery, plugin-specific UI.

### 13.2 Local Core API 계약

Loopback API는 `/v1` 아래에서 versioning한다. turn과 관련된 모든 response는
안정적인 `requestId`를 포함하고, 실패할 때 error object를 포함한다. Core가
source of truth이므로 client는 socket disconnect나 UI timer를 보고 완료를
추정하면 안 된다.

최소 endpoint:

| Endpoint | 목적 | 필수 동작 |
| --- | --- | --- |
| `GET /health` | process liveness | Ollama가 없어도 Core version, schema version, process status를 반환 |
| `GET /v1/runtime` | dependency readiness | Ollama/model readiness와 선택적 capability 상태를 분리해 보고 |
| `POST /v1/conversations` | conversation 생성 | ID 반환 전에 영속 conversation 생성 |
| `GET /v1/conversations` | conversation 목록 | cursor pagination과 제한 사용; 기본으로 전체 transcript를 반환하지 않음 |
| `GET /v1/conversations/{id}/messages` | transcript 조회 | 안정적인 sequence 순서의 cursor pagination |
| `POST /v1/conversations/{id}/turns` | user turn 제출 | provider 작업 전에 user message 저장; `requestId` 즉시 반환 |
| `GET /v1/requests/{requestId}/events` | lifecycle/output streaming | cursor 이후 event를 replay한 뒤 새 event streaming |
| `POST /v1/requests/{requestId}/cancel` | turn 취소 | idempotent; terminal turn은 변경하지 않음 |
| `POST /v1/requests/{requestId}/retry` | 실패/중단 turn retry | 원 요청에 연결된 새 attempt 생성; user message 중복 생성 금지 |

Turn request에는 `conversationId`, `clientMessageId`, `content`가 있어야 한다.
`clientMessageId`는 conversation 안에서 유일해야 하며 Desktop의 중복 전송을
idempotent하게 만든다. response에는 영속 user message ID, `requestId`, 최초
상태가 들어간다.

Event type은 문서화된 집합으로 제한한다: `request.accepted`,
`request.classified`, `message.started`, `message.delta`, `message.completed`,
`request.failed`, `request.cancelled`, `request.interrupted`,
`approval.required`. 각 event에는 `eventId`, `requestId`, `sequence`,
`createdAt`, JSON payload가 있다. `message.delta`는 열린 assistant message에
붙는 일시적 output이며, assistant message를 완료로 만드는 것은 최종
`message.completed` event뿐이다.

허용되는 request 전이는 다음과 같다.

```text
received -> persisted_user_message -> classified
classified -> generating | awaiting_approval | failed
generating -> streaming | failed | cancelled | interrupted
streaming -> completed | failed | cancelled | interrupted
awaiting_approval -> executing | cancelled | failed
executing -> streaming | completed | failed | cancelled | interrupted
```

client가 `completed` request를 직접 만들 수 없다. 알 수 없는 event, 중복 event,
순서가 맞지 않는 event는 sequence 규칙에 따라 무시하거나 거부하고 transcript를
망가뜨리지 않아야 한다.

### 13.3 Ollama provider 정책

기본 provider는 명시적인 local 설정으로 구성되는 Ollama adapter다. 예시는
`EEEE_OLLAMA_BASE_URL`, `EEEE_OLLAMA_MODEL`, connection timeout, generation
timeout, maximum context tokens다. 실제 설정 이름은 구현 중 바뀔 수 있지만
동작은 바뀌면 안 된다.

- Core가 ChatGPT Web, OpenHands, cloud model로 조용히 fallback하지 않는다.
- Ollama 없음, model 없음, timeout, 잘못된 output, provider 종료는 각각 다른
  retryable error code로 매핑한다.
- `/v1/runtime`은 Ollama가 없어도 Core health를 실패시키지 않고 Ollama 상태를
  unavailable로 보고한다.
- adapter는 streaming delta와 cancellation signal을 지원한다.
- context 구성은 token budget으로 제한한다. 현재 conversation의 최근 message와
  명시적으로 허용된 memory만 포함하고 전체 transcript를 무제한 로드하지 않는다.
- model은 일반 답변, clarification, typed action proposal 중 하나를 반환하도록
  요청받는다. 임의 executable path, plugin command, provider credential은 자유형
  model instruction으로 허용하지 않는다.
- system prompt는 EEEE를 local assistant로 설명하고, 설치되지 않은 capability를
  솔직하게 보고하게 한다. Core 실행 결과가 없으면 외부 작업이 완료됐다고 말하지
  않는다.

v1 자연어 분류는 hybrid로 한다. 결정론적 safety/capability 검사를 먼저 실행하고,
일반 대화와 모호한 intent는 Ollama가 처리한다. 이 방식은 LLM 장애가 단순 local
health/status 작업을 막지 않게 하며, model이 approval policy를 우회하지 못하게 한다.

### 13.4 저장, 마이그레이션, 재시작 계약

Core database는 current working directory가 아니라 명시적인 사용자별 app data
directory의 SQLite 파일 하나다. Windows 기본 위치는 `%LOCALAPPDATA%` 아래의
안정적인 EEEE data directory이고, test와 portable installation을 위한 override를
제공한다. 경로는 diagnostics에 표시하며 재실행한다고 조용히 바꾸지 않는다.

필수 저장 규칙:

- schema migration은 번호가 있고 transactional하며 schema table에 기록한다.
- 기존 project/request/memory table을 파괴적 reset 없이 보존/마이그레이션한다.
- `(conversation_id, client_message_id)` unique constraint를 둔다.
- message/event write는 API acknowledgement 전에 commit한다.
- foreign key, WAL mode, busy timeout을 일관되게 활성화한다.
- 하나의 Core instance가 write connection을 소유하고, process lock으로 같은
  data directory에 두 번째 Core가 시작되지 않게 한다.
- read client는 bounded query를 사용하고 write transaction을 붙잡지 않는다.
- credential/provider token은 기존 secure credential 경로에 저장하며 transcript나
  event payload에 넣지 않는다.

Core 시작 시 다음을 수행한다.

1. process lock을 얻고 database를 연다.
2. 보류 중인 migration을 적용한다.
3. stale `generating`, `streaming`, `executing` request를 startup recovery
   timestamp를 기준으로 `interrupted`로 만든다.
4. Ollama가 없어도 `/health`를 노출한다.
5. Desktop Shell이 마지막 cursor 이후 event를 replay하며 재연결할 수 있게 한다.

정상 종료 시 Core는 새 turn을 받지 않고, 활성 provider에 cancel을 요청하고,
event/message write를 flush한 뒤 lock을 해제한다. 강제 종료로 turn이 interrupted가
될 수는 있지만 완료된 message를 삭제해서는 안 된다.

### 13.5 Capability 및 plugin 수명주기 계약

Capability는 서로 독립적인 readiness 상태를 가진다: `not_installed`, `installed`,
`auth_required`, `ready`, `degraded`, `running`, `failed`, `removed`.
`installed`는 `ready`를 뜻하지 않으며, `failed`를 가짜 성공 답변으로 바꾸지 않는다.

모든 선택적 capability는 identity, entry point, protocol version, action, input/output
schema, permission, side-effect level, authentication method, health check, memory
scope를 포함하는 versioned manifest를 선언한다. Core가 등록 전에 manifest를
검증한다. 설치와 permission 승인은 명시적인 사용자 action이다. capability worker는
승인된 request가 선택할 때만 시작하고 idle policy 또는 명시적 disconnect 뒤 종료한다.
worker crash는 Core나 Desktop Shell을 종료시키지 않고 capability failure로 표시한다.

향후 Chat History plugin은 Core API client다. UI-local view state는 가질 수 있지만
Ollama를 새로 시작하거나, 두 번째 transcript database를 만들거나, Core permission을
우회할 수 없다. 이 방식으로 별도 plugin처럼 사용하면서도 비싼 runtime 중복을 막는다.

### 13.6 Desktop/Core 경계와 사용자 흐름

Desktop은 versioned Core API로만 통신한다. Ollama, SQLite repository, provider
client, project execution class를 import하지 않는다. Core가 unavailable이면 Desktop은
reconnect/error 상태를 표시하고 입력 중인 draft를 로컬에 보존한 뒤 사용자가 retry하게
한다. 다른 AI provider로 조용히 전환하지 않는다.

Shell은 다음 사용자 흐름을 만족해야 한다.

- 고양이 클릭: 다른 애플리케이션을 열거나 focus하지 않고 input bubble을 표시한다.
- Enter 제출: 입력한 text를 중앙에 표시한 뒤 기존 input text를 밑에 남기지 않고
  streamed answer로 전환한다.
- 답변 bubble 클릭: 기존 answer timer만 연장하지 않고 새로운 input turn을 시작한다.
- 긴 답변 수신: text block을 먼저 측정하고 asset padding을 추가한 뒤 측정된 content에
  맞춰 bubble을 키운다. 고정 한 줄 또는 24px text 영역을 사용하지 않는다.
- streaming 중, focus 중, approval 대기 중에는 자동 숨김하지 않는다.
- terminal answer 또는 terminal error 후 5초 뒤에 bubble만 숨긴다. transcript와
  request 상태는 유지한다.
- 사용자가 다른 앱에서 작업 중일 때 browser, terminal, ChatGPT Web, project window를
  자동으로 앞으로 띄우지 않는다.

### 13.7 검증 매트릭스

완료 보고서에는 모든 결과의 증거 등급을 표시해야 한다.

| 증거 등급 | v1 최소 증거 |
| --- | --- |
| 결정론적 | 문서화된 working directory에서 Core unit/API/state/migration 테스트 통과 |
| 로컬 runtime | 실제 Ollama model로 짧은 답변, 긴 답변, timeout, cancellation, model unavailable 오류를 검증 |
| 영속성 | 중지/재시작 후 conversation 보존, 중복 client submission 거부, interrupted turn 복구 |
| 패키징 Desktop | 선택적 runtime 없이 Shell 시작, Core 재연결, idle 때 Chrome/Node/ISEOL 미생성 |
| UI acceptance | 입력/답변 중앙 정렬, 긴 텍스트 확장, 답변 클릭 후 새 입력, 5초 숨김, focus 보존, draft 복구를 수동 또는 Qt/browser 테스트 |
| capability 경계 | 설치되지 않은 capability가 실제 상태를 보고하고 가짜 completed result를 반환하지 않음 |

기존 `450 passed, 1 skipped, 1 warning`은 결정론적 증거 등급에서만 유효하다.
local model, packaged application, live connector, 전체 user flow의 증거로 보고하면 안 된다.

### 13.8 첫 구현 계획의 완료 조건

구현 계획은 아래 항목을 각각 구체적인 작업과 테스트에 매핑한 뒤 시작한다.

- API schema와 event transition이 문서화되어 있다.
- Ollama 설정과 오류 동작이 고정되어 있다.
- database 경로, migration 순서, index, recovery 규칙이 고정되어 있다.
- v1 capability 범위가 고정되어 있다.
- Core/Shell import 및 process 경계를 강제할 수 있다.
- 검증 매트릭스에 실제 명령 또는 반복 가능한 수동 단계가 있다.
- compatibility 또는 migration note 없이 legacy endpoint를 삭제하지 않는다.

