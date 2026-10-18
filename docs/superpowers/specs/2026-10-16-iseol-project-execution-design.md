# 이설 프로젝트 실행 조직 설계 명세

작성일: 2026-10-16
상태: 설계 초안

## 1. 목적

이설은 사용자가 주제나 목표만 입력해도 웹 프로젝트의 기획, 조사, 콘텐츠,
정보구조, UX, UI, 기술설계, 개발, 테스트, 배포, 운영, 개선까지 이어지는
전체 작업을 하나의 전문 조직처럼 구성하고 실행한다.

이설은 모든 일을 하나의 거대한 에이전트에게 맡기지 않는다. 요청마다 필요한
조직, 플러그인, 봇, 검증기를 실행 그래프로 조립하고 각 작업의 산출물과
검증 증거를 다음 작업에 전달한다.

## 2. 핵심 원칙

1. 주제는 프로젝트 미션으로 변환한다.
2. 모든 작업은 원자 작업 단위로 추적한다.
3. 역할 봇과 외부 플러그인은 서로 다른 책임을 가진다.
4. 플러그인은 외부 시스템을 연결하거나 전문 작업 공간을 제공한다.
5. 봇은 판단·작성·분석을 담당하고 커넥터는 실제 외부 액션을 수행한다.
6. 검증기는 완료 주장을 독립적으로 확인한다.
7. 외부 상태 변경은 실행 전에 계획·권한·승인을 확인한다.
8. 필요한 파트와 플러그인만 지연 로딩한다.
9. 모든 작업은 재시작·재시도·복구가 가능해야 한다.
10. 완료는 생성물이 존재하는 것이 아니라 조건과 증거가 충족된 상태다.

## 3. 실행 계층

```text
Mission
└─ Project
   └─ Phase
      └─ Work Package
         └─ Atomic Task
            ├─ Worker Bot
            ├─ Action Plugin
            └─ Validator Bot
```

### 3.1 Mission

사용자가 입력한 목표다. 예: “카페 홈페이지를 만들어줘”.

### 3.2 Project

미션을 수행하기 위한 독립 작업 공간이다. 프로젝트에는 브리프, 조직도,
작업 그래프, 산출물, 외부 리소스 연결, 이벤트, 검증 증거가 포함된다.

### 3.3 Phase

프로젝트 생명주기의 큰 단계다.

```text
intake → definition → research → requirements → content
→ information-architecture → ux → ui → technical-design
→ environment → implementation → testing → release
→ operations → improvement
```

### 3.4 Work Package

한 가지 결과를 만들기 위한 작업 묶음이다. 예: “PR 품질 확인”,
“디자인 시스템 구축”, “Discord 프로젝트 공간 생성”.

### 3.5 Atomic Task

한 번의 실행과 검증으로 완료 여부를 판단할 수 있는 최소 작업이다.
예: “변경 파일을 UTF-8 strict 방식으로 읽고 깨진 문자가 없는지 확인한다”.

## 4. 이설 내부 조직

```text
ISEOL Executive Office
├─ Mission Control
├─ Project Management Office
├─ Planning & Research Office
├─ Content & Information Office
├─ Design Organization
├─ Engineering Organization
├─ Infrastructure & Release Organization
├─ Collaboration & Documentation Organization
├─ Quality & Security Organization
├─ Operations Organization
└─ Evidence & Memory Office
```

각 조직은 별도의 무거운 AI 프로세스가 아니다. 역할 매니페스트를 가진
실행 노드이며, 같은 런타임·모델·Core API를 필요할 때 공유한다.

## 5. 파트별 책임과 봇·플러그인 분배

### 5.1 Mission Control

책임:

- 자연어 목표 해석
- 프로젝트 유형 분류
- 필요한 단계와 조건부 단계 선택
- 필요한 봇과 플러그인 조합
- 실행 순서와 병렬 실행 결정
- 승인·권한·비용·시간 예산 확인
- 진행률과 차단 원인 보고
- 최종 완료 판정 요청

봇:

```text
iseol.intent-parser
iseol.project-type-classifier
iseol.scope-estimator
iseol.ambiguity-detector
iseol.question-selector
iseol.risk-classifier
iseol.org-composer
iseol.graph-compiler
iseol.progress-reporter
iseol.final-coordinator
```

검증기:

```text
iseol.plan-consistency-checker
iseol.dependency-cycle-checker
iseol.permission-preflight
iseol.completion-gate
```

### 5.2 Project Management Office

책임:

- 프로젝트 브리프·목표·범위·MVP 작성
- 성공 지표·완료 기준 정의
- 일정·우선순위·의존성 관리
- 리스크·변경 요청 관리
- 요구사항 추적성 유지

봇:

```text
planning.brief-writer
planning.goal-definition
planning.mvp-scope
planning.success-metrics
planning.user-story-writer
planning.acceptance-criteria
planning.dependency-mapper
planning.risk-register
planning.change-impact-analyzer
planning.backlog-prioritizer
```

플러그인:

```text
project-workspace
notion
notion-project-provisioner
github-projects
```

### 5.3 Planning & Research Office

책임:

- 시장·경쟁·사용자 조사
- 레퍼런스 수집
- 출처·라이선스 기록
- 조사 결과를 요구사항·디자인 방향에 반영

봇:

```text
research.web-researcher
research.competitor-analyzer
research.user-scenario-analyzer
research.reference-collector
research.source-verifier
research.license-checker
research.trend-analyzer
research.research-synthesizer
```

플러그인:

```text
web-research
browser
notion-research
asset-license
```

### 5.4 Content & Information Office

책임:

- 페이지 문구·콘텐츠 구조·콘텐츠 모델 작성
- SEO·다국어·법적 문구 처리
- 오류·빈 상태·성공 상태 문구 작성

봇:

```text
content.copywriter
content.page-content-planner
content.cta-writer
content.error-state-writer
content.empty-state-writer
content.seo-writer
content.localization-planner
content.legal-copy-checker
content.tone-consistency-checker
content.content-completeness-checker
```

플러그인:

```text
notion-documentation
cms-connector
translation
seo-checker
```

### 5.5 Design Organization

웹 디자인 플러그인은 하나의 전문 작업 공간이며, 내부에 다음 모듈을 가진다.

```text
web-design
├─ design-conference
├─ design-project-store
├─ design-research
├─ design-direction
├─ design-ia
├─ design-ux
├─ design-ui
├─ design-system
├─ design-assets
├─ design-prototype
├─ design-code-handoff
└─ design-review
```

봇:

```text
design.conference-facilitator
design.direction-generator
design.reference-board-builder
design.sitemap-builder
design.user-flow-builder
design.wireframe-builder
design.responsive-layout-designer
design.visual-direction-designer
design.component-spec-writer
design.design-token-builder
design.asset-selector
design.asset-generator
design.prototype-builder
design.figma-operator
design.canva-operator
design.design-critic
design.text-overflow-checker
design.layout-consistency-checker
design.accessibility-design-checker
```

커넥터:

```text
figma
canva
image-generation
asset-storage
browser-preview
```

웹 디자인 플러그인 저장소에는 디자인 회의, 결정사항, 시안, 에셋, 버전,
컴포넌트 규칙, 프로토타입 상태를 저장한다. Core에는 프로젝트 ID,
산출물 참조, 실행 이벤트, 권한·감사 기록만 저장한다.

### 5.6 Engineering Organization

책임:

- 기술 스택·아키텍처·데이터 모델·API 설계
- 저장소·브랜치·이슈·PR 관리
- 프론트엔드·백엔드·데이터·통합 구현
- 코드 리뷰·리팩터링·CI 관리

플러그인:

```text
github
github-project-provisioner
github-bot
repository-files
ci-cd
local-development
dependency-manager
```

봇:

```text
engineering.stack-selector
engineering.architecture-designer
engineering.data-modeler
engineering.api-contract-writer
engineering.auth-designer
engineering.security-designer
engineering.frontend-builder
engineering.backend-builder
engineering.database-builder
engineering.integration-builder
engineering.admin-builder
engineering.code-reviewer
engineering.refactorer
engineering.test-writer
engineering.migration-planner
```

### 5.7 Infrastructure & Release Organization

책임:

- 개발·스테이징·운영 환경 구성
- 환경변수·시크릿·CI/CD 구성
- 도메인·DNS·SSL·배포·롤백
- 비용·성능 예산 관리

플러그인:

```text
vercel
deployment
dns
ssl
cloud-storage
monitoring
```

봇:

```text
infra.environment-planner
infra.repository-bootstrapper
infra.ci-configurator
infra.secret-policy-checker
infra.deployment-configurator
infra.dns-checker
infra.ssl-checker
infra.cost-estimator
release.release-planner
release.build-verifier
release.deployer
release.smoke-tester
release.rollback-manager
release.release-note-writer
```

### 5.8 Collaboration & Documentation Organization

책임:

- 프로젝트 문서·회의록·결정사항 기록
- 협업 공간·채널·역할 생성
- 프로젝트 봇 설정
- 진행률 알림·최종 인수인계

플러그인:

```text
notion
notion-provisioner
discord
discord-server-provisioner
discord-bot-factory
gmail
calendar
slack
```

봇:

```text
collaboration.notion-workspace-builder
collaboration.project-wiki-builder
collaboration.meeting-recorder
collaboration.decision-recorder
collaboration.discord-workspace-builder
collaboration.channel-policy-builder
collaboration.project-bot-configurator
collaboration.status-announcer
collaboration.handoff-writer
```

Discord 서버·봇, Notion 데이터베이스, GitHub 저장소 생성은 모두 외부
상태 변경이므로 사전 계획·권한·사용자 승인을 요구한다.

### 5.9 Quality & Security Organization

책임:

- 요구사항·디자인·코드 결과 검증
- 인코딩·PR·CI·접근성·보안·성능 검사
- ClaimLatch 증거 생성
- 머지·배포 차단 여부 판정

봇:

```text
qa.requirements-traceability
qa.acceptance-test-runner
qa.unit-test-runner
qa.integration-test-runner
qa.e2e-test-runner
qa.browser-matrix-runner
qa.mobile-test-runner
qa.visual-regression-checker
qa.accessibility-checker
qa.security-scanner
qa.dependency-scanner
qa.performance-checker
qa.encoding-checker
qa.diff-checker
qa.secret-leak-checker
qa.pr-format-checker
qa.ci-result-checker
qa.claimlatch-verifier
qa.bug-triage
qa.merge-gate
```

### 5.10 Operations Organization

책임:

- 운영 상태·로그·비용·백업 모니터링
- 장애 감지·분류·복구
- 사용자 피드백·분석·개선 작업 관리

봇:

```text
ops.health-monitor
ops.log-analyzer
ops.incident-detector
ops.incident-responder
ops.backup-checker
ops.restore-planner
ops.cost-monitor
ops.feedback-classifier
ops.analytics-reader
ops.experiment-planner
ops.improvement-prioritizer
ops.retrospective-writer
```

## 6. 플러그인 종류

### 6.1 Domain Plugin

전문 작업 공간과 자체 데이터를 가진다.

```text
web-design
chat-history
project-management
```

### 6.2 Connector Plugin

외부 서비스의 API·OAuth·권한을 연결한다.

```text
github
figma
gmail
notion
discord
```

### 6.3 Provisioner Plugin

외부 리소스를 생성·설정한다.

```text
github-project-provisioner
discord-server-provisioner
notion-workspace-provisioner
bot-factory
```

### 6.4 Worker Plugin

특정 전문 작업을 수행한다.

```text
github-bot
design-review-bot
copywriter-bot
test-runner
```

### 6.5 Validator Plugin

결과를 독립적으로 검사한다.

```text
encoding-checker
accessibility-checker
claimlatch
visual-regression-checker
```

## 7. 원자 작업 계약

모든 작업은 다음 계약을 사용한다.

```json
{
  "taskId": "engineering.pr.encoding-check",
  "phase": "testing",
  "role": "qa.encoding-checker",
  "plugin": "repository-files",
  "inputs": ["artifact:pull-request-diff"],
  "dependsOn": ["engineering.pr.created"],
  "sideEffect": "read_only",
  "approval": "none",
  "preconditions": ["diff_is_available"],
  "outputs": ["artifact:encoding-report"],
  "completionCriteria": ["all_files_decode_as_utf8"],
  "validators": [],
  "timeoutSeconds": 60,
  "retryPolicy": {"maxAttempts": 2, "backoffSeconds": 2},
  "idempotencyKey": "projectId:prNumber:headSha",
  "onFailure": "block_merge_and_report",
  "next": ["qa.diff-check", "qa.pr-format-check"]
}
```

## 8. PR·CI·인코딩 검증 흐름

```text
이슈 생성
→ 작업 브랜치 생성
→ 변경 파일 목록 저장
→ 코드 작성
→ 포맷 검사
→ 문법 검사
→ 단위 테스트
→ 통합 테스트
→ UTF-8 strict 검사
→ 깨진 문자 검사
→ git diff --check
→ 줄바꿈·BOM 정책 검사
→ 시크릿 노출 검사
→ PR 제목·본문 한국어 양식 검사
→ CI 실행
→ CI 결과 수집
→ 코드 리뷰
→ 수정 요청 반영
→ 재검증
→ 머지 조건 확인
→ 머지
→ 머지 후 빌드·스모크 테스트
```

하나라도 실패하면 이설은 완료라고 말하지 않는다. 실패한 작업, 파일,
라인, 로그, 재시도 횟수, 다음 조치를 함께 보고한다.

## 9. 프로젝트 실행 예시

사용자 입력:

```text
카페 홈페이지를 만들어줘.
```

이설이 생성하는 실행 조직:

```text
프로젝트 디렉터
├─ 브리프 작성 봇
├─ 리서치 봇
├─ 콘텐츠 봇
├─ 웹 디자인 플러그인
│  ├─ 디자인 컨퍼런스
│  ├─ UX 봇
│  ├─ UI 봇
│  ├─ 디자인 시스템 봇
│  └─ 반응형 검증 봇
├─ 기술설계 봇
├─ GitHub 프로젝트 프로비저너
├─ 프론트엔드 개발 봇
├─ GitHub Bot
├─ 테스트 조직
│  ├─ 브라우저 테스트
│  ├─ 접근성 검사
│  ├─ 시각 회귀 검사
│  └─ ClaimLatch
├─ Notion 문서화 봇
├─ Discord 프로젝트 공간 프로비저너
├─ 배포 봇
└─ 운영 모니터링 봇
```

단순한 랜딩페이지라면 백엔드·결제·관리자·데이터베이스 조직은 생성하지
않는다. 프로젝트 유형과 요구사항에 따라 실행 그래프가 축소·확장된다.

## 10. 완료 게이트

```text
G0 미션 해석 완료
G1 프로젝트 범위 승인
G2 조사 근거 확보
G3 요구사항 추적 가능
G4 콘텐츠·정보구조 확정
G5 UX 흐름 검증
G6 UI·디자인 시스템 검증
G7 기술설계 승인
G8 개발환경 재현 가능
G9 구현 결과와 요구사항 연결
G10 테스트 통과
G11 배포 전 보안·권한·백업 확인
G12 운영 배포 스모크 테스트 통과
G13 문서·모니터링·복구 준비
G14 최종 증거 패키지 생성
```

## 11. 외부 리소스 생성 정책

다음 작업은 자동 생성 계획까지만 만들고 사용자 승인을 받은 뒤 실행한다.

- Discord 서버·채널·역할 생성
- Discord Bot 생성·권한 부여
- GitHub 저장소·브랜치 보호 생성
- Notion 페이지·데이터베이스 생성
- 외부 메일 발송
- 운영 배포
- 유료 서비스 연결
- 기존 리소스 수정·삭제

프로비저너는 먼저 dry-run 결과를 만들고, 실행 후 생성된 외부 ID와 권한을
Core의 리소스 레지스트리에 저장한다. 재실행하면 기존 리소스를 조회해
중복 생성하지 않는다.

## 12. 성능·패키징 원칙

- 모든 봇을 동시에 실행하지 않는다.
- 실행 그래프에 포함된 봇만 로드한다.
- 커넥터는 호출 직전에 인증·권한을 확인한다.
- 봇은 가능한 한 Core의 공용 런타임을 사용한다.
- 플러그인별 독립 데이터는 해당 플러그인이 소유한다.
- 실행 이벤트·권한·감사 기록은 Core가 소유한다.
- 작업 결과는 파일 전체가 아니라 artifact reference로 전달한다.
- 장시간 작업은 백그라운드 job과 이벤트로 처리한다.
- UI는 작업 진행률과 차단 원인을 표시한다.

## 13. 1차 구현 파트 분배

### Part A — Iseol Core Runtime

- 프로젝트·미션 모델
- 작업 그래프 모델
- 작업 상태 머신
- 봇 레지스트리
- 플러그인 레지스트리
- 의존성 해석기
- 실행 이벤트
- 승인 게이트
- 리소스 레지스트리

### Part B — Web Project Template

- 웹 프로젝트 기본 WBS
- 조건부 작업 확장 규칙
- 단계별 완료 게이트
- 프로젝트별 봇 조합 규칙

### Part C — Web Design Plugin

- 디자인 컨퍼런스
- 디자인 프로젝트 저장소
- 정보구조·UX·UI 작업 공간
- 디자인 시스템
- 에셋·버전 관리
- Figma·Canva·이미지 생성 연결
- 디자인 검증

### Part D — Engineering Plugin Set

- GitHub 커넥터
- GitHub Bot
- 저장소 프로비저너
- PR·브랜치·이슈 자동화
- CI 연동
- 코드 작업·리뷰 작업

### Part E — Documentation & Collaboration

- Notion 커넥터
- Notion 프로젝트 프로비저너
- Discord 커넥터
- Discord 서버 프로비저너
- Bot Factory
- 진행률·결과 알림

### Part F — Quality & Release

- 테스트 실행기
- 브라우저 검증
- 접근성 검증
- 보안 검증
- 인코딩·diff·PR 양식 검사
- ClaimLatch 연동
- 배포·롤백·스모크 테스트

### Part G — Operations & Improvement

- 모니터링
- 장애 대응
- 백업·복구
- 분석·피드백
- 개선 백로그
- 회고·지식 축적

## 14. 성공 기준

1. 주제만 입력해도 프로젝트 초안과 실행 조직이 생성된다.
2. 필요한 파트와 플러그인만 실행 그래프에 포함된다.
3. 각 봇의 입력·출력·권한·완료 조건이 추적된다.
4. 외부 리소스 생성 전 승인 계획을 보여준다.
5. PR·인코딩·CI·테스트·배포 검증이 원자 작업으로 기록된다.
6. 실패한 작업을 정확한 단계에서 재시도할 수 있다.
7. 재실행해도 외부 리소스가 중복 생성되지 않는다.
8. 최종 결과에는 산출물과 검증 증거가 함께 포함된다.
9. 이설은 검증되지 않은 작업을 완료했다고 보고하지 않는다.
10. 단순 프로젝트에는 불필요한 봇·플러그인을 실행하지 않는다.

## 15. 품질 평가 체계

이설은 작업을 수행하는 실행 조직과 결과를 평가하는 평가 조직을 분리한다.
작업을 만든 봇이 자기 결과를 단독으로 통과시키지 못하게 한다.

```text
Worker Bots
   ↓ 산출물·로그·증거
Task Validator
   ↓ 단계별 결과
Phase Review Board
   ↓ 전체 프로젝트
Project Quality Council
   ↓
Portfolio / Client Delivery Decision
```

### 15.1 세 가지 평가 대상

#### 실행 정확성

작업이 계획대로 수행됐는지 확인한다.

- 담당 봇이 올바른 작업을 했는가
- 입력 자료를 빠뜨리지 않았는가
- 허용되지 않은 플러그인을 호출하지 않았는가
- 권한 범위를 초과하지 않았는가
- 출력 형식이 계약과 일치하는가
- 로그와 증거가 남아 있는가
- 재시도·실패 기록이 정확한가

#### 단계 품질

해당 단계의 결과물이 다음 단계에서 사용할 수 있는지 확인한다.

- 산출물이 모두 생성됐는가
- 요구사항과 연결되는가
- 누락·중복·모순이 없는가
- 단계 완료 조건을 만족하는가
- 다음 단계의 입력으로 충분한가
- 검토 의견이 반영됐는가

#### 프로젝트 품질

전체 결과가 실제 사용자와 고객에게 제공할 수 있는 수준인지 확인한다.

- 처음 목표를 해결하는가
- 전체 사용자 흐름이 끊기지 않는가
- 디자인과 코드가 일치하는가
- 모든 핵심 기능이 실제로 동작하는가
- 품질·보안·접근성·성능 기준을 통과하는가
- 운영과 유지보수가 가능한가
- 문서와 인수인계가 충분한가
- 포트폴리오 또는 외주 납품 자료로 설명 가능한가

## 16. 원자 작업 체크리스트

모든 Atomic Task는 실행 전·실행 중·실행 후 체크리스트를 가진다.

### 16.1 실행 전

- 작업 ID가 고유한가
- 작업 목적이 명확한가
- 선행 작업이 완료됐는가
- 입력 산출물이 존재하는가
- 입력 버전이 고정됐는가
- 담당 봇이 해당 작업 권한을 가지고 있는가
- 호출할 플러그인이 허용 목록에 있는가
- 외부 상태 변경 여부가 판정됐는가
- 승인이 필요한 경우 승인 상태가 확인됐는가
- 타임아웃·재시도 정책이 있는가
- 중복 실행 방지 키가 있는가
- 실패 시 복구 경로가 있는가

### 16.2 실행 중

- 실제 호출 대상이 계획과 일치하는가
- 입력 데이터가 변조되지 않았는가
- 권한이 변경되지 않았는가
- 예상하지 못한 외부 액션이 발생하지 않았는가
- 진행 이벤트가 기록되는가
- 장시간 작업이 멈추지 않았는가
- 비용·시간 예산을 초과하지 않는가
- 중간 결과가 저장되는가

### 16.3 실행 후

- 출력 산출물이 생성됐는가
- 출력 형식이 계약과 일치하는가
- 빈 값·깨진 값·가짜 성공이 없는가
- 결과가 요구사항과 연결되는가
- 독립 검증기가 실행됐는가
- 검증 증거가 저장됐는가
- 로그에 민감정보가 포함되지 않았는가
- 다음 작업에 필요한 참조가 등록됐는가
- 실패하면 완료 상태로 위장되지 않았는가
- 사용자가 이해할 수 있는 요약이 생성됐는가

## 17. 단계별 품질 체크리스트

### 17.1 주제 입력·프로젝트 정의

- 사용자 목표가 한 문장으로 정리됐는가
- 목표 사용자와 사용 상황이 정의됐는가
- 성공 기준이 측정 가능한가
- MVP와 제외 범위가 분리됐는가
- 가정과 사실이 구분됐는가
- 모르는 정보가 질문 목록으로 남았는가
- 위험·비용·외부 권한이 분류됐는가
- 프로젝트 유형이 올바르게 선택됐는가
- 필요한 조직만 생성됐는가

### 17.2 조사

- 핵심 결정마다 출처가 있는가
- 조사 출처가 실제로 열리는가
- 출처와 모델 추론이 구분됐는가
- 경쟁 서비스 비교 기준이 일관적인가
- 레퍼런스의 라이선스가 확인됐는가
- 조사 결과가 요구사항과 디자인 결정에 반영됐는가
- 조사 결과가 단순 링크 모음으로 끝나지 않았는가

### 17.3 요구사항·콘텐츠

- 모든 핵심 기능에 사용자 목적이 있는가
- 정상·오류·빈 상태가 정의됐는가
- 권한별 동작이 정의됐는가
- 기능마다 완료 조건이 있는가
- 요구사항이 페이지·코드·테스트와 추적되는가
- 실제 사용할 문구가 들어갔는가
- 임시 문구·Lorem ipsum·가짜 데이터가 제거됐는가
- 한글 인코딩과 맞춤법이 확인됐는가
- SEO·법적·개인정보 문구가 필요한 경우 포함됐는가

### 17.4 정보구조·UX

- 사이트맵과 실제 라우트가 일치하는가
- 핵심 작업까지의 경로가 완성됐는가
- 뒤로가기·새로고침·세션 만료를 고려했는가
- 로딩·성공·실패·빈 상태가 모두 있는가
- 모바일·태블릿·데스크톱 흐름이 정의됐는가
- 키보드·스크린리더 사용 흐름이 고려됐는가
- 사용자가 다음에 무엇을 해야 하는지 명확한가
- 불필요한 단계가 없는가

### 17.5 UI·디자인 시스템

- 모든 핵심 화면이 같은 디자인 언어를 사용하는가
- 컬러·폰트·간격·그리드 토큰이 정의됐는가
- 컴포넌트 상태가 모두 정의됐는가
- 텍스트가 말풍선·카드·버튼·모달에서 잘리지 않는가
- 반응형에서 겹침·넘침·깨짐이 없는가
- 이미지·아이콘의 라이선스가 확인됐는가
- 포커스·호버·비활성·오류 상태가 보이는가
- 디자인과 실제 구현이 일치하는가

### 17.6 기술설계·개발환경

- 선택한 기술이 요구사항에 적합한가
- 폴더 구조와 모듈 경계가 명확한가
- 데이터 모델과 API 계약이 일치하는가
- 인증·권한·세션 정책이 정의됐는가
- 환경변수와 시크릿이 코드에 들어가지 않았는가
- 개발·스테이징·운영 환경을 재현할 수 있는가
- README만 보고 새 개발자가 실행할 수 있는가
- CI가 로컬과 동일한 핵심 검사를 수행하는가
- 브랜치·커밋·PR 규칙이 적용되는가

### 17.7 구현·PR

- 모든 변경이 요구사항 또는 버그와 연결되는가
- 변경 범위가 작업 목적에 맞는가
- 불필요한 파일 변경이 없는가
- UTF-8 strict 읽기가 통과하는가
- 깨진 문자와 대체문자가 없는가
- BOM·줄바꿈 정책이 통과하는가
- `git diff --check`가 통과하는가
- 포맷·린트·타입 검사가 통과하는가
- 단위·통합 테스트가 통과하는가
- 시크릿·토큰·개인정보가 노출되지 않았는가
- PR 제목·본문이 정해진 양식인가
- 변경 전후 화면과 동작 증거가 있는가
- 리뷰 의견이 모두 처리됐는가
- CI 결과가 최신 커밋을 기준으로 하는가
- 머지 후에도 실제 실행 검증을 했는가

### 17.8 테스트·배포

- 핵심 사용자 여정이 처음부터 끝까지 통과하는가
- 주요 브라우저·화면 크기에서 동작하는가
- 접근성 검사가 통과하는가
- 보안 검사가 통과하는가
- 성능 예산을 지키는가
- 운영 환경에서만 발생하는 오류가 없는가
- 배포 전 백업과 롤백 방법이 확인됐는가
- DNS·SSL·환경변수·외부 연결이 정상인가
- 배포 후 스모크 테스트가 통과하는가
- 모니터링과 장애 알림이 작동하는가

## 18. 전체 프로젝트 품질 심사

모든 단계가 끝나면 Project Quality Council이 작업 하나가 아니라 전체
프로젝트를 다시 평가한다.

### 18.1 계획 대비 결과

- 최초 목표가 실제 제품에 반영됐는가
- 계획된 요구사항이 모두 추적되는가
- 제외된 요구사항에 이유가 기록됐는가
- 생성된 조직과 플러그인이 실제 필요했는가
- 완료 처리됐지만 검증되지 않은 작업이 없는가
- 고아 산출물과 고아 작업이 없는가

### 18.2 사용자 관점

- 사용자가 처음 방문해 목적을 이해하는가
- 핵심 행동을 찾을 수 있는가
- 입력·오류·성공 흐름이 자연스러운가
- 모바일에서도 실제 사용할 수 있는가
- 느리거나 멈춘 것처럼 보이는 구간이 없는가
- 전문 용어가 사용자에게 노출되지 않는가
- 고객에게 설명 가능한 가치가 있는가

### 18.3 제품 완성도

- 화면 간 시각적 일관성이 있는가
- 기능 간 동작 방식이 일관적인가
- 콘텐츠 톤과 브랜드가 일치하는가
- 디자인·코드·문서가 서로 모순되지 않는가
- 예외 상황이 정상 상황만큼 처리됐는가
- 외부 연결이 끊겨도 사용자에게 명확히 안내하는가
- 데이터 손실·중복·권한 오류가 없는가

### 18.4 기술 완성도

- 새 환경에서 재현 가능한가
- 테스트를 다시 실행할 수 있는가
- 운영자가 장애 원인을 찾을 수 있는가
- 로그와 감사 기록이 충분한가
- 백업과 복원이 실제로 검증됐는가
- 의존성·시크릿·권한이 관리되는가
- 유지보수자가 구조를 이해할 수 있는가

### 18.5 납품·포트폴리오 완성도

- 배포 URL 또는 실행 방법이 있는가
- 프로젝트 소개 문서가 있는가
- 문제·해결 방법·주요 결정이 설명되는가
- 핵심 화면 캡처 또는 데모가 있는가
- 기술 스택과 아키텍처가 정리됐는가
- 테스트·품질 결과가 증거와 함께 있는가
- 사용한 외부 리소스와 라이선스가 정리됐는가
- 설치·운영·인수인계 문서가 있는가
- 변경 이력과 알려진 제한사항이 있는가
- 외주 고객에게 전달할 수 있는 형태인가

## 19. 평가 점수와 차단 규칙

기본 평가 점수는 다음 영역으로 계산한다.

```text
목표·요구사항 추적성       15점
리서치·콘텐츠·정보구조     10점
UX·UI·디자인 시스템        15점
기술설계·코드 품질         20점
테스트·보안·접근성·성능    20점
배포·운영·복구             10점
문서·인수인계·포트폴리오   10점
총점                      100점
```

기본 판정:

```text
90점 이상 + 차단 결함 없음  → portfolio_ready
85점 이상 + 차단 결함 없음  → client_ready_with_notes
70~84점                    → revision_required
70점 미만                  → replan_required
```

점수와 무관하게 다음 결함이 있으면 완료를 차단한다.

- 핵심 사용자 흐름이 작동하지 않음
- 데이터 손실 또는 중복 생성 위험
- 인증 우회·권한 상승
- 시크릿·개인정보 노출
- 배포 후 복구 방법 없음
- 검증 결과를 조작하거나 증거가 없음
- 실제로 실행하지 않았는데 완료로 보고함
- 외부 리소스를 승인 없이 생성·수정·삭제함

결함 등급:

```text
P0 즉시 차단·롤백
P1 출시 전 반드시 수정
P2 다음 작업 전에 수정 권장
P3 기록 후 백로그 등록
```

## 20. 최종 평가 보고서

프로젝트 종료 시 이설은 다음 보고서를 생성한다.

```text
프로젝트 요약
최초 요청
최종 결과
실행한 조직·봇·플러그인
생성된 산출물 목록
요구사항 추적표
단계별 게이트 결과
실패·재시도·복구 기록
테스트 결과
PR·CI·인코딩 검사 결과
보안·접근성·성능 결과
배포·운영 상태
남은 제한사항
총점과 품질 등급
포트폴리오·외주 납품 가능 여부
다음 개선 작업
```

최종 보고서는 단순한 요약문이 아니라 각 주장을 산출물·로그·테스트 결과와
연결한 증거 패키지여야 한다.

## 21. 자연어 한 문장 실행 계약

### 21.1 사용자에게 보이는 입력

사용자는 단계, 봇, 플러그인, 기술 스택을 선택하지 않는다.

```text
오늘 식단을 정리해주는 웹 만들어줘.
```

```text
카페 홈페이지를 만들고 실제로 배포해줘.
```

```text
내 포트폴리오 사이트를 만들어서 GitHub와 Notion에 정리해줘.
```

이 한 문장이 이설 프로젝트의 시작점이다.

### 21.2 내부 변환 과정

```text
자연어 요청
→ 의도·목표·산출물 해석
→ 프로젝트 유형 분류
→ 기본 가정 생성
→ 필요한 질문만 선별
→ 웹 프로젝트 템플릿 선택
→ 필요한 파트·봇·플러그인 동적 구성
→ 작업 그래프 컴파일
→ 외부 리소스 생성 계획 확인
→ 실행
→ 단계별 검증
→ 전체 프로젝트 심사
→ 결과물·링크·증거 보고
```

사용자는 내부 조직도를 볼 필요가 없다. 필요하면 진행 화면에서 현재 어떤
파트가 실행 중인지 확인할 수 있지만, 작업을 직접 분배하거나 다음 단계를
수동으로 실행시키지 않는다.

### 21.3 질문 최소화 규칙

이설은 정보가 조금 부족하다는 이유만으로 작업을 멈추지 않는다.

#### 바로 실행하는 경우

- 일반적인 웹사이트 목적을 추정할 수 있는 경우
- 기본적인 디자인·기술 선택으로 결과를 만들 수 있는 경우
- 외부 계정이나 위험한 액션이 필요하지 않은 경우
- 부족한 정보가 결과의 핵심을 바꾸지 않는 경우

이 경우 이설은 기본 가정을 기록하고 먼저 결과물을 만든다.

#### 질문하는 경우

- 답에 따라 결과가 완전히 달라지는 핵심 정보가 없는 경우
- 결제·개인정보·인증처럼 높은 위험이 있는 경우
- 외부 서비스 생성·삭제·배포·메일 발송 승인이 필요한 경우
- 법적·보안상 임의로 결정할 수 없는 경우

질문이 필요하면 여러 번 나누지 않고 한 번에 묶어서 보여준다.

```text
현재 바로 만들 수 있지만, 아래 2가지만 확인하면 결과가 더 정확해져.

1. 식단은 사용자가 직접 입력하는 방식으로 할까, 예시 데이터로 시작할까?
2. 결과물은 로컬 미리보기까지만 만들까, 실제 배포까지 할까?
```

### 21.4 “오늘 식단 정리 웹” 실행 예시

사용자 입력:

```text
오늘 식단 정리해주는 웹 만들어줘.
```

이설의 내부 판단:

```text
프로젝트 유형: 식단 기록·정리 웹
기본 사용자: 개인 사용자
필수 화면: 오늘 식단, 식사 추가, 식단 목록
필수 기능: 아침·점심·저녁 구분, 음식명·시간·메모 입력
선택 기능: 칼로리, 영양소, 통계, 검색
초기 데이터: 빈 상태 + 예시 데이터 선택 가능
기본 저장: 로컬 프로젝트 저장소
기본 디자인: 모바일 우선 반응형
필요 조직: 기획, 콘텐츠, UX, UI, 프론트엔드, QA
제외 조직: 결제, 관리자, 외부 협업, 복잡한 백엔드
```

자동 실행:

```text
1. 프로젝트 브리프 생성
2. 식단 기록 사용자 흐름 설계
3. 오늘 식단 화면 구조 설계
4. 입력·편집·삭제 흐름 설계
5. 모바일 우선 UI 제작
6. 빈 상태·오류·저장 상태 제작
7. 로컬 데이터 저장 구현
8. 반응형 구현
9. 브라우저·모바일 테스트
10. 접근성·텍스트 잘림·시각 일관성 검사
11. 실행 가능한 결과물 생성
12. README와 사용법 작성
13. 최종 품질 보고서 생성
```

최종 응답에는 최소한 다음이 포함되어야 한다.

```text
완료한 프로젝트
실행 링크 또는 로컬 실행 방법
생성된 파일·저장소
주요 기능
테스트 결과
알려진 제한사항
추가로 할 수 있는 개선 작업
```

### 21.5 외부 액션 처리

자연어 한 문장 실행 원칙은 플러그인 선택을 사용자에게 떠넘기지 않는다는
뜻이지, 위험한 외부 액션을 무승인으로 실행한다는 뜻은 아니다.

이설은 필요한 외부 액션을 한 번에 묶어서 보여준다.

```text
프로젝트를 완성하려면 다음 외부 작업이 필요해.

- GitHub 저장소 생성
- Notion 프로젝트 문서 생성
- Discord 프로젝트 공간 생성
- 운영 배포

필요 권한과 생성될 리소스를 확인했어.
[한 번에 승인하고 실행]
```

승인 후에는 사용자가 플러그인별 설정 화면을 돌아다니지 않고 이설이 순서에
맞게 연결·생성·검증한다.

### 21.6 사용자 경험 성공 기준

1. 사용자는 자연어 한 문장만으로 프로젝트를 시작할 수 있다.
2. 사용자는 봇·플러그인·기술 스택을 직접 선택하지 않아도 된다.
3. 이설은 프로젝트 유형에 맞지 않는 조직을 실행하지 않는다.
4. 부족한 정보가 있어도 가능한 부분은 먼저 진행한다.
5. 질문이 필요하면 한 번에 묶어서 요청한다.
6. 외부 액션은 필요한 경우 한 번의 승인으로 처리한다.
7. 작업 진행 중 사용자의 일반적인 컴퓨터 사용을 방해하지 않는다.
8. 결과물과 실행 방법이 반드시 제공된다.
9. 테스트·검증되지 않은 결과는 완료로 보고하지 않는다.
10. 결과물은 포트폴리오·외주 납품을 검토할 수 있는 품질 보고서를 포함한다.
