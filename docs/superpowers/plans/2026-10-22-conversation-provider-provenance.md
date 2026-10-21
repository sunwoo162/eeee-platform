# 대화 provider provenance 보강 계획

## 목표

정본 대화 기록에 실제로 답변을 생성한 provider와 model을 저장한다. Web GPT가 기본 fallback으로 전환된 경우에도 선택된 provider 이름만 남기지 않고 실제 사용 provider를 기록해 사용자가 나중에 원인을 추적할 수 있게 한다.

## 범위

1. provider adapter가 현재 실제 사용 provider/model을 노출한다.
2. Web·Ollama fallback wrapper가 fallback 시 실제 provider를 갱신한다.
3. ConversationService가 assistant 메시지의 생성·완료·실패 모든 경로에 provider/model을 저장한다.
4. 기존 provider가 metadata를 제공하지 않는 경우에도 기존 동작을 유지한다.
5. 실제 provider 기록과 fallback 기록을 회귀 테스트로 고정한다.

## 완료 조건

- Web GPT 성공 응답은 `provider=chatgpt_web`으로 기록된다.
- 기본 fallback 성공 응답은 `provider=builtin`으로 기록된다.
- 명시적 Ollama 응답은 실제 모델 이름을 기록한다.
- provider가 실패해도 선택 provider가 아니라 실제 시도 provider와 오류 코드가 보존된다.
