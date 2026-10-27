# Gleave 방향성 점검 07 — 타사 AI 대화 내보내기 가져오기

기준: 2026-10-28 · feat/unified-chat

## 목표와 구현

- 기존 GPT/Claude/Codex의 사용자 소유 대화 내보내기 파일을 Gleave로 가져오는 첫 버전.
- 지원 대상: ChatGPT conversations.json, Claude conversations.json, Codex CLI 세션 JSONL.
- 파일 선택 -> 형식별 미리보기 -> 1~20개 대화 명시 선택 -> 프로젝트 지정 후 가져오기.
- 가져온 대화는 원본 id/provider/content digest를 보관. 같은 사용자/서비스/원본 id 재입력은 중복 건너뜀.
- 가져온 대화는 Gleave 일반 채팅처럼 읽을 수 있고 이후 이어서 질문할 수 있음.
- 원본 텍스트는 기존 사용자/assistant 역할만 저장. system/developer, 도구 출력, 추론, 명령 및 미디어는 제외.
- 프로젝트에 연결하더라도 **자동 프로젝트 기억은 0건**, 동일 프로젝트의 다른 채팅이 import raw excerpts를 자동 참고하지 않도록 차단.
- 사용자는 가져온 채팅의 **user 메시지**에 있는 기억 승인 버튼을 클릭하고 확인해야만 프로젝트 기억이 생성됨.
- 이미 지원하는 memory source_message_id를 이용해 승인된 기억과 대화의 출처를 추적 가능.
- 프로젝트 접근 권한 없이 타인의 프로젝트로 import할 수 없음. 다른 사용자의 source origin도 조회 불가능.
- 동일 source_id의 import와 메시지/링크는 단일 SQLite transaction으로 생성하며 중복을 방지.

## 개인정보 및 학습 원칙

- 파일은 브라우저에서 읽고 **로컬 Gleave API**로 전송하여 처리. 타사 API로 자동 업로드하지 않음.
- 저장된 imported transcript를 사용자가 직접 열어 GPT/Claude 등으로 질문하면 해당 모델로 내용이 보내질 수 있음.
- 가져온 원본을 개인 LLM 학습 데이터로 자동 등록하지 않음.
- 개인/팀 기억을 자동 섞지 않음. 팀 프로젝트의 승인 기억은 팀 모델 컨텍스트에 반영될 수 있으므로 명시적 승인 UI 필요.
- 시스템 프롬프트나 Codex AGENTS.md 역할의 삽입 데이터를 사용자 대화로 오인하지 않도록 이벤트 타입을 제한.
- CSV, ZIP, HTML 직접 Import는 미지원이며, 공식 export 압축 파일에서 JSON을 직접 추출해야 함.
- 현재 8MB/파일, 200개 대화/파일, 20개 확인·저장/요청, 최대 500개 메시지/대화(추가 텍스트 길이 제한)인 **초기 MVP 제한**.
- 일부 중첩 멀티모달·비표준 포맷은 가져오지 않고 오해의 소지가 없도록 분명히 안내해야 함.
- ChatGPT mapping에서 current_node를 기준으로 선택된 대화 분기만 가져온다.

## 완료 검증 조건

- 공급자별 텍스트-only 필터 및 안전한 역할 파싱 테스트.
- Preview는 아무 것도 저장하지 않고, Commit 후 canonical 채팅 생성/프로젝트 링크 확인.
- 같은 파일 반복 import와 부적절한 범위·권한 요청 차단.
- 사용자가 승인하기 전 import 원문은 별도 프로젝트 채팅으로 확산되지 않는지 검사.
- 승인된 출처 메시지는 기존 프로젝트 memory 스토어로 생성되고 새 컨텍스트에서만 사용되는지 확인.
- React 빌드, Python 회귀, GitHub CI 통과 여부 확인.

## 다음 단계

대용량 export ZIP/증분 스트리밍/다중 파일 가져오기, Claude 최신 다양한 스키마 호환,
과거 대화 검색/병합 검토, 사용자 수정·중복 후보 심사, 기억 추출 **승인 후보** UI,
정식 데이터 삭제/되돌리기 UX, 실제 로컬 파일 Import E2E 테스트.
