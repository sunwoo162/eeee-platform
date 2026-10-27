# Gleave 방향성 점검 06 — 생명주기 복구 + 작업 감사 기록 UI

날짜: 2026-10-28
브랜치: feat/unified-chat
상태: 구현/회귀 테스트 후 CI 확인

## 검증에서 발견한 실제 결함

이전 코드에서는 create_app() 내부에서 FastAPI lifespan_context를 두 번 덮어쓰고
있었다. 앞에서 설정한 core_lifespan의 Codex 작업 종료 처리와 복구는 실제로
호출되지 않았다. 또한 CodexJournal 생성 시 곧바로 모든 running/queued/approval
상태를 interrupted로 변경해, 이미 다른 Core가 실행 중일 때 두 번째 앱을
단순 생성해도 작업 상태가 훼손될 위험이 있었다.

## 수정

- 실제로 적용되는 단일 application_lifespan에 Core process lock, Codex 복구,
  Codex subprocess shutdown, 기존 Core/ClaimLatch/assistant shutdown을 통합.
- CodexJournal 초기화는 복구 상태를 변경하지 않도록 구성; 복구는 Core lock
  소유 후에만 실행.
- 동일 데이터 경로에 두 번째 Core가 시작되면 실패하고, 실행 중인 Core의
  Codex 작업 및 승인 대기를 훼손하지 않음.
- 정상 종료/다음 재시작 시 이전 소유자의 미완료 기록만 interrupted 처리.
- 종료 시 CodexTaskManager.shutdown()이 정확히 한 번 호출되는 회귀 테스트.
- Codex 패널에 해당 채팅의 작업 이력 선택/조회, 승인 감사 타임라인 추가.
- 감사 데이터는 앱 서버에서 사용자/채팅 소유권을 확인하며 다른 사용자는 조회 불가.

## 제품 방향 점검

- 하나의 Gleave 창에서 프로젝트별 기록과 승인 결정을 다시 찾을 수 있음.
- Codex 실제 작업을 안전하게 취소·복구하므로 장기 개발 보조 제품 목표에 적합.
- 의도된 read-only 기본값 및 별도 write 승인을 변경하지 않음.

## 아직 남은 작업

- 실제 인증된 Codex agent를 사용한 파일 변경/테스트/승인/취소 E2E.
- GPT/Claude/Codex 비용·품질·지연을 계측하는 Auto Router, 정량 평가.
- 공식 내보내기 기반 과거 대화 Import 및 신뢰 범위별 기억 승인 UI.
- Windows 설치 없는 앱 패키징, 실 팀 인증 및 파일 브라우저/코드 diff 뷰어.
- task DB snapshots 이외의 장기간 세션 replay, WebSocket/SSE 이벤트 통합.

CI 성공과 실제 모델 실행 성공을 동일한 것으로 취급하지 않는다.
