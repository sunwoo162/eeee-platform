# EEEE Platform Architecture Index

The canonical architecture is [`docs/architecture/eeee-platform.md`](architecture/eeee-platform.md).

`Gleave` is the one local-first project. EEEE is the top-level personal assistant, ISEOL is the project-execution capability selected by EEEE, and ClaimLatch plus deterministic QA form the global trust boundary. The user operates one local Gleave application; Notion, Calendar, GitHub, Desktop, and Mobile are connector surfaces around the same Project Runtime. Discord is not part of the core workflow.

ISEOL is the internal project-execution Harness Coordinator. The core runtime provisions Notion documentation and GitHub CI/code-review state; it does not create Discord project spaces. QA and ClaimLatch remain independent release gates.

The detailed design and implementation plan are:

- [`docs/architecture/eeee-platform.md`](architecture/eeee-platform.md)
- [`docs/superpowers/specs/2026-10-06-eeee-personal-assistant-platform-design.md`](superpowers/specs/2026-10-06-eeee-personal-assistant-platform-design.md)
- [`docs/superpowers/plans/2026-10-06-eeee-personal-assistant-platform-plan.md`](superpowers/plans/2026-10-06-eeee-personal-assistant-platform-plan.md)

The sections below are retained as the existing EEEE/ISEOL/ClaimLatch execution and memory reference. New code must follow the canonical single-project boundary above.

## 0. 문서 목적

이 문서는 세 프로젝트를 하나의 로컬 오픈소스 시스템으로 통합할 때의 기준 아키텍처다.

- `EEEE`: 사용자의 개인 비서이자 전체 개인 운영체제
- `ISEOL`: 모든 Agent 조직을 관리하는 Harness Coordinator
- `ClaimLatch`: AI가 만든 주장과 보고서를 외부 근거 및 정책으로 검증하는 신뢰성 Gate
- `Deterministic Verification`: 코드, 파일, 테스트, 보안, 실행 결과를 기계적으로 검증하는 품질 계층

핵심 원칙은 다음과 같다.

> EEEE는 사용자의 삶과 프로젝트의 장기 기억을 관리한다. ISEOL은 프로젝트 안의 모든 Agent를 조직하고 실행한다. ClaimLatch와 결정론적 QA는 결과가 신뢰 가능한지 확인한다. 프로젝트에서 얻은 검증된 경험은 다시 EEEE의 프로젝트 기억으로 저장되어 다음 프로젝트의 계획과 QA에 사용된다.

이 문서는 조직도뿐 아니라 Agent 분해 방식, 독립 QA, ClaimLatch 사용 위치, 영속 기억의 저장·검색·재사용 흐름까지 정의한다.

---

## 1. 최상위 조직도

```text
사용자
  │
  │ 아이디어 · 요구사항 · 질문 · 일정 · 지시
  ▼
┌────────────────────────────────────────────────────────┐
│                         EEEE                           │
│           Personal Executive Assistant / Personal OS   │
│                                                        │
│  사용자의 기억 · 시간 · 약속 · 프로젝트 · 의사결정 관리 │
│  요청 해석 · 우선순위 판단 · 준비 · 추적 · 보고         │
│  비휘발성 메모리와 프로젝트 경험의 장기 보존            │
└──────────────────────────┬─────────────────────────────┘
                           │
                           │ 프로젝트 실행 위임
                           ▼
┌────────────────────────────────────────────────────────┐
│                         ISEOL                          │
│            Harness Coordinator / Agent Organization OS │
│                                                        │
│  모든 Agent의 생성 · 분해 · 배정 · 실행 · 감독 · 통합    │
│  작업 DAG · 병렬 실행 · Context Handoff · 실패 복구     │
│  독립 QA · 검증 · 리뷰 · 릴리스 판단 · 결과 보고         │
└──────────────┬───────────────────────────┬─────────────┘
               │                           │
               │ 작업 조직                  │ 검증 조직
               ▼                           ▼
     ┌─────────────────────┐       ┌─────────────────────┐
     │ Dynamic Agent Teams │       │ Independent QA       │
     │                     │       │ & Verification      │
     │ Design              │       │                     │
     │ Product / Research  │       │ QA Planning         │
     │ Frontend            │       │ Acceptance Criteria │
     │ Backend             │       │ Unit / Integration  │
     │ Data                │       │ E2E / Regression    │
     │ Infrastructure      │       │ Visual / A11y       │
     │ Security            │       │ Security / Perf     │
     │ Documentation       │       │ Evidence Collection │
     └──────────┬──────────┘       └──────────┬──────────┘
                │                             │
                └──────────────┬──────────────┘
                               ▼
                    ┌─────────────────────────┐
                    │ Integration & Release   │
                    │                         │
                    │ Workspace / Git         │
                    │ Build / Test / Review   │
                    │ ClaimLatch Reliability  │
                    │ Release Readiness       │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │ Project Outcome Report  │
                    │                         │
                    │ 결과 · 증거 · QA · 실패  │
                    │ 성공 패턴 · 개선안       │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │ EEEE Persistent Memory │
                    │                         │
                    │ Project Memory          │
                    │ Quality Memory          │
                    │ Organization Playbook  │
                    │ Agent Performance      │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    다음 프로젝트의 계획·QA에 재사용
```

### 책임 경계

| 구성요소 | 책임 | 하지 않는 일 |
|---|---|---|
| EEEE | 사용자 비서, 장기 기억, 일정, 우선순위, 프로젝트 포트폴리오, ISEOL 위임, 결과 보고 | 개별 Agent를 직접 배정하거나 작업 파일을 직접 조정하지 않음 |
| ISEOL | 모든 Agent 조직과 프로젝트 실행의 총괄 관리 | 사용자의 사적인 장기 기억을 임의로 관리하지 않음 |
| Agent Team | 전문 작업 수행 | 최종 품질 승인이나 자기 결과의 최종 판정 |
| QA Organization | 독립적인 품질·릴리스 검증 | 구현 Agent의 성공 주장만으로 통과시키지 않음 |
| ClaimLatch | 텍스트·사실 주장·보고서의 근거 기반 검증 | 코드가 실제로 동작하는지 단독으로 판정하지 않음 |
| Deterministic Verifier | 빌드·테스트·정적 검사·파일·실행 결과 확인 | 자연어 주장의 사실성을 단독으로 검증하지 않음 |

---

## 2. EEEE: 최상위 개인 비서

EEEE는 개발 도구가 아니라 사용자의 개인 비서이자 개인 운영체제다.

### 2.1 EEEE의 주요 조직

```text
┌──────────────────────────────────────────────┐
│                    EEEE                      │
├──────────────────────────────────────────────┤
│                                              │
│  Personal Assistant Core                     │
│  ├─ 자연어 의도 해석                          │
│  ├─ 사용자의 우선순위·상황 판단                │
│  ├─ 오늘 할 일·다음 행동 제안                  │
│  ├─ 사용자에게 필요한 질문만 요청              │
│  └─ 결과를 사용자가 이해할 수 있게 보고        │
│                                              │
│  Life Operations                             │
│  ├─ 캘린더·일정                               │
│  ├─ 약속·마감·반복 업무                        │
│  ├─ 알림·리마인더                             │
│  ├─ 회의 준비·회의 후속 조치                   │
│  └─ 개인 행정 업무                            │
│                                              │
│  Communication & Documents                   │
│  ├─ 메일·메신저 초안                          │
│  ├─ 문서 정리·요약                            │
│  ├─ 보고서·회의록                             │
│  └─ 외부 전송 전 사용자 승인                   │
│                                              │
│  Project Portfolio                           │
│  ├─ 프로젝트 목록·상태                        │
│  ├─ 프로젝트 간 우선순위                      │
│  ├─ 자원·시간 배분                            │
│  ├─ 프로젝트별 메모리 연결                    │
│  └─ ISEOL 실행 위임                           │
│                                              │
│  Persistent Memory                           │
│  ├─ Personal Memory                           │
│  ├─ Project Memory                            │
│  ├─ Quality Memory                            │
│  ├─ Organization Memory                       │
│  └─ Reusable Playbook                         │
│                                              │
│  Policy, Privacy & Approval                  │
│  ├─ 민감정보 보관 정책                        │
│  ├─ 외부 전송 승인                            │
│  ├─ 삭제·수정·망각 요청                       │
│  └─ 되돌릴 수 없는 작업 승인                  │
│                                              │
└──────────────────────────────────────────────┘
```

EEEE가 프로젝트 요청을 받으면 직접 Agent를 고르지 않는다. 사용자의 목표, 제약, 일정, 선호, 과거 프로젝트 기억을 포함한 `Project Brief`를 만들어 ISEOL에 전달한다.

---

## 3. ISEOL: Agent 총합관리 조직

ISEOL은 단순한 작업 큐나 한 명의 PM Agent가 아니다. 프로젝트 안의 모든 AI Agent를 관리하는 운영체제다.

```text
┌──────────────────────────────────────────────────┐
│                      ISEOL                      │
│         Harness Coordinator / Agent OS          │
├──────────────────────────────────────────────────┤
│                                                  │
│  Project Command                                 │
│  ├─ Project Brief 수신                          │
│  ├─ 요구사항 정리                                │
│  ├─ 범위·리스크·성공 기준 결정                   │
│  └─ 프로젝트 상태 머신 관리                      │
│                                                  │
│  Planning & Decomposition                        │
│  ├─ 목표를 Epic으로 분해                         │
│  ├─ Epic을 Workstream으로 분해                   │
│  ├─ Workstream을 Task로 분해                     │
│  ├─ Task DAG·의존성 생성                         │
│  ├─ 병렬 실행 가능성 판단                        │
│  └─ EEEE의 과거 Playbook과 QA 규칙 반영          │
│                                                  │
│  Agent Organization                              │
│  ├─ Agent Registry                               │
│  ├─ 역할·능력·도구·성과 조회                      │
│  ├─ 동적 팀 구성                                  │
│  ├─ Agent 생성·선택·종료                         │
│  ├─ 작업 배정·우선순위·동시성 제어                │
│  ├─ Lease·Heartbeat·Ownership 관리              │
│  ├─ Context Budget 관리                           │
│  └─ Agent 간 Handoff·인수인계                     │
│                                                  │
│  Execution Control                               │
│  ├─ 로컬 런타임·도구 호출                         │
│  ├─ Workspace·Branch·Worktree 관리              │
│  ├─ 실행 로그·이벤트·증거 수집                    │
│  ├─ 충돌·중복·Stale State 방지                    │
│  └─ 실패 감지·재시도·재계획                      │
│                                                  │
│  Integration & Release                           │
│  ├─ Agent 결과 통합                              │
│  ├─ 최신 Revision 확인                           │
│  ├─ 통합 상태에서 재검증                         │
│  ├─ 릴리스 후보 생성                             │
│  └─ EEEE에 최종 결과 보고                        │
│                                                  │
└──────────────────────────────────────────────────┘
```

### 3.1 Agent의 계층

`Frontend Agent`나 `Backend Agent`는 실제 작업자 한 명이 아니라 Workstream 또는 팀 이름이다.

```text
ISEOL
  │
  ├─ Workstream: Frontend
  │    ├─ Frontend Planner
  │    ├─ UI Architecture Agent
  │    ├─ Component Agent
  │    ├─ State Management Agent
  │    ├─ API Integration Agent
  │    ├─ Responsive Layout Agent
  │    ├─ Accessibility Agent
  │    ├─ Browser Compatibility Agent
  │    ├─ Frontend Test Agent
  │    └─ Frontend Reviewer
  │
  ├─ Workstream: Backend
  │    ├─ API Architecture Agent
  │    ├─ Database Agent
  │    ├─ Authentication Agent
  │    ├─ Business Logic Agent
  │    ├─ Security Agent
  │    ├─ Performance Agent
  │    ├─ Unit Test Agent
  │    └─ Backend Reviewer
  │
  ├─ Workstream: Design
  │    ├─ UX Research Agent
  │    ├─ Information Architecture Agent
  │    ├─ Visual Design Agent
  │    ├─ Design System Agent
  │    └─ Visual Review Agent
  │
  └─ Workstream: Data / Infrastructure / Documentation / 기타
```

ISEOL은 프로젝트 크기와 위험도에 따라 각 Workstream을 더 세분화하거나 합친다. 고정된 Agent 수나 고정된 조직도를 강제하지 않는다.

---

## 4. 독립 QA 및 검증 조직

QA는 프로젝트 마지막에 붙는 검사 단계가 아니다. 요구사항이 만들어지는 순간부터 릴리스 후 회고까지 지속되는 독립 조직이다.

```text
┌──────────────────────────────────────────────────┐
│              INDEPENDENT QA ORGANIZATION         │
│           ISEOL 내부의 독립적인 품질 Gate         │
├──────────────────────────────────────────────────┤
│                                                  │
│  QA Strategy                                     │
│  ├─ 요구사항별 Acceptance Criteria                │
│  ├─ 위험도·영향도 분류                            │
│  ├─ 테스트 범위·우선순위                          │
│  ├─ 이전 프로젝트의 QA 규칙 조회                  │
│  └─ 이번 프로젝트 전용 QA Plan                    │
│                                                  │
│  Requirement QA                                  │
│  ├─ 요구사항 누락 검사                            │
│  ├─ 모호한 조건 식별                              │
│  ├─ 성공 기준 검증 가능성                         │
│  └─ 사용자 목표와 구현 범위 일치 여부             │
│                                                  │
│  Engineering QA                                  │
│  ├─ Type Check                                   │
│  ├─ Lint / Format                                │
│  ├─ Build / Compile                              │
│  ├─ Unit Test                                    │
│  ├─ Integration Test                             │
│  ├─ E2E Test                                     │
│  ├─ Regression Test                              │
│  └─ Dependency·Version 검사                      │
│                                                  │
│  Product QA                                      │
│  ├─ 사용자 시나리오                              │
│  ├─ Acceptance Test                              │
│  ├─ Edge Case                                    │
│  ├─ Error Recovery                               │
│  └─ 실제 사용 흐름                               │
│                                                  │
│  Specialized QA                                  │
│  ├─ Visual Regression                            │
│  ├─ Responsive Layout                             │
│  ├─ Accessibility                                │
│  ├─ Security                                     │
│  ├─ Performance                                  │
│  ├─ Privacy                                      │
│  └─ License·Provenance                           │
│                                                  │
│  Evidence & Release Gate                         │
│  ├─ 테스트 로그·스크린샷·리포트 수집              │
│  ├─ 최신 Revision 기준 검증                       │
│  ├─ 결함 심각도·재현 절차                         │
│  ├─ PASS / WARN / BLOCKED                       │
│  └─ 릴리스 가능 여부 결정                         │
│                                                  │
└──────────────────────────────────────────────────┘
```

### 4.1 QA 단계

```text
요구사항
  │
  ▼
QA-0: Acceptance Criteria 작성
  │
  ▼
설계
  │
  ▼
QA-1: 구조·계약·위험 검토
  │
  ▼
구현
  │
  ▼
QA-2: 단위 테스트·정적 검사·작업 단위 검증
  │
  ▼
통합
  │
  ▼
QA-3: Agent 간 연결·충돌·회귀 검증
  │
  ▼
릴리스 후보
  │
  ▼
QA-4: 전체 시나리오·보안·성능·시각 검증
  │
  ├─ BLOCKED ──▶ Problem Router ──▶ 원인 Workstream 재배정
  │
  └─ PASS/WARN ─▶ ClaimLatch·Release Gate
                         │
                         ▼
                    배포 또는 사용자 승인
                         │
                         ▼
QA-5: 결과·교훈·회귀 규칙을 EEEE에 저장
```

### 4.2 QA의 독립성 규칙

- Agent가 말하는 `완료했습니다`는 증거가 아니다.
- 구현 Agent는 자신의 결과에 대한 최종 릴리스 승인을 하지 않는다.
- QA는 통합된 최신 Revision에서 검사를 다시 실행한다.
- 이전 Revision의 검증 결과로 최신 변경을 통과시키지 않는다.
- 테스트가 없거나 증거를 저장할 수 없으면 `WARN` 또는 `BLOCKED`로 처리한다.
- 치명적 결함, 보안 문제, 검증되지 않은 외부 주장, 근거 없는 성공 보고는 자동으로 차단한다.

---

## 5. ClaimLatch 활용 위치

ClaimLatch 활용은 누락되지 않는다. 다만 ClaimLatch와 코드 QA는 서로 대체하는 관계가 아니므로 역할을 분리한다.

### 5.1 ClaimLatch가 담당하는 것

ClaimLatch는 다음과 같은 자연어 주장과 보고서를 검증한다.

- Agent가 조사한 외부 사실
- 라이브러리·프레임워크·API의 기능 설명
- 버전·날짜·수치·호환성 주장
- 라이선스·저장소·문서에 대한 설명
- QA 결과에 포함된 사실 주장
- 최종 보고서의 “완료”, “지원”, “통과” 같은 주장
- EEEE에 장기 기억으로 저장할 재사용 규칙
- 사용자가 받게 될 모든 신뢰성 있는 자연어 답변

### 5.2 결정론적 검증이 담당하는 것

ClaimLatch만으로는 코드가 실제로 동작하는지 알 수 없으므로 ISEOL의 결정론적 검증과 함께 사용한다.

- `compileall`, `pytest`, `npm test`, `npm run build` 같은 실행 결과
- 타입·린트·포맷 검사
- Git diff와 변경 파일 검사
- 실제 API·브라우저·E2E 시나리오
- 시각 회귀와 접근성 검사
- 보안·비밀정보·위험한 외부 전송 검사
- 생성된 파일의 존재 여부와 해시
- Agent 작업 공간과 최신 Revision 일치 여부

### 5.3 전체 검증 Gate

```text
AI Agent 결과
  │
  ├─ 자연어 주장·조사·설명
  │       │
  │       ▼
  │   ClaimLatch
  │   ├─ Claim 추출
  │   ├─ Evidence 수집
  │   ├─ Claim ↔ Evidence 바인딩
  │   ├─ SUPPORTED / CONTRADICTED /
  │   │  UNSUPPORTED / UNVERIFIABLE 판정
  │   └─ 정책에 따른 PASS / BLOCK
  │
  ├─ 코드·파일·실행 결과
  │       │
  │       ▼
  │   ISEOL Deterministic Verifier
  │   ├─ Build / Compile
  │   ├─ Unit / Integration / E2E Test
  │   ├─ Static / Security / Diff 검사
  │   └─ Evidence Artifact 생성
  │
  └─ 구조화된 도구 호출·행동
          │
          ▼
      Application-owned Structured Output Verifier
      ├─ Schema 검사
      ├─ 허용된 도구·인자 검사
      ├─ 권한·범위 검사
      ├─ 외부 전송·삭제·배포 정책 검사
      └─ 사용자 승인 필요 여부 판단
  │
  ▼
Unified Release Gate
  ├─ 모든 필수 검증 PASS
  ├─ 중요한 Claim은 근거 보유
  ├─ 최신 Revision 기준
  ├─ QA 차단 이슈 없음
  └─ 정책 위반 없음
  │
  ├─ PASS ──▶ 사용자·EEEE·신뢰 저장소로 전달
  └─ BLOCK ─▶ 사용자에게 미완료 상태 보고 + ISEOL 재계획
```

### 5.4 ClaimLatch의 구체적 사용 지점

#### A. 계획 단계

요구사항을 분석하면서 외부 사실을 사용하면 ClaimLatch로 검증한다.

```text
“이 라이브러리는 해당 기능을 지원한다”
“이 패키지는 MIT 라이선스다”
“이 API는 특정 버전을 요구한다”
“이 기술 조합이 호환된다”
```

이런 주장은 공식 문서, 저장소, 패키지 메타데이터 등의 근거와 함께 계획에 포함한다.

#### B. Agent Handoff 단계

Agent가 다음 Agent에게 전달하는 요약도 신뢰된 인수인계 데이터로 사용되기 전에 검증한다.

```text
Agent A 결과
  ├─ 변경 파일
  ├─ 실행한 명령
  ├─ 테스트 결과
  ├─ 남은 문제
  └─ 자연어 설명
          │
          ├─ 파일·명령·테스트 → 결정론적 검증
          └─ 자연어 사실 주장 → ClaimLatch
```

#### C. QA 보고 단계

QA가 “전체 테스트 통과”, “보안 문제 없음”, “요구사항 충족”이라고 보고하면 해당 주장을 실제 검사 증거와 연결한다. 근거가 없거나 검사 범위를 넘는 주장은 통과시키지 않는다.

#### D. 최종 사용자 보고 단계

EEEE가 사용자에게 전달하는 최종 보고는 ClaimLatch를 통과한 보고서만 신뢰된 결과로 표시한다. 차단된 결과는 완료처럼 표현하지 않고, 차단 이유와 다음 조치를 함께 보여준다.

#### E. EEEE 영속 기억 저장 단계

프로젝트에서 얻은 “재사용 가능한 규칙”은 바로 기억에 넣지 않는다.

```text
프로젝트 결과
  ▼
기억 후보 추출
  ▼
실제 증거·QA 결과·출처 연결
  ▼
ClaimLatch 검증
  ▼
기존 기억과 모순 검사
  ▼
적용 범위·신뢰도·만료 조건 설정
  ▼
EEEE 영속 기억 저장
```

### 5.5 ClaimLatch 적용 시 주의사항

- ClaimLatch는 LLM의 자기보고 신뢰도를 그대로 믿는 도구가 아니다.
- ClaimLatch의 `coverage`는 정확도 백분율이 아니라 증거로 판정 가능한 주장 비율이다.
- 코드의 정상 실행 여부는 테스트·빌드·실행 증거로 검증해야 한다.
- 구조화된 도구 호출은 애플리케이션이 허용 목록과 권한 정책을 별도로 정의해야 한다.
- 검증되지 않은 답변은 사용자에게 릴리스하거나 신뢰 기억에 저장하지 않는다.
- ClaimLatch 검증 자체가 실패해도 fail-open하지 않고 결과를 차단하거나 `WARN/BLOCKED`로 남긴다.
- ClaimLatch의 검증 보고서와 가능하면 서명된 receipt를 프로젝트 증거와 함께 보존한다.

---

## 6. EEEE 비휘발성 프로젝트 기억

EEEE의 가장 중요한 기능은 대화 내용을 저장하는 것이 아니라, 프로젝트 경험을 다음 프로젝트에서 다시 사용할 수 있는 구조화된 지식으로 보존하는 것이다.

```text
┌──────────────────────────────────────────────┐
│          EEEE Persistent Memory              │
├──────────────────────────────────────────────┤
│                                              │
│  Personal Memory                             │
│  ├─ 사용자 선호                               │
│  ├─ 일정·약속·반복 업무                        │
│  ├─ 장기 목표                                 │
│  └─ 연락·문서·개인 운영 방식                   │
│                                              │
│  Project Memory                              │
│  ├─ 프로젝트 목적·범위                         │
│  ├─ 기술 스택·아키텍처                         │
│  ├─ 요구사항·결정사항                          │
│  ├─ 파일·문서·환경                             │
│  └─ 릴리스·변경 이력                           │
│                                              │
│  Quality Memory                              │
│  ├─ 발견된 버그                                │
│  ├─ QA 실패 원인                               │
│  ├─ 회귀 방지 규칙                             │
│  ├─ 테스트 체크리스트                          │
│  ├─ 릴리스 차단 조건                            │
│  └─ 성공한 검증 방식                            │
│                                              │
│  Organization Memory                         │
│  ├─ 잘 작동한 Agent 구성                       │
│  ├─ 좋은 Task 분해 방식                        │
│  ├─ 효과적인 병렬 실행 방식                    │
│  ├─ 효율적인 Handoff 방식                      │
│  ├─ Agent별 강점·실패 패턴                     │
│  └─ ISEOL 운영 방식                            │
│                                              │
│  Playbook Memory                              │
│  ├─ 웹 프로젝트 개발 절차                      │
│  ├─ API 프로젝트 보안 QA                       │
│  ├─ 모바일·반응형 QA                            │
│  ├─ 디자인·시각 검증 절차                      │
│  ├─ 배포 전 체크리스트                          │
│  └─ 프로젝트 유형별 기본 조직 템플릿            │
│                                              │
└──────────────────────────────────────────────┘
```

### 6.1 기억의 종류

| 기억 유형 | 예시 | 다음 프로젝트에서의 사용 |
|---|---|---|
| 프로젝트 사실 | “이 프로젝트는 Python 3.12와 SQLite를 사용한다” | 작업 환경·Agent 컨텍스트 구성 |
| 사용자 선호 | “사용자는 로컬 우선과 명시적 승인을 선호한다” | 기본 실행·승인 정책 |
| 성공 패턴 | “작은 UI 작업은 병렬 실행보다 한 Agent의 순차 작업이 안정적이었다” | ISEOL 팀 구성 |
| 실패 패턴 | “API와 DB를 동시에 수정하면 계약 불일치가 자주 발생했다” | 작업 의존성 강화 |
| QA 규칙 | “웹 프로젝트는 320/375/768px에서 시각 검사를 수행한다” | 자동 QA 계획 생성 |
| 회귀 규칙 | “이전 프로젝트에서 인증 만료 처리 누락” | 다음 프로젝트 필수 테스트 |
| Agent 성과 | “특정 작업 유형에서 특정 Agent의 재작업률이 낮았다” | Agent 라우팅 |
| 운영 Playbook | “기획→계약→구현→통합→독립 QA 순서가 안정적이었다” | 초기 Task DAG 생성 |

### 6.2 기억 저장 포맷의 최소 조건

모든 기억은 단순한 문자열이 아니라 다음 메타데이터를 가져야 한다.

```text
MemoryRecord
├─ id
├─ type
├─ title
├─ content
├─ scope
│  ├─ personal
│  ├─ project
│  ├─ technology
│  └─ organization
├─ source_project_id
├─ source_artifact_ids
├─ evidence_ids
├─ claimlatch_report_id
├─ deterministic_check_ids
├─ confidence
├─ status: candidate / active / superseded / revoked
├─ created_at
├─ last_verified_at
├─ expires_at
├─ supersedes_memory_id
└─ user_editable
```

### 6.3 기억 저장 정책

- 원본 로그와 재사용 규칙을 분리한다.
- 모든 규칙은 출처 프로젝트와 증거를 가져야 한다.
- 외부 사실이 포함된 기억은 ClaimLatch 검증 없이는 `active`가 될 수 없다.
- 코드·테스트·파일에 관한 기억은 결정론적 증거가 있어야 한다.
- 사용자 선호는 사용자가 직접 수정·삭제할 수 있어야 한다.
- 오래된 기술 정보는 만료·재검증 대상으로 표시한다.
- 새 프로젝트 결과가 이전 기억과 충돌하면 자동 덮어쓰지 않고 버전으로 보존한다.
- 민감정보는 별도의 접근·암호화·보존 정책을 적용한다.

---

## 7. 프로젝트 경험이 다음 QA로 연결되는 흐름

```text
프로젝트 A 실행
  │
  ▼
ISEOL이 Agent 조직 구성·작업 분해·실행
  │
  ▼
독립 QA가 결함·누락·성공 패턴 발견
  │
  ▼
결정론적 증거와 ClaimLatch 보고서 결합
  │
  ▼
Project Outcome Report 생성
  │
  ▼
EEEE Memory Compiler
  ├─ 성공 패턴 추출
  ├─ 실패 패턴 추출
  ├─ 새 QA 규칙 추출
  ├─ 회귀 테스트 후보 추출
  ├─ Agent 라우팅 성과 추출
  └─ 운영 Playbook 갱신
  │
  ▼
EEEE Project Memory에 영속 저장
  │
  ▼
프로젝트 B 생성
  │
  ▼
EEEE가 관련 프로젝트 기억 검색
  │
  ▼
ISEOL에 Project Brief + QA Baseline 전달
  │
  ▼
ISEOL이 과거 실패를 선제적으로 검사하는 QA Plan 생성
  │
  ▼
프로젝트 B 실행
```

### 예시: 모바일 UI 결함의 재사용

프로젝트 A에서 375px 화면의 레이아웃이 깨졌다면 EEEE는 다음과 같은 규칙을 저장할 수 있다.

```text
QA Rule: Web Responsive Baseline
Scope: React 또는 유사 웹 프론트엔드
Required Viewports: 320px, 375px, 768px
Required Evidence: 화면 캡처 또는 자동 시각 회귀 결과
Source: Project A QA report
Status: active
```

프로젝트 B가 시작되면 이 규칙이 자동으로 QA 기준에 들어간다. 이렇게 EEEE는 프로젝트마다 반복되는 실수를 조직의 장기 지식으로 바꾼다.

---

## 8. 전체 프로젝트 실행 흐름

사용자가 EEEE에게 다음과 같이 말한다고 가정한다.

> “이전 프로젝트에서 잘했던 방식과 QA 기준을 반영해서 쇼핑몰 MVP를 만들어줘.”

```text
사용자 요청
  │
  ▼
EEEE
  ├─ 의도·목표 해석
  ├─ 사용자 선호·일정 확인
  ├─ 관련 Project Memory 검색
  ├─ 이전 QA 규칙·실패 패턴 검색
  ├─ Project Brief 생성
  └─ ISEOL에 실행 위임
  │
  ▼
ISEOL
  ├─ 요구사항·범위·성공 기준 정리
  ├─ 계획에 포함된 외부 사실을 ClaimLatch 검증
  ├─ Epic·Workstream·Task DAG 생성
  ├─ Dynamic Agent Team 구성
  ├─ QA Plan과 과거 회귀 규칙 포함
  └─ 병렬·순차 실행 결정
  │
  ▼
각 Agent Team
  ├─ 작업 수행
  ├─ 결과·변경 파일·명령·증거 제출
  ├─ 자연어 주장과 사실을 ClaimLatch에 전달
  └─ 다음 Agent를 위한 Handoff 작성
  │
  ▼
ISEOL 통합
  ├─ 최신 Revision 확인
  ├─ Ownership·충돌·Stale State 검사
  ├─ 결과 통합
  └─ 결정론적 검증 재실행
  │
  ▼
독립 QA
  ├─ 요구사항 검증
  ├─ 전체 테스트
  ├─ 과거 회귀 규칙
  ├─ 보안·성능·시각·접근성
  └─ Evidence 수집
  │
  ├─ 실패 ──▶ Problem Router ──▶ 원인 Agent/Workstream 재배정
  │                                │
  │                                └─ 재실행 후 QA 복귀
  │
  └─ 통과
       │
       ▼
ClaimLatch Final Report Gate
  ├─ 최종 자연어 보고서의 주장 검증
  ├─ 근거·증거·검사 결과 바인딩
  └─ PASS / BLOCK
       │
       ▼
EEEE
  ├─ 사용자에게 결과·위험·남은 일 보고
  ├─ 외부 전송·배포는 정책과 승인 확인
  ├─ Project Outcome Report 저장
  ├─ 검증된 경험을 Project Memory로 승격
  └─ 다음 프로젝트의 QA Baseline 갱신
```

---

## 9. 로컬 오픈소스 실행 구조

핵심 기능은 중앙 로그인이나 원격 서버 없이 사용자의 로컬 PC에서 동작한다.

```text
사용자 PC
├─ EEEE Local Service
│  ├─ Personal Assistant API
│  ├─ SQLite 영속 저장소
│  ├─ Memory Compiler / Retriever
│  ├─ Calendar·Scheduler
│  └─ Local UI / Desktop UI
│
├─ ISEOL Runtime
│  ├─ Agent Coordinator
│  ├─ Workspace·Git Manager
│  ├─ Task Runner
│  ├─ QA Orchestrator
│  └─ Evidence Store
│
├─ ClaimLatch Runtime
│  ├─ Node SDK 또는 로컬 프로세스
│  ├─ Guarded Answer Handler
│  ├─ Structured Output Verifier Adapter
│  └─ Verification Receipt Store
│
├─ Local AI Runtime
│  ├─ Ollama 등
│  └─ 필요 시 OpenAI-compatible Adapter
│
└─ Optional Adapters
   ├─ Notion
   ├─ GitHub CI / Code Review
   ├─ Calendar
   ├─ Email
   └─ Browser
```

외부 서비스 연결은 선택 기능이다. 핵심 기억, 프로젝트 상태, QA 증거, ClaimLatch 보고서는 로컬에 보관한다. 외부로 메시지를 보내거나 배포하는 작업은 EEEE의 승인 정책을 통과해야 한다.

---

## 10. 현재 저장소 기준 상태와 통합 누락 사항

### 10.1 EEEE에 현재 있는 기반

- SQLite 기반 프로젝트·작업·승인·실행·이벤트·보고서 영속 저장
- 프로젝트 상태와 Revision 관리
- Harness Coordinator의 Agent Task Lease와 Ownership 관리
- Stale State 방지와 Handoff 계약
- 최신 통합 상태에 대한 결정론적 검증
- `compileall`, `pytest`, `git diff --check` 계열의 허용된 검사
- 변경 파일과 검증 결과 Evidence 저장
- 정적 Reviewer의 외부 전송·삭제·비밀정보 탐지
- 로컬 FastAPI·브라우저 UI·선택적 데스크톱 UI

### 10.2 ISEOL 저장소에 있는 기반

- 프로젝트 모델과 Work Request
- 실행·재시도·복구·Reconciliation 흐름
- 로컬 AI Chat·AI Team 런타임
- Desktop Agent와 ChatGPT Web Adapter
- Workspace·Evidence·Portfolio 개념
- Notion·GitHub·웹 Control Plane 어댑터

최종 통합에서는 원격 협업 채널을 핵심으로 두지 않고, ISEOL의 Agent 조직·실행·증거 기능을 EEEE 아래의 로컬 Harness 계층으로 사용한다.

### 10.3 ClaimLatch 현재 상태

ClaimLatch 저장소에는 다음 기능이 있다.

- Claim 추출
- Evidence 수집 및 Provenance 연결
- `SUPPORTED`, `CONTRADICTED`, `UNSUPPORTED`, `UNVERIFIABLE` 판정
- 정책 기반 `PASS` / `BLOCK`
- `verifyBeforeRelease`
- HTTP/Fetch Guarded Answer Handler
- OpenAI-compatible Proxy
- 구조화된 출력에 대한 애플리케이션 소유 Verifier Hook
- Signed Verification Receipt와 Receipt Store
- 독립 벤치마크 및 정책 검증

### 10.4 현재 직접 통합 상태

현재 `EEEE`에는 로컬 ClaimLatch 통합 계층이 구현되어 있다. 핵심 경계는
`apps/eeee/app/integrations/claimlatch_client.py`의 버전 고정 클라이언트,
`apps/eeee/app/integrations/claimlatch_process.py`의 loopback 프로세스 어댑터,
`apps/eeee/app/integrations/claimlatch_audit.py`의 SQLite 감사 기록이다.
`apps/eeee/app/trust/pipeline.py`와 `apps/eeee/app/trust/gate.py`는 자연어 주장·구조화된
행동·릴리스 보고서를 결정론적 증거와 함께 fail-closed로 판정한다. 따라서 현재 상태는:

```text
현재 EEEE
  ├─ 자체 결정론적 Harness 검증: 있음
  ├─ 자체 QA·Evidence 구조: 있음
  ├─ SQLite 영속 상태: 있음
  ├─ ClaimLatch 로컬 Adapter·프로세스 경계: 있음
  ├─ ClaimLatch 감사 Receipt·revision 연결: 있음
  └─ 릴리스·메모리 승격 fail-closed Gate: 있음
```

현재 구현의 범위와 한계도 분리해 기록한다. 기본 검증은 외부 로그인이나 hosted 서버 없이
로컬 결정론적 verifier로 수행한다. 외부 LLM 기반 ClaimLatch provider를 사용하는 경우에는
별도 환경 설정이 필요하며, provider 오류·증거 누락·revision 불일치는 모두 PASS가 아니라
WARN/BLOCK으로 남는다. ISEOL의 전체 Agent 조직 런타임과 선택적 외부 플러그인은 이 저장소의
core release gate 범위를 넘어선다.

```text
apps/eeee/app/integrations/
├─ claimlatch_client.py       # 버전·payload·revision 계약
├─ claimlatch_process.py      # 제한된 loopback/process 경계
└─ claimlatch_audit.py        # report/receipt/payload hash 감사
apps/eeee/app/trust/
├─ pipeline.py                # 주장·행동·릴리스 검증 흐름
└─ gate.py                    # PASS/WARN/BLOCK 정책
apps/eeee/app/release/manifest.py  # artifact·UTF-8·evidence 검증
```

Python 기반 EEEE와 TypeScript 기반 ClaimLatch 사이의 외부 호출은 버전 고정 JSON 계약과
제한된 loopback/process 경계로만 확장한다. EEEE는 ClaimLatch 내부 구현을 복제하지 않고,
결과와 Receipt를 프로젝트 Evidence 및 revision에 연결한다.

### 10.5 통합 후 필수 Gate

```text
Agent 결과를 trusted 상태로 저장하기 전
  ├─ 구조·스키마 검사
  ├─ 변경 파일·실행 증거 확인
  ├─ 결정론적 QA 실행
  ├─ 자연어 주장 ClaimLatch 검증
  ├─ 구조화된 행동 정책 검증
  └─ 실패 시 trusted 저장·릴리스 금지
```

---

## 11. 권장 통합 데이터 계약

ISEOL은 작업 완료 시 EEEE에 단순 문자열이 아니라 다음 형태의 결과를 전달한다.

```text
ProjectOutcomeReport
├─ project_id
├─ project_revision
├─ status: completed / blocked / failed
├─ user_goal
├─ scope
├─ changed_artifacts
├─ agent_teams
├─ task_graph_summary
├─ handoffs
├─ deterministic_verification_report
├─ qa_report
├─ claimlatch_reports
├─ verification_receipts
├─ passed_checks
├─ failed_checks
├─ unresolved_risks
├─ successful_patterns
├─ failed_patterns
├─ reusable_qa_rules
├─ regression_candidates
├─ agent_performance
├─ recommended_next_actions
└─ memory_candidates
```

EEEE는 이 결과를 받아 다음 순서로 처리한다.

```text
Outcome Report
  ▼
Evidence와 Receipt 확인
  ▼
Memory Candidate 분류
  ▼
중복·모순·범위 검사
  ▼
ClaimLatch 및 정책 검증
  ▼
사용자 승인 필요 여부 판단
  ▼
Project Memory / Quality Memory / Playbook 저장
```

---

## 12. 설계 완료 기준

이 통합 아키텍처는 다음 조건을 만족해야 한다.

### 조직

- [ ] EEEE가 최상위 개인 비서로 동작한다.
- [ ] ISEOL이 모든 Agent 관련 관리를 담당한다.
- [ ] Frontend·Backend 같은 분야가 단일 Agent가 아니라 동적 Workstream으로 동작한다.
- [ ] ISEOL이 Task 분해·팀 구성·병렬 실행·Handoff·실패 복구를 담당한다.

### QA

- [ ] QA가 구현 Agent와 독립되어 있다.
- [ ] 요구사항 단계부터 QA 기준을 만든다.
- [ ] 최신 통합 Revision에서 검증한다.
- [ ] Unit·Integration·E2E·Regression·Visual·Accessibility·Security 검사를 지원한다.
- [ ] 증거 없는 Agent 완료 주장을 통과시키지 않는다.
- [ ] 실패 시 원인 Workstream으로 되돌아가는 Problem Router가 있다.

### ClaimLatch

- [ ] Agent의 자연어 보고서와 사실 주장을 ClaimLatch로 검증한다.
- [ ] 최종 EEEE 보고서를 ClaimLatch Gate 뒤에서 릴리스한다.
- [ ] EEEE 장기기억에 들어가는 외부 사실과 재사용 규칙을 검증한다.
- [ ] ClaimLatch와 결정론적 코드 QA를 함께 사용한다.
- [ ] 구조화된 도구 호출은 별도의 정책 기반 Verifier를 사용한다.
- [ ] 검증 실패 시 fail-open하지 않는다.
- [ ] Verification Report와 Receipt를 Evidence에 연결한다.

### 영속 기억

- [ ] 프로젝트별 기억과 전체 조직 Playbook을 분리한다.
- [ ] 성공·실패·QA 규칙·Agent 성과를 다음 프로젝트에서 검색할 수 있다.
- [ ] 각 기억에 출처·증거·범위·신뢰도·생성일·검증일이 있다.
- [ ] 오래된 기억을 갱신·폐기·철회할 수 있다.
- [ ] 사용자가 기억을 확인·수정·삭제할 수 있다.
- [ ] 다음 프로젝트의 Task DAG와 QA Plan에 관련 기억이 자동 반영된다.

---

## 최종 정의

> **EEEE는 사용자의 개인 비서이자 프로젝트 경험을 축적하는 비휘발성 조직 기억이다.**
>
> **ISEOL은 EEEE의 명령을 받아 모든 AI Agent를 조직하고, 작업을 분해하고, 병렬 실행하고, 통합하고, 독립 QA와 검증을 통과시키는 Harness Coordinator다.**
>
> **ClaimLatch는 Agent와 EEEE가 내놓는 자연어 주장·조사·보고서·기억 후보를 근거 기반으로 검증하는 신뢰성 계층이며, 코드의 실제 동작은 ISEOL의 결정론적 QA가 검증한다.**
>
> **한 프로젝트의 검증된 성공과 실패는 EEEE의 Project Memory와 Quality Memory에 저장되고, 다음 프로젝트의 Agent 구성·작업 분해·QA 계획·회귀 테스트로 다시 사용된다.**

