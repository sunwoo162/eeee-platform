# EEEE Desktop Assistant Product Implementation Plan

> 이 계획은 `docs/superpowers/specs/2026-10-08-eeee-desktop-assistant-product-design.md`를 구현하기 위한 기준이다.

## 목표

사용자가 바탕화면의 EEEE 펫에게 자연어로 말하면 EEEE가 일반 대화 또는 설치된
plugin을 선택하고, 개발 요청은 ISEOL에 위임하여 백그라운드에서 실행·검증·보고하는
실제 Desktop Assistant를 만든다.

## 고정된 기술 경계

- Python 3.12 / FastAPI: EEEE Core, API, SQLite, local supervisor
- PySide6: Desktop pet와 Workspace shell
- TypeScript / Node.js / Playwright: ISEOL web bridge와 browser evidence
- SQLite: 실행 원장과 재개 정보의 source of truth
- ChatGPT Web: reasoning provider. 파일·명령·테스트 실행 권한 없음
- Local Agent Runtime: workspace read/write/run의 유일한 실행 경계
- ClaimLatch: claim·agent result·side effect·release·memory promotion gate

## 세션 규칙

- 각 세션은 RED 테스트 → 최소 구현 → GREEN → 회귀 테스트 순서로 진행한다.
- 기존 사용자 변경은 보존한다. 광범위한 reset, checkout, 삭제를 하지 않는다.
- 성공 보고는 실제 명령 출력과 증거가 있을 때만 한다.
- 세션 완료 조건을 통과하지 못하면 다음 세션으로 진행하지 않고 원인을 먼저 해결한다.
- UI가 떠도 실제 요청·상태·파일·검증이 연결되지 않으면 완료로 인정하지 않는다.

---

## Session 0 — 기준선·범위·실행 계약

### 목적

기존 구현의 실제 상태와 문서 설계를 대조하고, 이후 작업의 재현 가능한 검증 명령을 고정한다.

### 작업

- 전체 Python, TypeScript, adapter, packaged self-test 기준선 실행
- 현재 API route, desktop entrypoint, bridge port, runtime selection 기록
- 기존 dirty worktree와 생성 산출물을 보존하면서 테스트 격리 규칙 정리
- EEEE/ISEOL/ClaimLatch 간 현재 계약의 중복·충돌 목록 작성

### 완료 조건

- 기준선 테스트 명령과 결과가 `docs/operations/`에 기록됨
- 테스트 실패가 기능 실패인지 환경 실패인지 분류됨
- 이후 세션에서 사용할 `verify-all` 명령이 재현 가능함

---

## Session 1 — EEEE Desktop Pet와 Workspace 경계

### 목적

사용자에게 보이는 기본 화면을 EEEE 중심으로 만들고, 펫 종료와 백그라운드 서비스 종료를 분리한다.

### 작업

- 펫 기본 화면에서 프로젝트 전용 문구·카드 제거
- 일반 대화 입력, Enter 전송, Esc 닫기, 클릭/우클릭 동작 고정
- Pet Host와 Quick Chat을 독립적인 top-level Qt tool window로 분리
- Quick Chat에 백그라운드 작업 상태와 최신 응답을 표시
- Ctrl+클릭 Workspace를 브라우저가 아닌 데스크톱 control center로 제공
- 펫 우클릭 프로필에서 로컬 이름·기본 아바타를 저장·변경
- Workspace에 대화·진행 중·프로젝트·plugin·기억·설정 메뉴 구성
- 펫 window close는 UI만 닫고 supervisor/API는 유지
- 명시적 종료 명령에서만 백그라운드 서비스 종료
- 한국어 기본 UI와 영어 선택 상태 보존

### 검증

- PySide6 UI smoke test
- Enter/Esc/window close interaction test
- 기본 실행 시 `Ready for a development request` 같은 개발 전용 문구가 없음
- 일반 대화 route가 project-execution으로 오인되지 않음

### 완료 조건

사용자는 기본적으로 캐릭터와 말풍선만 보고, 전체 Workspace를 열었을 때만 EEEE control center를 본다.

---

## Session 2 — 백그라운드 Supervisor와 실행 원장

### 목적

긴 프로젝트 실행을 HTTP 요청에 묶지 않고, Desktop 백그라운드에서 checkpoint 단위로 실행·재개한다.

### 작업

- 실행 상태 머신 구현: `REQUESTED → PLANNING → PROVISIONED → RUNNING → QA_RUNNING → VERIFYING → RELEASED`
- 예외 상태 구현: `PAUSED`, `BLOCKED`, `FAILED`, `CANCELLED`, `INCONSISTENT`
- SQLite execution/event/job store 계약 확정
- `POST /api/assistant/route`가 accepted + `executionId` + `projectId`를 즉시 반환
- Supervisor worker와 lease/heartbeat/재시작 복구 구현
- 각 단계 완료 전 atomic checkpoint 저장
- 중복 side effect 방지용 idempotency key 적용
- `execution-plan.json`, `PROJECT_LOG.md`는 원장 projection으로 변경

### 검증

- 프로세스 중단 후 마지막 checkpoint에서 재개
- 이미 PASS한 Agent가 재실행되지 않음
- stale revision 및 동시 실행 충돌 테스트
- route 응답이 장시간 provider를 기다리지 않음
- 사용자에게 상태 이벤트가 순서대로 전달됨

### 완료 조건

Desktop을 닫았다가 다시 열어도 작업 상태가 유지되고, 실패한 단계부터 재개된다.

---

## Session 3 — EEEE 일반 대화와 Plugin Router

### 목적

EEEE를 프로젝트 전용 비서가 아니라 모든 요청의 단일 진입점으로 안정화한다.

### 작업

- conversation / local action / plugin work / project work intent 분리
- 일반 대화는 ChatGPT Web provider로 전달하되 사용자에게 provider 창을 노출하지 않음
- provider 실패를 EEEE 사용자 메시지로 변환
- plugin manifest, permissions, connection state, pause/resume 상태 정리
- 설치·연결·정지·재개·필요 plugin 안내를 자연어로 처리
- plugin이 없을 때 fake success 금지

### 검증

- “안녕”, 일반 질문, 기억 질문이 ISEOL로 가지 않음
- “todo 앱 만들어줘”만 project plugin으로 라우팅됨
- paused/disconnected plugin은 자동 선택되지 않음
- provider 401/503/timeout이 사용자 친화적 BLOCKED 상태가 됨

### 완료 조건

사용자는 EEEE와만 대화하고, 어떤 plugin이 내부에서 사용되는지 몰라도 정상적으로 결과를 받는다.

---

## Session 4 — ChatGPT Web reasoning provider 안정화

### 목적

ChatGPT Web은 판단만 하고, 로컬 실행은 Desktop runtime이 담당하는 경계를 실제로 보장한다.

### 작업

- agent action JSON schema 고정
- specialist별 bounded conversation 정책 적용
- malformed JSON correction budget과 transient retry budget 분리
- browser identity drift 복구 및 stale conversation 차단
- provider 응답에 side effect가 포함되어도 로컬 runtime 승인 없이는 실행하지 않음
- 인증·브라우저 상태를 EEEE DB나 Agent prompt에 노출하지 않음

### 검증

- JSON 오류·identity 변경·503·timeout별 recovery test
- provider가 명령을 반환해도 LocalAgentRuntime의 허용 action만 실행
- 동일 요청 retry가 파일을 중복 변경하지 않음
- 단일 provider session이 병렬 Agent 요청을 섞지 않음

### 완료 조건

provider가 느리거나 실패해도 전체 프로젝트 원장이 일관된 BLOCKED/재시도 상태로 남는다.

---

## Session 5 — ISEOL Agent DAG·checkpoint·handoff

### 목적

프로젝트 개발 조직을 실제 실행 가능한 Agent 운영체제로 만든다.

### 작업

- Project Brief를 requirements, design, architecture, implementation, QA, release 단계로 변환
- Workstream별 하위 Agent를 규모·위험도에 따라 동적 생성
- `AgentRequest`, `AgentResult`, `AgentExecutionRecord`, `Handoff` 계약 정리
- dependency가 통과한 Agent만 다음 Agent에 전달
- 결과·변경 파일·테스트·evidence·ClaimLatch receipt 저장
- Agent별 retry/reflection/replan 정책 구현
- 병렬 실행은 workspace 충돌이 없는 노드에만 허용
- 코드 리뷰 Agent는 구현 Agent와 독립된 fresh context로 실행

### 검증

- dependency DAG 순서와 병렬성 검증
- runtime 미설정 시 BLOCKED
- Agent 결과가 evidence 없이 PASS할 수 없음
- 실패 노드 의존 작업이 자동 BLOCKED
- 재시작 후 완료된 handoff 유지

### 완료 조건

ISEOL이 실제 파일과 명령을 통해 프로젝트를 만들고, 각 Agent의 책임·증거·handoff가 추적된다.

---

## Session 6 — ClaimLatch·독립 QA·Release Gate

### 목적

“완료”라는 보고가 실제 결과와 일치하도록 전역 신뢰 경계를 연결한다.

### 작업

- Agent claim/result verification
- evidence 파일 존재·SHA256·revision·시간·출처·중복 확인
- 결정론적 QA 실행기 연결
- browser E2E, responsive, accessibility, security, encoding 검사 연결
- `QA_REPORT.json`, `RELEASE_MANIFEST.json` 생성
- 동일 `projectId + projectRevision` 확인
- ClaimLatch PASS + deterministic QA PASS + release manifest consistency 조건 적용
- memory promotion은 release gate 이후에만 허용

### 검증

- 파일·테스트·보고 내용 불일치 차단
- stale revision 차단
- ClaimLatch unavailable 시 완료 금지
- QA 실패가 release/memory 승격을 차단
- WARN과 BLOCK의 사용자 보고 구분

### 완료 조건

증거 없는 성공 보고, 다른 revision의 테스트 재사용, 검증되지 않은 기억 승격이 모두 불가능하다.

---

## Session 7 — Project Progress Organization View

### 목적

사용자가 프로젝트의 모든 작업과 커밋·검증 위치를 조직도형 화면에서 확인하게 한다.

### 작업

- 프로젝트 카드 클릭 시 상세 실행 맵 진입
- DAG 노드 상태·진행률·의존성·현재 Agent 표시
- 노드별 변경 파일, 명령, 로그, evidence, ClaimLatch 결과 표시
- 현재 commit/revision과 다음 작업 표시
- 실패 노드 재시도, 일시정지, 취소 동작
- 기본 요약과 고급 상세 보기 분리

### 검증

- 실제 event store 변화가 UI에 반영됨
- 새로고침·재실행 후 동일 상태 복구
- 완료·차단·실패 노드 색상과 텍스트가 명확함
- 대형 DAG에서도 읽을 수 있는 축소/확대·스크롤 제공

### 완료 조건

“지금 어디서 무엇을 하고 있고, 어떤 커밋과 검증이 있었는가”를 사용자가 화면에서 확인할 수 있다.

---

## Session 8 — 실제 Todo Live E2E

### 목적

설계의 최종 핵심 시나리오인 `todo 앱 만들어줘`를 실제로 끝까지 검증한다.

### 실행 시나리오

1. EEEE 펫을 실행한다.
2. 일반 대화가 되는지 확인한다.
3. “todo 앱 만들어줘”를 입력한다.
4. 즉시 accepted 상태와 진행 화면을 확인한다.
5. Desktop을 닫았다가 재실행한다.
6. 마지막 checkpoint에서 계속 진행되는지 확인한다.
7. 생성된 앱을 실제 브라우저에서 연다.
8. 추가·수정·완료·필터·삭제·새로고침을 수행한다.
9. 반응형·인코딩·테스트·ClaimLatch·Release Manifest를 확인한다.
10. 검증 통과 후에만 EEEE가 완성 결과를 보고하는지 확인한다.

### 완료 조건

위 흐름이 실제 파일·실제 브라우저·실제 evidence를 남기며 한 번의 사용자 명령으로 완료된다.

---

## Session 9 — Packaging·Recovery·전체 회귀

### 목적

개발 환경이 아닌 사용자의 설치·재부팅 환경에서 재현 가능한 상태로 만든다.

### 작업

- PyInstaller packaged executable 검증
- 중복 프로세스 감지·정리·단일 인스턴스 정책
- 포트 충돌·Qt DLL·브라우저 bridge 오류의 사용자 안내
- 재부팅 후 자동 시작/수동 시작 정책 검증
- root verification script와 release checklist 정리
- 사용자에게 제공할 실행법·로그 수집법·문제 해결 문서 갱신

### 최종 완료 조건

- 일반 대화가 실제 응답함
- project request가 실제 프로젝트를 생성함
- 백그라운드 작업과 재개가 동작함
- 조직도형 진행 화면이 실제 원장을 표시함
- QA·ClaimLatch·Release Gate가 실제 증거를 검사함
- packaged 실행 파일이 재부팅 후 실행됨
- 전체 회귀 테스트가 통과함
- 실패 시 완료라고 거짓말하지 않음

