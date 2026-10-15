# EEEE 채팅 기록 플러그인

## 목표

사용자가 플러그인 화면에서 `EEEE 채팅 기록`을 설치하면, 별도 창에서
EEEE에게 보낸 명령과 Ollama 답변을 휴대폰 채팅처럼 확인하고 같은 대화에
새 명령을 계속 보낼 수 있게 한다.

## 경계

- EEEE 코어는 로컬 Ollama 라우팅, SQLite 기록, 로컬 API를 제공한다.
- 채팅 기록은 `apps/eeee/plugins/eeee_chat_history`에 있는 별도 설치 패키지다.
- 설치 시 플러그인 패키지만 사용자 데이터의 `plugins/eeee_chat_history`로 복사한다.
- 플러그인 창은 별도 프로세스로 열리지만 Ollama 프로세스나 SQLite를 별도로 만들지 않는다.
- 플러그인 삭제는 패키지만 제거하고 `conversation_turns` 기록은 보존한다.
- 플러그인은 `conversationId`를 유지해 펫 입력창과 같은 `desktop-default` 대화를 사용한다.

## 계약

- `GET /api/assistant/conversations`: 대화 목록과 최신 미리보기
- `GET /api/assistant/conversations/{conversationId}`: 메시지 페이지 조회
- `POST /api/assistant/route`: 기존 EEEE 명령 라우트로 새 메시지 전송
- `POST /api/plugins/eeee-chat-history/install`: 패키지 설치
- `GET /api/plugins/eeee-chat-history/launch`: 설치된 플러그인 진입점 확인

모든 채팅 기록 API는 로컬 데스크톱 요청만 허용한다. 메시지 조회는 `limit`과
`beforeId` 커서로 제한해 긴 대화를 한 번에 렌더링하지 않는다.
