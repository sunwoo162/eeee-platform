# EEEE 범용 플러그인 레지스트리·OAuth 연결 설계

## 목적

EEEE가 사용자가 직접 개발한 로컬 플러그인과 이미 존재하는 외부 서비스 커넥터를 같은 방식으로 제공한다. 사용자는 플러그인 목록에서 설치를 누르고, 권한을 확인한 뒤 해당 서비스에 로그인하면 된다. 일반 대화는 계속 로컬 우선으로 처리하고, 연결된 플러그인의 capability만 작업 라우팅에 참여시킨다.

## 범위

이번 단계는 범용 설치·연결 기반과 1차 커넥터 계약을 제공한다.

1. 버전이 고정된 EEEE 플러그인 레지스트리
2. 설치와 사용자별 연결의 분리
3. OAuth 2.0 Authorization Code + PKCE 기반 브라우저 로그인 흐름
4. 토큰의 OS credential store 저장과 사용자 scope 분리
5. MCP, OpenAPI/OAuth, 기존 local-process 플러그인을 수용하는 공통 connector 계약
6. 권한 미리보기, 연결 상태, health check, 재인증, 해제
7. 1차 제공 후보의 메타데이터와 실제 구현 가능 상태 표시
8. 연결되고 healthy한 capability만 EEEE 라우터에 동적으로 투영

실제 Gmail·Google Calendar·Google Drive·Google Contacts·Notion·GitHub·Figma·Slack·Linear·Todoist·Outlook의 provider API 구현은 동일한 계약을 따르는 단계별 커넥터 작업으로 진행한다. 번들 카탈로그는 먼저 로컬에 설치할 수 있지만, 커넥터가 설정되지 않은 서비스는 `설치됨 · 연결 설정 필요`로만 표시하고 연결·라우팅하지 않는다.

## 비목표

- ChatGPT 내부 플러그인 구현물을 그대로 복사하거나 사용자 계정을 공유하지 않는다.
- EEEE 서버에 모든 사용자의 provider token을 중앙 평문으로 저장하지 않는다.
- provider별 API를 하나의 거대한 서비스에 직접 하드코딩하지 않는다.
- 기존 local plugin manifest/command 실행 경로를 제거하지 않는다.
- 플러그인 연결 없이 일반 대화를 GPT 웹 창으로 우회하지 않는다.

## 사용자 흐름

```text
플러그인 스토어 열기
  -> 설치
  -> 권한·side effect 확인
  -> 연결
  -> 기본 브라우저 로그인
  -> state/PKCE 검증 후 local callback
  -> 사용자별 credential 저장
  -> provider health check
  -> 연결됨 및 capability 활성화
```

연결 실패는 `reauthentication_required`, `permission_denied`, `provider_unavailable`, `state_mismatch`, `cancelled`처럼 사용자 행동이 명확한 상태로 표시한다. UI에는 access token, refresh token, client secret을 표시하지 않는다.

## 레지스트리

레지스트리 항목은 다음 정보를 가진다.

- `id`, `name`, `version`, `description`
- `provider`, `protocol`: `mcp`, `openapi-oauth`, `local-process`
- `authMode`: `oauth-pkce`, `token`, `token-or-oauth`, `none`
- `permissions`: 읽기/쓰기와 side-effect 수준
- `capabilities`: intent, trigger, action, approval 정책
- `connector`: 실행 가능한 등록된 connector id
- `availability`: `available`, `coming_soon`, `disabled`
- `defaultInstalled`: 기본 설치 여부. 외부 provider는 false

초기에는 안전한 bundled registry를 사용한다. 원격 registry를 추가할 때는 서명 검증과 allowlist가 먼저 필요하며, 원격 manifest가 임의의 로컬 명령을 실행하도록 허용하지 않는다.

## Connector 계약

모든 provider adapter는 다음 경계를 구현한다.

```text
connect(user, credential, approved_permissions) -> connection
health(connection) -> health result
invoke(connection, action, input) -> typed output
disconnect(connection) -> void
```

MCP adapter는 MCP endpoint와 provider OAuth를 감싸고, OpenAPI adapter는 등록된 operation schema와 OAuth token을 감싼다. provider별 차이는 adapter 내부에만 존재하며 platform, router, UI는 provider-neutral 계약만 본다.

## 인증·보안

- OAuth callback은 loopback `127.0.0.1`의 일회성 port와 짧은 만료 시간을 사용한다.
- authorization `state`와 PKCE verifier는 연결 시도별로 생성하고 callback에서 검증한다.
- credential은 OS keyring에 opaque reference로 저장한다.
- SQLite에는 credential reference, provider, user scope, 상태, 승인 권한만 저장한다.
- `X-EEEE-User-Id`는 local-only API에서만 허용하며 malformed 또는 cross-user scope를 거부한다.
- uninstall/disconnect 시 credential을 폐기하고 provider refresh token revoke를 지원한다.
- 쓰기 작업은 manifest의 side-effect와 approval 정책을 따라 추가 확인한다.

오픈소스 배포에서는 두 인증 설정을 지원한다.

1. EEEE가 제공하는 공식 OAuth client 설정
2. 자체 호스팅 사용자가 provider별 client id/secret을 설정하는 설정 경로

개발자 계정의 client secret이나 token을 모든 사용자와 공유하지 않는다.

## 라우팅

라우터는 다음 순서로 동작한다.

1. 일반 대화는 local-first secretary가 처리한다.
2. 설치되지 않은 플러그인 capability는 후보에서 제외한다.
3. 연결되지 않았거나 paused/failed/unhealthy인 capability는 후보에서 제외한다.
4. 연결되고 healthy한 capability만 intent와 trigger로 선택한다.
5. 외부 side effect 작업은 approval policy를 적용한다.
6. 사용자가 요청한 provider가 설치·연결되지 않았으면 필요한 다음 행동을 안내한다.

## 1차 제공 후보

### 구현 우선순위 A

- Google Workspace: Gmail, Google Calendar, Google Drive, Google Contacts
- Notion
- GitHub

### 구현 우선순위 B

- Figma
- Slack
- Linear
- Todoist
- Outlook Email
- Outlook Calendar

후속 후보는 Atlassian/Jira/Confluence, Asana, Trello, ClickUp, Canva, Miro, Dropbox, Vercel, WordPress, Shopify, Zoom, Teams다. 실제 OAuth/API 계약을 검증하기 전에는 installable 상태로 등록하지 않는다.

## 오류·복구

- OAuth 취소: 연결 시도만 정리하고 기존 연결은 유지
- state/PKCE 불일치: credential 저장 금지, 재시도 안내
- provider 401/refresh 실패: `reauthentication_required`, capability 비활성화
- provider 403: `permission_denied`, 부족한 scope 표시
- rate limit/5xx: `provider_unavailable`, 기존 credential 유지
- connector 미등록: 로컬 설치는 허용하되 연결·라우팅은 차단하고 설정 필요 상태로 표시
- uninstall: 연결 해제, credential 삭제, 설치 상태 제거를 원자적으로 처리

## 검증 기준

자동 테스트로 다음을 확인한다.

- registry schema와 duplicate/unknown connector 검증
- 설치와 연결 상태의 분리
- OAuth state/PKCE 성공·실패·취소·재인증 흐름
- credential이 응답, 로그, SQLite에 노출되지 않음
- 사용자 A의 connection/capability가 사용자 B에 보이지 않음
- 건강하지 않은 provider가 라우팅되지 않음
- permission/side-effect approval이 적용됨
- 기존 local-process plugin과 기존 API contract가 회귀하지 않음
- fake provider로 설치부터 invoke까지 end-to-end 동작

## 단계적 출시

1. 범용 registry와 protocol/connector registry
2. OAuth callback broker와 credential lifecycle
3. UI 설치·권한·연결 상태 화면
4. Google Workspace/Notion/GitHub connector
5. Figma/Slack/Linear/Todoist/Outlook connector
6. 전체 회귀 테스트, packaged desktop build, PR 단위별 merge

각 provider는 별도 feature commit/PR로 분리하고, 연결되지 않은 provider를 보여주기식으로 등록하지 않는다.
