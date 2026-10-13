# EEEE 플러그인 레지스트리·OAuth 구현 계획

> **실행 규칙:** 각 작업은 테스트를 먼저 추가하고, 해당 테스트가 실패하는 것을 확인한 뒤 구현한다. 작업 완료마다 독립 커밋을 만들고, 커넥터별로 별도 PR이 가능한 단위로 유지한다.

## 목표

설계 문서 `docs/superpowers/specs/2026-10-13-plugin-registry-oauth-design.md`를 구현한다. EEEE가 설치 가능한 외부 커넥터를 정확히 표시하고, 사용자가 브라우저에서 계정을 연결하면 사용자별 credential과 healthy capability가 생기며, 일반 대화와 플러그인 라우팅이 분리되어야 한다.

## 현재 구조와 변경 경계

- `apps/eeee/app/plugins/catalog.py`: 현재 Notion 단일 bundled catalog. 레지스트리 스키마와 installable/coming-soon 검증을 확장한다.
- `apps/eeee/app/plugins/connectors.py`: provider-neutral connector 계약. OAuth connection과 health/error 타입을 추가한다.
- `apps/eeee/app/plugins/platform.py`: 설치·연결·health·capability 투영의 단일 오케스트레이터. provider별 로직을 넣지 않는다.
- `apps/eeee/app/plugins/credentials.py`: OS keyring/메모리 테스트 저장소. opaque reference만 platform에 노출되도록 유지한다.
- `apps/eeee/app/api/routes.py`: user-scoped plugin API와 desktop snapshot. OAuth 시작/콜백/상태 API를 추가한다.
- `apps/eeee/app/main.py`: connector registry와 callback broker를 조립한다.
- `apps/eeee/app/static/*`: control center의 설치·권한·연결 UX를 추가한다.
- `apps/eeee/tests/plugins/*`, `apps/eeee/tests/api/*`: 모든 신규 계약의 RED→GREEN 테스트를 둔다.

## 작업 1 — Registry와 connector registration

**변경:** `app/plugins/catalog.py`, 새 `app/plugins/registry.py`, `tests/plugins/test_catalog.py`, 새 `tests/plugins/test_registry.py`.

- `protocol`, `availability`, `auth_mode`, `connector_id`, provider metadata를 가진 strict entry를 만든다.
- `available`은 등록된 connector가 실제로 존재할 때만 허용한다.
- `coming_soon`은 catalog에는 보이되 install endpoint에서 거부하고 UI에 설치 버튼을 만들지 않는다.
- duplicate plugin id, duplicate capability, unknown connector를 시작 시 fail-fast 한다.
- 기존 Notion entry와 기존 catalog API JSON alias를 유지한다.

**검증:** catalog schema, legacy Notion response, installable gate, duplicate/unknown rejection.

**커밋:** `feat: add validated plugin registry contracts`

## 작업 2 — OAuth state/PKCE callback broker

**변경:** 새 `app/plugins/oauth.py`, `app/plugins/oauth_models.py`, `app/api/routes.py`, `app/main.py`, 새 `tests/plugins/test_oauth.py`, `tests/api/test_plugin_oauth_routes.py`.

- 연결 시도마다 random state, PKCE verifier/challenge, expiry, user id, plugin id를 생성한다.
- authorization URL을 만들고 browser-open 가능한 URL을 API로 반환한다.
- loopback callback에서 state/expiry/plugin match를 검증한다.
- 취소, state mismatch, expired session, provider error를 typed result로 변환한다.
- verifier와 provider token은 API response/log/SQLite에 노출하지 않는다.
- 실제 provider 호출은 injectable OAuth transport로 둬서 테스트는 fake server로 실행한다.

**검증:** 성공, 취소, state mismatch, 만료, 다른 user/plugin callback, token redaction.

**커밋:** `feat: add secure oauth pkce callback flow`

## 작업 3 — Generic protocol connectors

**변경:** 새 `app/plugins/protocol_connectors.py`, `app/plugins/provider_errors.py`, `tests/plugins/test_protocol_connectors.py`.

- `MCPConnector`, `OpenAPIOAuthConnector`, `LocalProcessConnector`를 공통 `PluginConnector` 계약에 맞춘다.
- operation/capability schema를 manifest로부터 projection한다.
- provider 401/403/429/5xx, timeout, malformed response를 표준 health/error로 매핑한다.
- connector registry가 platform에 provider adapter를 주입한다.
- arbitrary remote code 실행은 허용하지 않고, registry에 선언된 endpoint/operation만 허용한다.

**검증:** fake MCP/OpenAPI endpoint connect-health-invoke-disconnect, error mapping, capability projection, unregistered connector rejection.

**커밋:** `feat: add generic plugin protocol connectors`

## 작업 4 — Platform credential lifecycle와 API

**변경:** `app/plugins/platform.py`, `app/plugins/api_models.py`, `app/api/routes.py`, `tests/plugins/test_platform.py`, `tests/plugins/test_platform_routes.py`.

- credential 입력은 token을 write-only `SecretStr`로 받고, OAuth callback은 platform connect로 이어진다.
- 기존 연결 중 재연결 시 새 credential이 healthy일 때만 교체한다.
- disconnect/uninstall은 credential delete와 provider revoke hook을 실행한다.
- status는 `not_installed`, `awaiting_authentication`, `connecting`, `connected`, `paused`, `failed`를 정확히 반환한다.
- user A/B 격리와 local-only user header 검증을 유지한다.
- plugin capability는 connected + healthy일 때만 router에 투영한다.

**검증:** credential rotation, disconnect cleanup, uninstall cleanup, user isolation, unhealthy routing gate, redacted API output.

**커밋:** `feat: complete user scoped plugin connection lifecycle`

## 작업 5 — Control center install/connect UX

**변경:** `app/static/*`, desktop snapshot routes, UI contract tests.

- catalog entry마다 Install/Connect/Open/Reconnect/Resume 상태를 표시한다.
- 권한과 side-effect 수준을 연결 전 확인할 수 있게 한다.
- Connect 클릭은 OAuth authorization URL을 기본 브라우저로 열고, callback 완료를 polling/event로 반영한다.
- 연결 중·실패·재인증·provider unavailable 상태를 구분한다.
- 토큰과 callback query를 UI에 출력하지 않는다.

**검증:** browser contract, desktop snapshot, install/connect/disconnect state transitions, failed callback UX.

**커밋:** `feat: add plugin store connection controls`

## 작업 6 — 1차 실제 connector adapters

각 provider를 별도 커밋/PR로 작업한다. 실제 provider API를 호출하는 코드는 injectable HTTP client와 provider fixture를 사용한다. provider client id/secret은 환경변수 또는 사용자 설정에서만 읽고 저장소에 넣지 않는다.

### 6A — Google Workspace

`gmail`, `google-calendar`, `google-drive`, `google-contacts`를 공통 Google OAuth scope와 provider API adapter로 구현한다. 읽기 capability와 쓰기 capability의 permission을 분리하고, 메일 발송·일정 변경·파일 변경은 항상 approval을 요구한다.

**커밋/PR:** `feat: add google workspace connectors`

### 6B — Notion·GitHub

기존 Notion adapter를 OAuth/token 두 경로와 registry 계약으로 옮기고 GitHub repository/issue/PR/CI read capability부터 추가한다. write action은 approval을 요구한다.

**커밋/PR:** `feat: add notion and github connectors`

### 6C — Figma·Slack·Linear·Todoist·Outlook

각 provider의 공개 OAuth/API/MCP 계약을 확인한 것만 installable로 등록한다. 확인되지 않은 provider는 `coming_soon`으로 유지한다.

**커밋/PR:** provider별로 분리

## 작업 7 — Secretary/router integration

**변경:** `app/assistant/router.py`, `app/kernel/service.py`, 새/기존 assistant tests.

- 일반적인 인사·질문은 local-first로 처리한다.
- 사용자가 “메일 보내”, “일정 등록”, “노션에 저장”처럼 provider capability를 요청하면 연결 상태를 확인한다.
- 미설치면 Install, 미연결이면 Connect, 권한 부족이면 Reconnect/permission 안내를 반환한다.
- plugin 결과를 대화 응답으로 자연스럽게 요약하되 provider 내부 오류와 인증 오류는 숨기지 않는다.
- 기존 Notion routing과 local-process plugin regression을 보장한다.

**검증:** local-first latency path, connected plugin invoke, missing-install/connect guidance, approval-required write action, regression suite.

**커밋:** `feat: route secretary requests through healthy plugins`

## 작업 8 — Release 검증과 PR 분리

- 각 작업별 focused tests와 전체 `pytest` 실행
- `python -m compileall -q app`
- `git diff --check`
- desktop build 및 packaged self-test
- OAuth/credential redaction 수동 검토
- provider별 PR은 독립 merge 가능하도록 분리
- main 최신 반영 후 merged branch 삭제

**커밋:** `chore: verify plugin platform release`

## 실행 순서와 중단 기준

작업 1~5와 7은 현재 저장소에서 바로 구현한다. 작업 6은 provider의 공식 OAuth/API 계약과 테스트 가능한 endpoint가 확인된 provider만 installable로 올린다. client credentials나 provider 정책이 없는 경우에는 기능을 가장한 catalog entry를 추가하지 않고 `coming_soon`으로 남긴다.

각 작업마다 RED→GREEN 테스트, 독립 커밋, focused suite를 완료한 뒤 다음 작업으로 이동한다. 전체 완료 전에는 “모든 플러그인 연결 완료”라고 보고하지 않는다.
