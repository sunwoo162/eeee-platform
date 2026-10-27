# Gleave Unified Chat: 제품 및 시스템 설계 v1

상태: 구현 개시 / 2026-10-27
대상 기준: gleave-merge-clean HEAD 24defc1, 별도 worktree feat/unified-chat
목표: 다른 AI 앱을 옮겨 다니지 않아도 채팅, 학습, 설계, 개발, 파일 수정, 작업 검증을 수행하는 단일 로컬 우선 Windows 프로그램.

## 1. 사용자 경험 / 불변 조건

- 첫 화면은 ChatGPT처럼 단순한 채팅. 일반 대화에 IDE 패널을 강제로 노출하지 않는다.
- 개인 또는 팀 > 프로젝트 폴더 > 개별 채팅 순서로 관리한다. 채팅 제목이 아니라 명시적 projectId가 소속의 유일한 기준이다.
- 같은 프로젝트에 속한 채팅은 공통 프로젝트 기억을 검색한다. 다른 프로젝트/사용자의 원문 기록은 범위를 넘지 않는다.
- 모든 모델은 Gleave의 canonical transcript와 허용된 MemoryContextPacket을 사용한다. GPT/Claude/Codex의 내부 기억이 동기화되었다고 표현하지 않는다.
- Auto가 기본 모델 선택. 사용자는 특정 대화 또는 한 메시지에 GPT, Claude, Codex, 로컬 모델을 선택할 수 있다.
- 수동 선택 실패 시 임의의 다른 AI로 몰래 변경하지 않는다. 명시적 재선택 또는 사전 동의된 fallback만 허용한다.
- 모델이 변경되어도 화면의 대화 정체성, 메시지 순서, 작업 기록, 프로젝트 기억은 보존한다.
- 개발/도구 요청 시에만 파일 트리, diff, 터미널, 브라우저 미리보기, QA 패널이 열리는 progressive disclosure.
- 외부 발송, 삭제, 파일 쓰기, 배포, Git push 등 부작용은 실행 범위와 위험에 따라 승인한다.
- 답변 실패, 도구 미실행, 모델 부족, 인증 실패를 정상 완료로 저장하거나 꾸며내지 않는다.

## 2. 최상위 모듈

1. Gleave Client (React + Tauri 후보): 채팅/프로젝트 트리/모델 선택/필요한 작업 패널.
2. EEEE Core (기존 FastAPI): 대화 state machine, 권한, 메모리 컨텍스트, 라우팅 정책, SSE, audit.
3. Provider Hub: chat provider (GPT API, Claude API, 로컬)와 agent provider (Codex app-server/SDK, 향후 Claude Code)를 다른 계약으로 감싼다.
4. Task/Tool Runtime: sandbox와 승인, 파일 접근, 명령 실행, diff preview, browser preview, ISEOL 협업, ClaimLatch 검증.
5. Project Knowledge: 개인/팀 공간, 프로젝트 소속, 승인된 프로젝트 기억, 원본 검색·출처, 수정·철회.
6. Importer: 공식 대화 export + 로컬 에이전트 세션에서 초기 기록 가져오기, 중복 제거, 출처 추적.
7. Personal Learning: 사용자 소유/허가 데이터만 검토 후 학습 후보, 기존 eeee-personal-llm SFT/LoRA/Registry/rollback.

첫 단계에서는 기존 SQLite source of truth 하나를 유지한다. 모든 클라이언트가 같은 API를 호출하고 DB를 직접 수정하지 않는다.

## 3. 핵심 데이터 및 소유권

- chat_workspaces(id, kind personal/team, owner_user_id, name)
- chat_workspace_members(workspace_id, user_id, role)
- chat_projects(id, workspace_id, name)
- chat_conversation_links(conversation_id UNIQUE, project_id, linked_by, linked_at)
- chat_project_memories(id, project_id, content, source_message_id, creator, status)
- 기존 conversations/messages/assistant_requests/events는 변경 없이 canonical 대화 원본 유지.
- 같은 채팅은 동시에 한 프로젝트에 속한다. 이동 시 link만 갱신하고 원본 메시지/기억 원본은 보존.
- 채팅 원문은 자동으로 확정된 사실이 되지 않는다. 명시적 프로젝트 메모리와 원본 검색 결과를 구분한다.
- 앞으로 memory facts에 source, confidence, effective_at, supersedes, revision, allowed_scopes, privacy_class를 추가한다.
- 기존 project execution의 projectId와 chat folder projectId는 다른 개념. 명시적 연결 테이블로 연계한다. ID를 합치거나 암묵적으로 공유하지 않는다.

## 4. 기억 조회 및 충돌 처리

입력: principal, workspace, projectId?, conversationId, latest user request, intent, permission.

1. ACL 평가. 팀에 공유되지 않은 개인 기억, 남의 채팅 원문은 제외.
2. 현재 대화의 최신 메시지(필수)를 우선 예약.
3. 승인된 유효 개인 기억(개인 공간에서만)과 승인된 프로젝트 기억 로드.
4. 같은 projectId의 검색 가능한 타 채팅 원문을 출처/확신 수준과 함께 참조. 첫 버전은 본인 작성 발화만, 나중에 BM25+벡터 검색.
5. 모순/변경 시 무조건 최신 데이터로 덮지 않음. source evidence, 승인, revision 추적 후 적용.
6. 민감정보 필터, 데이터 출처 표기, 프롬프트 인젝션 방어. 검색 문서는 명령이 아닌 비신뢰 참고자료.
7. provider token budget에 맞춰 canonical packet 구성, 실제 선택 provider에 필요한 부분만 전달.
8. 철회/삭제/프로젝트 이동 후 다음 답변에서 즉시 반영. 삭제 시 임베딩/인덱스/캐시도 정리.

첫 구현: 명시적 프로젝트 폴더, 채팅 링크, 승인된 프로젝트 메모리 CRUD, 동일 사용자 타 채팅의 bounded 참고자료.
후속 구현: 의미 검색, 증거 기반 결정 추출, 프로젝트 요약, 메모리 승인 UI 및 팀별 공유 정책.

## 5. 모델 자동/수동 선택 계약

모델 단위 metadata:
providerId, modelId, runtimeType(chat|agent|local), capabilityFlags,
contextWindow, maxOutput, priceIn, priceOut, toolSupport, region, health, availability.

RouteRequest:
requestId, workspaceId, projectId, conversationId, currentTurn,
requestedMode(auto|manual), requestedProvider?, requestedModel?, qualityProfile,
maxSpend?, maxLatency?, privacyPolicy, needsFilesystem, needsTools, contextBudget.

Auto 선택:
0. 명시적으로 설정된 보안·오프라인·데이터 전송 제한 먼저 필터.
1. intent (잡담/학습/정보/문서/개발/도구) + 실제 액션 필요 여부 판별.
2. 현재 사용 가능한 모델 목록(고정 명칭을 하드코딩하지 않음), capability·context·가격 조회.
3. 예측 품질, 추정 input/output tokens, 금액, latency, 실패율을 종합하여 선택.
4. 초기에는 검증 가능한 결정론적 규칙 + 기준선으로 시작하고, 실측 결과로 점진 조정.
5. 여러 모델 협업은 기본 OFF. 하나로 실패할 확률/중요도 높을 때만 선택적 검증 사용.

수동 선택:
- 한 턴 임시 지정 / 현재 채팅 기본 모델 설정은 별개.
- 선택 불가·한도 초과·인증 실패 시 실패 상태를 반환. 사용자 동의 없는 provider 변경 금지.
- Codex는 일반 텍스트 모델과 달리 파일 수정·실행 agent runtime. 작업 권한을 별도 검사.

Audit:
requestedMode, chosenProvider, chosenModel, reasonCodes, versions,
estimatedTokens/actualTokens, costEstimate/actualCost, latency, toolRuns, fallback,
resultState, costCurrency, timestamps. 예상값과 확정값을 혼동하지 않음.
ChatGPT 구독과 API 결제는 별개일 수 있고 각 제공자 인증 정책에 맞게 연결한다.

## 6. 에이전트 도구 및 개발 작업

- Workspace path 명시: 프로젝트 루트 외부 접근은 기본 거부. path traversal, symlink, 프로세스 환경변수/credential 유출 방지.
- 작업 계획 → diff/명령 제안 → 권한 체크 → 실행 → stdout/stderr + exit code 기록 → 검증 → 최종 결과.
- read/search는 허용 범위 내 자동 수행 가능. 파일 쓰기, 파괴적 명령, Git push/배포/외부 발송은 risk-based approval.
- 작업별 timeout, cancel, retry idempotency, 작업 중 단절 및 재시작 복구 필요.
- 터미널/파일 트리/코드 diff/웹 미리보기는 채팅 우측 선택 패널. 일반 채팅은 숨김.
- ISEOL은 프로젝트 규모의 실행·QA, ClaimLatch는 필요한 사실 주장/완료 검증에만 적용.
- 작업 결과를 단순 모델 텍스트로 완료 표시하지 않음: 실제 파일 diff, 테스트 기록, 승인 영수증을 사용.
- 첫 v1에서는 기존 ISEOL과 Codex SDK/app-server 계약을 조사해 단계별 연동하며 전체 VS Code 호환 IDE를 구현하지 않는다.

## 7. 과거 대화 가져오기와 지속 동기화

- Gleave에서 생성되는 모든 신규 메시지는 첫날부터 canonical transcript로 자동 저장.
- ChatGPT/Claude의 과거 기록은 공식 내보내기 파일에서 사용자 동의로 가져온다. 외부 사이트 로그인만으로 전체 이력을 읽을 수 있다고 가정하지 않는다.
- Codex/Claude Code는 공식 지원 세션 export 또는 로컬 파일을 사용자 허락 하에 incremental import.
- source provider + source conversationId + messageId + contentHash를 dedupe key로, import job/checkpoint를 저장.
- 가져오기 전 미리보기, 대상 프로젝트 매핑, 민감 채팅 제외, 진행률, 취소, 재시도, 삭제/재가져오기 제공.
- UI는 직접 채팅 작성과 데이터 import를 구분. imported fact는 자동 승인/자동 LoRA 학습하지 않는다.
- 외부 소비자 웹 채팅의 실시간 동기화는 공식 API 접근이 허용될 때만 지원 범위 명시. 현재 지원되지 않는 수단은 약속하지 않는다.

## 8. 개인화 LLM 운용

- 초기 채팅 품질은 GPT/Claude 등 연결된 검증된 모델을 활용.
- 기존 Qwen2.5-0.5B+LoRA는 local/experimental/shadow profile로 운영하고 실측 품질이 낮으면 자동 응답에서 제외.
- 장기 기억은 데이터베이스에 보관해 즉시 반영. model weights는 승인된 학습 데이터로만 반복 학습.
- 모델 공급자 출력과 저작권/계약 제한이 있는 데이터는 임의로 자체 모델의 교사 정답으로 사용하지 않는다.
- 학습 시 conversation-level train/val/holdout 분리, bias, 실제 한국어 멀티턴, 오탈자, 정보 충돌, 개인정보 누출, latency 확인.
- baseline보다 악화되면 승격 금지, registry rollback, 사용자 opt-in/opt-out, 데이터 삭제/학습 중지.
- 모델이 똑똑해지는 것과 공용 기억이 늘어나는 것을 대시보드에서 명확히 구분.

## 9. 보안 / 팀 공동작업 계획

현재 로컬 API는 loopback + X-EEEE-User-Id 스코핑이며 원격 인증된 여러 사용자의 신원 증명이 아니다.
이 신뢰 경계에서는 팀 폴더 라벨/기본 데이터 모델만 제공한다.
다른 사람 초대·네트워크 공유·공동 작업은 아직 켜지 않는다.

팀을 실제로 공개하기 전 필수:
- OS 로컬 앱 인증 또는 중앙 identity/OIDC, 사용자 토큰 audience/expiry 검증.
- 팀 owner/editor/viewer 역할, 프로젝트별 별도 ACL, 초대 승인/해지, 접속 감사.
- 사용자 비밀이 포함된 원본 대화는 team membership만으로 읽을 수 없음.
- 팀 기억은 explicit reviewed 공유만, 개인 global memory는 team 채팅에 자동 전달 금지.
- 원격 DB 동기화/E2EE 필요성 결정, 충돌 해결, device revoke 및 backup/export/delete.
- 공급자 API key는 앱 안전 저장소 또는 OS credential store; 로그·Git·프롬프트/학습 데이터에 저장 금지.

## 10. UI / UX

기본 레이아웃: 왼쪽 사이드바 + 중앙 채팅. 작업 실행 시에만 우측 도구 드로어.
사이드바: 새 채팅, 전체 검색, 개인/팀 공간, 접을 수 있는 프로젝트, 프로젝트별 채팅, 고정/보관.
상단: 프로젝트 위치, Auto/수동 모델 선택. 메시지 단위 override와 채팅 기본값 구분.
입력: 첨부, 이미지, 취소, 다시 생성, 채팅 편집. 스트리밍 동안 상태·사용 모델은 요청 시 확인.
프로젝트: 폴더 생성/이름변경, 드래그로 채팅 이동, 동일 프로젝트 기억과 연결된 파일, 기억 수정/철회.
도구 드로어: 실행 계획, 파일 트리, 코드 diff, 터미널(권한), 테스트 결과, 브라우저 미리보기.
오류: provider unavailable / approval needed / paused / cost cap / timeout 구분. false success 금지.
접근성: 키보드 검색, screen reader label, 빠른 전환, 레이아웃 유지, 밝은 테마 기본.
대량 기록: 가상 스크롤, 페이지네이션, 프로젝트별 검색, requestId 기반 중복 전송 방지.

## 11. 마이그레이션과 기존 자산

- Gleave master 데이터 원본은 기존 SQLiteStore와 ConversationStore 그대로 사용.
- EEEE가 chat routing 소유; UI가 DB나 개인화 LLM API를 직접 호출하지 않음.
- chat folder project는 project-execution runtime project와 별도 테이블로 시작.
- 오래된 채팅은 unassigned로 남고 사용자가 폴더로 이동하면 링크/컨텍스트 활성화.
- 기존 데이터는 destructive migration 금지, 사전 backup + 버전별 migration 회귀 테스트.
- 작업 시작 기준은 git worktree feat/unified-chat, 기존 gleave-merge-clean/eeee-platform/개인 LLM 원본 유지.
- 이전 개인 비서/펫은 선택적 기능으로, 새 메인 UI는 채팅으로 전환.

## 12. 단계 / 완료 판정

P0(진행 중) 데이터 경계: workspace/project/chat 링크, 수동 프로젝트 메모리, ACL, 프로젝트 컨텍스트, unit/API tests.
P1 새 UI: chat/project sidebar, 기본 대화 SSE, 링크 이동, 메모리 편집. 앱 내 chat-first 경험.
P2 Provider Hub: GPT·Claude·Codex 연결, manual selection, explicit fallback, per-turn provenance. 실제 사용 테스트.
P3 Agent Studio: sandbox/approval/diff/terminal/preview, 취소/복구, 파일 수정·검증 E2E.
P4 Smart Router: 프로파일별 품질/비용/지연 실측, Auto v1, 비용 상한, 비교 리포트.
P5 Importer+고급 기억: 초기 공식 export, local agent logs, provenance/dedupe, 후보 승인/충돌 UI, 벡터 검색.
P6 Personal LLM: shadow/eval/opt-in 학습 및 선택적 라우팅.
P7 Authenticated teams: 초대/ACL/동기화/원격 접근 검증.

v1 핵심 시나리오:
1. 한 프로그램을 열어 개인 프로젝트 만들고 여러 채팅 생성/이동.
2. 채팅 A에서 저장한 승인된 결정이 동일 프로젝트 B에만 나타남.
3. 다른 프로젝트로 옮겼을 때 이전 프로젝트 맥락 누락 확인; 원본 메시지 불변.
4. GPT/Claude 수동 선택 및 Auto; 실제 모델과 실패를 감사하고, 선택된 Codex가 로컬 워크스페이스에서 승인받아 수정.
5. 팀 유출/경계 테스트, 모델 다운/중복 제출/재시작 복구, 비용 상한 테스트.
6. 기존 앱 테스트 통과 + 패키징된 Windows 앱 실실행 smoke/E2E. 테스트 통과만으로 API 로그인이나 실제 개발 실행 성공을 주장하지 않음.

## 13. P0 이번 구현 범위

- schema_migrations v6: chat_workspaces / members / projects / links / curated memory.
- FastAPI /v1/workspaces, /v1/workspaces/{id}/projects, /v1/projects/{id}/conversations, /v1/projects/{id}/memories.
- ConversationContextBuilder에서 같은 프로젝트의 승인된 memory와 제한된 본인 작성 sibling excerpts 사용.
- 팀 프로젝트에서 개인 전역 기억 자동 주입 차단.
- 확정되지 않은 타 대화 내용은 reference only; 검증된 메모리와 다르게 표시.
- 팀 멤버 초대 API, 외부 AI 연결, UI, 실제 팀 공유, embeddings, 자동 LoRA 재학습은 이 단계에서 제공하지 않는다.
