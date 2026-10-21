# Web GPT 오류 분류 보강 계획

## 목표

ChatGPT Web bridge의 timeout·인증 필요·연결 불가·잘못된 응답을 하나의 `unavailable` 문자열로 뭉개지 않고 정본 오류 코드로 전달한다. 그래야 재시도 정책, 사용자 안내, 대화 기록의 실패 원인이 실제 원인과 일치한다.

## 범위

1. 공통 `AgentResult`에 선택적 `error_code`를 추가한다.
2. ChatGPT Web runtime이 네트워크 timeout, 인증 필요, HTTP bridge 오류, 잘못된 응답을 구분한다.
3. 대화 provider가 runtime의 오류 코드를 보존한다.
4. 기존 호출자의 위치 인자 호환성을 유지한다.
5. 각 오류 유형의 회귀 테스트와 전체 EEEE 검증을 실행한다.

## 완료 조건

- timeout은 `chatgpt_web_timeout`으로 기록된다.
- 로그인/인증 문제는 `chatgpt_web_auth_required`로 기록된다.
- provider가 runtime이 준 코드를 덮어쓰지 않는다.
- 기존 성공·재시도·대화 흐름 테스트가 모두 통과한다.
