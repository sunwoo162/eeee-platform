# EEEE native 자연어 프로젝트 실행 계약

이 문서는 EEEE가 사용자의 한 문장 요청을 실제 로컬 프로젝트로 바꾸는
현재 계약이다. 플러그인 자체 구현은 이 단계의 범위가 아니며, 외부 계정이나
외부 리소스에 대한 변경을 성공으로 가장하지 않는다.

## 실행 순서

1. `POST /api/assistant/route`가 원문을 받는다.
2. `NaturalLanguageIntake`가 원문을 보존하면서 `ProjectIntent`를 만든다.
3. 프로젝트 ID와 workspace를 먼저 저장한다. 백그라운드 작업이 재시작돼도
   같은 ID와 revision을 사용한다.
4. 네이티브 Python `AgentGraphCompiler`가 요청에 필요한 phase와 전문 담당자를
   컴파일한다. Node planner는 호환 입력일 뿐 네이티브 경로의 권위가 아니다.
5. `WebTemplateCatalog`가 템플릿을 선택한다. 현재 검증된 내장 템플릿은
   `todo_app`, `meal_planner`, `generic_web`이다.
6. 로컬 scaffold를 만들고 실행 계획, 프로젝트 로그, 디자인 결정, 배포/복구
   문서를 남긴다.
7. 템플릿 runner가 UTF-8, syntax, API health, CRUD, 반응형 기본 조건을
   검사한다. 브라우저 엔진이 없으면 브라우저 검사를 `NOT_RUN`으로 기록한다.
8. ClaimLatch가 프로젝트 ID, revision, QA evidence를 확인한다.
9. `ProjectQualityEvaluator`가 7개 카테고리 100점으로 최종 평가하고
   `FINAL-QUALITY-REPORT.json`을 기록한다.

## 사용자가 보는 API

- `POST /api/assistant/route`: 실행을 시작한다. 백그라운드 작업은 즉시
  `accepted`이며 완료 전에는 `completed`로 표시하지 않는다.
- `GET /api/assistant/jobs/{job_id}`: 작업 상태와 안전한 최종 응답을 본다.
- `GET /api/projects/{project_id}/execution-plan`: phase, task 상태,
  템플릿, 선택/누락 extension을 본다. `rawText`, `systemPrompt`, credential은
  반환하지 않는다.
- `GET /api/projects/{project_id}/quality`: 최종 리포트가 없으면
  `status=awaiting`, identity가 어긋나면 `status=blocked`, 유효한 리포트가
  있으면 `FinalProjectReport`를 반환한다.
- `GET /api/projects/{project_id}/map`: 기존 조직도/작업 그래프를 본다.

## 최종 등급과 차단 조건

- `portfolio_ready`: 필수 증거와 검증이 모두 통과한 상태
- `client_ready_with_notes`: 로컬 검증은 통과했지만 브라우저 E2E나 선택적
  외부 연결 같은 제한이 명시된 상태
- `revision_required`: 결과물 보강이 필요한 상태
- `replan_required`: QA, ClaimLatch, rollback, identity 같은 핵심 게이트가
  통과하지 못해 계획부터 다시 검토해야 하는 상태

다음은 성공으로 처리하지 않는다.

- QA report가 없거나 다른 project/revision을 가리키는 경우
- ClaimLatch가 PASS가 아닌 경우
- 인코딩 오류, BOM, replacement character, diff whitespace가 있는 경우
- rollback 근거가 없는 경우
- 브라우저 검사를 하지 않았는데 실행했다고 기록하는 경우
- 외부 connector가 없는데 Gmail/GitHub/Notion/Figma 작업이 끝났다고 기록하는 경우

## 플러그인 경계

현재는 extension manifest를 선택하거나 누락 상태로 기록할 수만 있다. 실제
플러그인 connector는 이후 단계에서 별도 패키지로 추가한다. connector가
설치되고 OAuth/권한 승인을 거쳐야만 외부 action을 실행할 수 있으며, 실행
결과는 별도의 evidence와 ClaimLatch 검증을 받아야 한다. 따라서 내장 native
프로젝트 실행과 플러그인 설치/연결은 같은 프로세스 안에서 섞이지 않는다.

## 로컬 검증

```powershell
Set-Location apps\eeee
$env:PYTHONPATH = "."
python -m pytest tests/e2e/test_natural_language_project_execution.py -q
python -m pytest -q
```

저장소 수준 검증은 `scripts/verify-core-product.ps1`가 실행한다. 자동
commit, push, PR, 외부 배포는 이 계약에 포함되지 않는다.
