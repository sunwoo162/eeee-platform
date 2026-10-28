# Gleave 방향성 점검 10 — 변경 가능한 프로젝트 기억과 AI 분석 평가 기반

기준: 2026-10-28 · feat/unified-chat

## 구현 범위

### 기억 수정·철회 이력
- 프로젝트별 `chat_memory_revisions` 스키마 v13 추가: 생성/수정/철회 시점, 수정자, 전후 내용, 원본 메시지 ID, 버전 정보를 추가 기록.
- 기존 승인 기억을 안전하게 이전: 현재 상태의 'legacy_snapshot'만 남김.
  기록이 없었던 과거 변경 내역을 추측하거나 임의로 채우지 않음.
- memory edit API는 `expectedVersion` 필수. 낡은 브라우저 상태에서 충돌하는 수정을 막으며, 변경 내용과 감사 기록은 동일 DB 트랜잭션에서 처리.
- 기존 delete API는 status=revoked로 바꾸고 이력에 철회 이벤트를 남김.
- 기억을 수정/철회하면 프로젝트 컨텍스트는 실시간으로 active 내용만 가져옴.
- 기존 `chat_memory_reviews`을 통한 AI 후보 승인도 최초 생성 이력을 함께 추가.

### 출처 추적
- `GET /v1/projects/{project_id}/memories/{memory_id}/history`
  - 생성 시 링크된 원본 메시지와 실제 대화 제목
  - 출처가 import였다면 원본 제공자와 원본 대화 ID
  - 수정/철회 작업의 버전 및 시간
- 팀 기억은 공유 가능하지만 **원본 대화가 다른 멤버 개인 소유라면 원문과 원본 대화 제목/ID를 공개하지 않음.**
- 원본 대화를 삭제했을 때 링크가 없을 수 있으나 현재 승인 기억과 이력은 보관.

### 비교 실험의 기준
- `app.conversation_imports.evaluation`: 사용자 제공된 모델별 분석 JSON을 읽는 **오프라인 평가기** 추가.
- 합성 고정 시나리오 `docs/architecture/memory-review-benchmark.json`:
  새로운 프로젝트 목표, 명시적 중복, 충돌, 의문형, 서로 무관한 기술 선택, 애매한 과거 발언 등.
- 모델별 판정 일치율, 유효 응답 coverage, 근거 ID 정확히 일치한 비율,
  잘못 인용된 메모리 ID 수, 충돌 precision/recall 계산.
- 평가기는 GPT/Claude를 직접 호출하지 않으며, 실제 API/구독 과금·데이터 업로드·기억 수정도 하지 않음.
- 예: `cd apps/eeee; python -m app.conversation_imports.evaluation --gold ../../docs/architecture/memory-review-benchmark.json --predictions <your-predictions.json>`
  예측 JSON은 객체 배열로 `caseId`, `provider`, `verdict`, `relatedMemoryIds`를 갖추어야 함.
- **지금의 CI 성공은 실제 유료 모델 품질을 측정한 것이 아니다.** 사용자 동의가 있는
  별도 실제 실행 결과를 수집해야 모델별 점수 비교를 주장할 수 있음.

## 방향과 한계
- 유지: 개인/프로젝트/채팅 Scope, 출처 명확성, AI 제안과 사람의 승인 구분,
  Codex 파일 변경 별도 허가, 인위적 타사 모델 학습 금지.
- 현실적 제한: 현재 API 권한은 로컬 사용자 헤더 계약이고 생산용 팀 인증·감사 로그
  무결성 서명은 미완성. 삭제/철회 이력은 일반 DB 운영자가 수정 가능하며
  변조 불가능한 불변 원장이 아님.
- 수정 전후 내용을 기록하므로 DB에 개인정보가 남을 수 있어 추후 보유 기간·완전 삭제
  정책이 필요함. 팀원이 보기 전에 과거 원문이 비공개인지 확인해야 함.
- 사용자가 UI에서 이력을 확인해 내용을 수정할 수 있게 했지만 실제 Windows
  패키지 UI 수동 E2E는 별도 검증이 필요함.
- 의미상 중복은 AI 제안으로만 평가하며 오판 가능. 참조 근거 ID 체크는 사실성 검증을 의미하지 않음.

## 다음 과제
- 삭제/보유 기간/감사 정책과 복원 UI, 이전 기억 철회 및 상충 정리 지원.
- 실제 가입된 GPT/Claude 모델을 동의 기반으로 호출한 품질 벤치마크 수행.
- 앱 자체 Windows 실행 파일 패키징 및 사람의 수동 플로우 E2E.
