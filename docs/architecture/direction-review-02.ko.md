# Gleave 방향성 점검 02 — 대화 중심 UI

기준: 2026-10-27
브랜치: feat/unified-chat
판정: P1 UI 개발 기반 검증 완료. 전체 Gleave 최종 제품 완성 아님.

## 핵심 사용자 목표 확인

- [x] Gleave 대화가 중심 화면이며 복잡한 IDE 패널을 기본 노출하지 않음.
- [x] 왼쪽에 개인/팀 -> 프로젝트 -> 하위 채팅 목록 구성.
- [x] 프로젝트 드래그앤드롭으로 채팅 소속 이동 및 해제.
- [x] 여러 채팅의 승인된 프로젝트 기억을 같은 ContextBuilder로 조회.
- [x] 프로젝트 기억 추가·철회 패널과 대화 서버 스트리밍 및 취소 UI.
- [x] Windows 개발용 단일 로컬 API /chat/에서 React 프론트 제공.
- [x] 기존 EEEE 루트 화면 / 및 기존 API 엔드포인트 유지.
- [ ] GPT/Claude/Codex 실제 provider 및 수동 선택: 아직 개발 전.
- [ ] 모델 선택 Auto 최적화 및 비용 상한: 아직 개발 전.
- [ ] 배포 가능한 독립 Windows 앱(설치 없이 실행): 아직 개발 전.
- [ ] 팀 계정 인증, 멤버 초대 및 기기 간 동기화: 아직 개발 전.
- [ ] 파일 편집·터미널·미리보기·코드 에이전트 실행: 아직 개발 전.
- [ ] 타사 이력 가져오기, 자체 LLM 학습/승격 UI: 아직 개발 전.

## 테스트/검증

- React + TypeScript + Vite: npm run build 성공, JS/CSS 에셋 생성.
- Python (대화/워크스페이스/API 관련): 82 passed, 1 warning.
- 실제 uvicorn API에서 GET /chat/ => HTTP 200, 에셋 참조 확인.
- GET /v1/workspaces 호출 성공, 개인 작업 공간·프로젝트·채팅 생성 수동 HTTP smoke 성공.
- Git diff whitespace 검사 및 새 코드 ruff 검증 통과.
- GitHub CI는 push 후 별도로 확인해야 함.

## 발견한 제품/기술 과제

1. 기존 EEEE 기본 conversation_provider는 personal_llm로, 사용자가 지적한 품질 문제가 남음.
2. UI의 모델 위치는 *현재 활성 Provider*만 표시. Auto/수동 선택이라고 오인하도록 가짜 컨트롤은 두지 않음.
3. 로컬 팀 workspace 데이터 모델은 멀티유저 인증된 실제 협업 기능과 구별해야 함.
4. P1 브라우저 제공은 독립 데스크톱 exe가 아님. 데스크톱 shell 패키징은 별도 P 단계.
5. UI는 SSE 정상/취소 후 durable 메시지를 다시 조회함. 장시간 연결 재시도/도구 실행 UX는 후속 회귀 대상.
6. Google Fonts 등 외부 CDN 의존성 없음. 데이터와 UI는 loopback에서 동작.

다음 단계에서 가장 중요한 것은 provider hub: GPT/Claude/Codex 연결, 수동 고정 및 Auto 라우팅 시 모델별 권한/비용/현재 작업 맥락의 일관성 검증.
