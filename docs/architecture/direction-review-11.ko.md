# Gleave 방향성 점검 11 — 기억 충돌 교체와 명시적 API 품질 평가 실행

기준: 2026-10-28, 개발 브랜치 feat/unified-chat

## 변경 요약

### 충돌 해결을 별도의 승인 작업으로 구성
- 이전에는 AI가 기존 승인 기억과 충돌한다고 제안하면 사용자는 새 기억을 추가하거나 후보를 제외하는 선택만 가능했음.
- 이제 해당 후보의 모델 분석이 conflict이고 참조 ID가 실제 현재 프로젝트 승인 기억에 있을 때, 그 **기존 기억 하나를 새 결정으로 교체** 가능.
- POST /v1/imports/projects/{project_id}/memory-candidates/{message_id}/replace
  요청은 memoryId, content, expectedVersion, acknowledgedRisk를 모두 확인.
- 요청한 사람의 imported user-role 원본 메시지에 한정하며 소속 프로젝트/사용자 접근 권한,
  확정된 AI 분석 레코드, 참조한 기존 기억 ID, 현재 승인 기억 목록의 digest,
  대상 기억의 revision version, 위험 확인 및 중복·민감정보 필터를 검증.
- **동일 SQLite 트랜잭션** 안에서 기존 기억의 내용/출처를 교체하고 버전 이력 및
  해당 새 후보의 reviewed=approved 상태를 기록.
- 중간 실패 시 기존 기억이 바뀌거나 후보가 승인 상태로 남지 않음.
- 기존 memoryId는 유지하고 변경 전후 내용/새 출처 메시지가 revision에 기록.
  새 기억을 하나 더 추가해 서로 충돌하는 확정 기억을 만드는 일을 줄임.
- UI에서 기존 승인 기억을 비교한 후, 위험 확인 체크와 교체 확인 창을 통해서만 실행.

### 모델별 분석 품질 측정의 실행 기반
- app.conversation_imports.prompts.build_review_prompt를 프로젝트 분석과
  오프라인 평가 실행에서 공유해 서로 다른 프롬프트로 평가하는 오류를 방지.
- app.conversation_imports.evaluation_runner CLI를 추가해
  합성 JSON benchmark를 GPT/Claude API에 보낼 수 있는 **명시적 선택형 경로** 제공.
- 안전한 기본 실행은 DRY RUN. --execute --confirm-api-charges와
  --output을 직접 지정해야 호출하며 API 키가 연결되지 않으면 실행 불가.
- 1번 요청에서 최대 8개의 합성 사례만 호출. 모델 선택 고정,
  실패 시 다른 공급자로 자동 전환하지 않음.
- 결과는 caseId/provider/model/verdict/relatedMemoryIds/elapsedMs/evaluatedAt으로 저장.
  기존 evaluation.score_reviews로 정답 판정률, 충돌 precision/recall,
  잘못 인용된 기억 ID 등을 비교 가능.
- 현 테스트는 FakeHub로 호출 계약을 점검했고 **실제 GPT/Claude 품질 점수는 아직 없음**.
- token 사용량/실제 과금액은 응답에서 측정하지 않으며, latency만 측정.

## 수동 실행 방법

1. cd apps/eeee
2. python -m app.conversation_imports.evaluation_runner --gold ../../docs/architecture/memory-review-benchmark.json --provider gpt
3. 실제 API 과금 가능. 명시 동의 후에만 다음 명령 실행:
   python -m app.conversation_imports.evaluation_runner --gold ../../docs/architecture/memory-review-benchmark.json --provider gpt --max-cases 4 --execute --confirm-api-charges --output predictions-gpt.json
4. python -m app.conversation_imports.evaluation --gold ../../docs/architecture/memory-review-benchmark.json --predictions predictions-gpt.json

## 제품 방향 점검

- 여러 공급자를 단일 Gleave에서 선택하고, 프로젝트별로 출처가 있는 기억을 유지하며,
  AI가 추론한 것은 사용자에게 제안하고 그 결정권은 사용자에게 돌리는 목표에 부합.
- AI의 분류만으로 기록을 조작하거나 서로 다른 프로젝트 문맥을 합치지 않음.
- main 병합은 하지 않고, 검증된 기능별 커밋만 feat/unified-chat에 Push.

## 남은 한계

- 모델 판정 자체는 사실 검증이 아니고 선택한 새 기억도 사용자가 확인해야 함.
- 모델 분석시 원본 후보 1개와 승인 기억 일부가 선택한 외부 API에 전송될 수 있음.
- 실제 유료 모델 E2E, 품질 점수 평가, 예산/토큰 계측은 별도 검증 대상.
- 휴리스틱 후보에 해당하지 않는 문장 검토 UI, 기억 동기화/버전 갈등 관리 고도화,
  인증된 팀 권한, Windows 독립 실행/설치 및 사용자 E2E가 남아 있음.
