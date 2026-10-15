# EEEE 성장형 Web GPT 코어 설계

## 목표

EEEE를 고정 응답형 로컬 챗봇이 아니라, Web GPT를 판단 provider로 선택할 수
있고 사용자의 명시적 피드백과 검증된 기억을 다음 대화에 반영하는 성장형 개인
비서 코어로 만든다.

## 범위

이번 변경은 EEEE Core에 한정한다.

- 일반 대화 provider는 기본적으로 `chatgpt_web`을 사용한다.
- 기존 설치 호환을 위해 `auto`를 허용하지만, Web GPT만 선택하며 Ollama로
  자동 전환하지 않는다.
- `ollama`는 마이그레이션/진단 목적의 명시적 예외 경로로만 남긴다.
- 명시적으로 `chatgpt_web`을 선택했는데 연결되지 않으면 Ollama로 몰래
  전환하지 않고 명확한 오류를 반환한다.
- Web GPT, Ollama, 테스트 provider가 모두 같은 `ConversationProvider` 계약을
  사용한다.
- 빈 답변, provider 실패, 취소를 정상 완료로 저장하지 않는다.
- 승인된 active memory를 대화 컨텍스트에 bounded하게 포함한다.
- 사용자 피드백을 별도 ledger에 저장한다.
- 사용자가 명시적으로 기억하라고 한 피드백만 active memory로 승격한다.
- 모든 provider 상태와 선택 결과를 `/v1/runtime`에서 확인할 수 있게 한다.

이번 변경에 포함하지 않는다.

- Chat History 별도 UI/plugin 구현
- ISEOL Agent 팀 내부 구현 변경
- 외부 provider 업무 API 구현
- 모델 weight fine-tuning
- Web GPT 브라우저 자동화 자체 재작성

## 성장 규칙

```text
대화 결과
  ↓
사용자 피드백 ledger
  ↓
임시 신호로 보관
  ↓  (사용자가 명시적으로 기억하라고 한 경우)
검증 가능한 explicit memory
  ↓
다음 대화 컨텍스트에 bounded하게 반영
```

raw conversation이나 단순 긍정 피드백은 자동으로 active memory가 되지 않는다.
피드백은 나중에 품질 평가와 패턴 분석에 사용할 수 있도록 보존하되, 사용자
승인 없는 기억이 응답을 오염시키지 않게 한다.

## Provider 규칙

- `auto`: Web GPT bridge ready → Web GPT, otherwise `chatgpt_web_unavailable`.
- `chatgpt_web`: Web GPT configured가 아니면 `chatgpt_web_unavailable` 실패.
- `ollama`: Ollama만 사용.
- provider 오류는 assistant의 `completed` message가 되지 않는다.
- Web GPT adapter는 EEEE context를 하나의 안전한 assistant prompt로 전달하고,
  credentials나 임의 executable instruction을 포함하지 않는다.
- runtime status는 Core health와 provider readiness를 분리한다.

## 검증 규칙

- provider가 delta를 하나도 내지 않았거나 공백만 반환하면
  `provider_empty_response`로 실패한다.
- terminal response만 completed로 저장한다.
- feedback의 `remember=true`에 correction이 없으면 거부한다.
- 기억에 source message와 feedback evidence가 없으면 active memory로 만들지
  않는다.
- active memory는 context budget을 넘기지 않는다.

## 완료 기준

1. Web GPT bridge가 ready인 환경에서 일반 대화가 Web GPT adapter를 선택한다.
2. Web GPT를 명시했는데 연결이 없으면 Ollama fallback 없이 오류 상태로 끝난다.
3. 기존 Ollama adapter는 명시적 migration/debug 경로에서만 동작한다.
4. 빈 provider 응답이 completed로 저장되지 않는다.
5. active memory가 다음 대화에 포함되고, revoked/superseded memory는 포함되지
   않는다.
6. feedback ledger가 재시작 후에도 남는다.
7. 명시적인 `remember=true` 피드백만 active memory가 된다.
8. 전체 결정론적 테스트와 provider 선택/성장 회귀 테스트가 통과한다.
