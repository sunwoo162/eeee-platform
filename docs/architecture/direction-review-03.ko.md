# Gleave 방향성 점검 03 — 요청별 모델 선택

기준: 2026-10-27, feat/unified-chat
판정: P2 다중모델 대화 전환의 초기 구현 완료. 핵심 요구의 일부이며 Codex는 미완료.

## 구현 상태
- 한 canonical conversation과 user/project memory를 보존한 채 각 turn에 selected_provider 저장.
- GPT(OpenAI Responses SSE), Claude(Anthropic Messages SSE) 별도 API provider 구현.
- Auto v0: 우선순위 + 코드 키워드 규칙. 가격/지연/품질을 실측한 Smart Router는 아님.
- 채팅 상단에서 Auto/GPT/Claude/개인 LLM/Ollama 및 연결 가능 모델을 선택.
- 수동 선택은 다른 모델로 무단 fallback하지 않으며 연결이 없으면 명시적인 실패.
- 다른 모델로 재시도하는 경우 원래 요청의 provider 선택 보존.
- API 키는 서버측 환경변수 OPENAI_API_KEY / ANTHROPIC_API_KEY, 모델은 GLEAVE_*_MODEL.
- API 키가 없는 개발/테스트 환경에서는 외부 요청을 보내지 않음.
- 기존 API, 대화 ID, 프로젝트 폴더, 메시지 provenance 및 상태 머신 유지.

## 검증과 한계
- GPT·Claude HTTP SSE 구조는 MockTransport와 고정 모의 서버 응답으로 검증.
- 실제 사용자의 API 인증·결제·모델 권한/요금·네트워크 E2E는 미검증.
- Codex는 일반 대화 API가 아니라 권한과 파일 변경을 동반하는 개발 에이전트.
  현재 UI에 표시되지만 연결 전에는 비활성화. Codex 앱 서버 + 승인/복구를 P3에서 개발.
- Auto 선택은 규칙 기반이므로 자동 모델 최적화 성공을 주장하면 안 됨.
- API 키에 종속된 서비스 사용은 별도 과금될 수 있다.
- 팀 공유는 아직 인증되지 않은 로컬 라벨 수준. 개인 기억의 클라우드 전달 정책 UI 미구현.
- GitHub Push의 CI는 별도 확인 대상.

## 목표 일치 판단
같은 채팅에서 원하는 모델을 바꾸는 제품 목표로 진전. 다만 대화/기억 공유가 올바른지
실제 API를 통한 회귀 테스트, Codex 실행/인간 승인, 예상 비용/컨텍스트 정산, 앱 패키징,
공식 대화 기록 Import가 남아 있으므로 최종 버전이라 부르지 않는다.
