# Gleave 방향성 점검 04 — Codex 개발 작업 패널

일자: 2026-10-28
브랜치: feat/unified-chat
판정: Codex 개발 에이전트의 P3 기초 구현은 제품 목표와 일치. 아직 종합 완성품이 아님.

## 이번 개발

- ChatGPT형 대화 중심 UI를 유지하면서 프로젝트 채팅 우측에 Codex 작업 패널을 노출.
- chat project ID와 Gleave 작업 루트의 기존 로컬 소스 폴더를 명시적으로 연결; 소속/권한 검증.
- 별도 전용 빈 폴더를 클릭 한 번으로 생성할 수 있으며, 기존 소스 자동 복사는 하지 않음.
- JSONL stdio 기반 Codex app-server initialize -> initialized -> thread/start -> turn/start 흐름.
- readOnly 분석과 명시적 동의를 받은 workspaceWrite 실행을 분리.
- workspaceWrite 범위는 연결된 root에 제한하고 networkAccess=false로 요청.
- 지원하는 command/fileChange 추가 승인 요청을 받아 사용자가 accept/decline, 미지원 요청은 거절.
- 실시간 agentMessage delta, diff 업데이트, 단계 로그, 완료/실패, 취소 및 동시 작업 제한.
- 소유하지 않은 채팅, 다른 프로젝트 채팅, 등록되지 않은 폴더, 상대경로 탈출, symlink 탈출 검사.
- FastAPI 서버 종료 시 남은 Codex 작업 프로세스 종료.

## 설계 일치 여부

**맞는 부분**
- Gleave 한 화면에서 일상 채팅과 개발 작업을 병행할 수 있는 기반.
- 모델 선택과 프로젝트 채팅/기억은 기존 EEEE 데이터 원본을 유지.
- 별도 Codex 앱 창을 직접 열 필요 없는 제품 방향.
- 위험한 작업을 암묵적으로 시작하지 않고 모드와 추가 권한을 명확히 구분.

**아직 부족한 부분**
- Codex는 일반 채팅의 model selector에서 비활성 상태. 이번 버전은 별도 우측 에이전트 패널.
- Codex의 작업 단계, 변경된 파일, 승인 기록을 중앙 채팅 로그/DB에 영속 기록하지 않음.
- 프로젝트 파일 편집기/터미널/브라우저 미리보기 아직 미완성.
- GPT·Claude 실제 결제 인증, 모델 품질 기반 자동 라우팅 실측은 미검증.
- Windows 앱 패키징, 팀원 인증, 원격 동기화, AI 대화 Import/학습은 진행 대상.

## 품질/보안

- localhost만 Codex API 접근 허용하며, 기존 X-EEEE-User-Id는 신뢰할 수 있는 다중 사용자 인증 수단이 아님.
- 메모리는 승인된 프로젝트 노트만 Codex에 포함; 팀원 원문이나 전역 개인 기억을 자동 전달하지 않음.
- Codex 작업 요청과 프로젝트 파일 내용이 모델 공급자에게 전송될 수 있음을 UI·문서에 표시.
- 사용자 명시 동의 없이 workspaceWrite 작업 시작 불가; 추가 권한 요청은 별도 사용자 승인.
- 단순 시스템 프롬프트의 비밀 유출 금지 문구만으로 보안을 보장할 수 없으므로 실제 sandbox/네트워크 제약과 별도 점검을 병행해야 함.
- app-server 실제 설치된 Windows Codex CLI의 initialize handshake 성공(모델 사용을 통한 실 E2E 아님).
- Mock Codex 프로세스 테스트에서 protocol lifecycle, approval wait/decline, cancel 검증.
- 변경 후 npm build 및 pytest/CI 테스트로 회귀 검사.

다음 목표: Codex 작업과 canonical Gleave 채팅 이벤트의 연결, task state 영속화,
프로젝트 코드 리뷰(diff)/터미널/웹 미리보기, 사용자별 승인 감사 로그.
