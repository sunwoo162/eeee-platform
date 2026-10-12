# EEEE Plugin Platform Foundation Design

## Outcome

EEE는 기본적으로 모든 대화를 처리하고, 사용자가 선택적으로 플러그인을 설치하고 계정을 연결했을 때만 해당 서비스의 capability를 라우팅한다. 이번 범위는 새로운 플러그인 기능을 만드는 것이 아니라, 설치·권한·계정 연결·상태·실행 경계를 제품 수준으로 완성하고 Notion 연결 흐름을 실제로 검증하는 것이다.

## Scope and non-goals

### In scope

- 선택적 플러그인 카탈로그를 조회한다. Notion을 포함한 외부 서비스는 기본 설치되지 않는다.
- 로컬 플러그인 manifest를 검증하고 설치/등록/삭제할 수 있다.
- 사용자별 권한 승인과 연결 상태를 저장한다.
- OAuth 또는 사용자가 제공한 credential을 플러그인 연결 경계에서만 처리한다.
- 플러그인의 건강 상태와 실행 상태를 EEEE의 capability router에 반영한다.
- 미설치·미연결·권한 거부·오류 상황을 자연어 대화에서 정확히 안내한다.
- 기존 `NotionClient`를 선택적 Notion connector로 연결하고, 실제 API 요청은 transport 주입으로 테스트한다.
- 연결/해제/권한 거부/health check/실행/재시작 격리를 검증한다.

### Out of scope

- Notion API 기능을 새로 설계하거나 확장하는 것
- 포트폴리오·이설 등 신규 플러그인 구현
- 원격 플러그인 마켓플레이스, 자동 다운로드, 자동 패키지 설치
- 사용자의 credential을 서버나 모델 prompt에 업로드하는 방식
- 사용자의 명시적 승인 없는 외부 side effect

## Product behavior

사용자는 플러그인 화면에서 다음 상태를 본다.

```text
미설치 → 설치됨 → 연결 필요 → 연결 중 → 연결됨
                                      ├─ 일시정지
                                      └─ 오류
```

- 기본 설치 상태는 `미설치`다.
- 설치는 manifest 검증을 통과한 로컬 package/source에만 허용한다.
- 연결은 필요한 permission scope를 사용자에게 보여준 뒤 승인받는다.
- 연결 완료 전에는 해당 plugin capability를 자동 라우팅 목록에 넣지 않는다.
- 연결된 플러그인이 health check에 실패하면 capability를 즉시 숨기고 `오류` 상태로 전환한다.
- EEEE가 특정 서비스 요청을 받았지만 플러그인이 없거나 연결되지 않았다면, 작업을 실행한 척하지 않고 설치/연결에 필요한 다음 행동을 한 문장으로 안내한다.
- 해제는 credential을 삭제하고 capability를 라우팅 목록에서 제거한다. 감사 이벤트와 일반 실행 envelope에는 credential 원문이 들어가지 않는다.

## Architecture

### Existing boundaries to preserve

- `PluginManifest`, `PluginHost`, `PluginRegistrationStore`, `ExecutionEnvelope`를 기존 로컬 plugin execution boundary로 유지한다.
- subprocess 실행, protocol version, correlation id, timeout, health probe를 유지한다.
- `CapabilityRegistry`의 dynamic provider를 통해 연결되고 healthy한 capability만 노출한다.
- 기존 `NotionClient`는 typed REST adapter로 유지하고 connection service가 수명주기를 담당한다.

### New boundaries

1. **Plugin catalog**
   - 설치 가능한 optional plugin metadata를 제공한다.
   - catalog entry는 `id`, `name`, `version`, `description`, `authMode`, `permissions`, `installSource`, `defaultInstalled=false`를 가진다.
   - 이번에는 local bundled catalog만 제공하고 network registry는 만들지 않는다.

2. **Connection service**
   - `PluginConnection`을 사용자 id와 plugin id에 귀속한다.
   - 상태, 승인된 scope, provider account label, 마지막 health 결과, updated timestamp를 저장한다.
   - token value는 connection record나 log에 저장하지 않는다.
   - credential store는 `CredentialStore` 인터페이스로 추상화하고 테스트는 in-memory fake를 사용한다. OS secure store 구현은 Windows Credential Manager/keyring adapter로 분리할 수 있게 한다.

3. **Connector adapter**
   - `PluginConnector`는 `connect`, `disconnect`, `health`, `invoke` 경계를 가진다.
   - Notion adapter는 기존 `NotionClient`를 감싸며 `pages.read`와 `pages.write` scope를 선언한다.
   - OAuth client 설정이 없는 오픈소스 설치에서는 연결을 `awaiting_authentication`으로 보고, token을 요구하는 경우에는 사용자가 명시적으로 제공한 local credential만 사용한다. 상태 이름은 기존 저장소의 `awaiting_authentication`과 통일한다.

4. **Management API/UI contract**
   - catalog 조회, 설치, 연결 승인, 연결 해제, pause/resume, health 조회, capability 조회를 명시적인 JSON contract로 제공한다.
   - 기존 `/api/plugins` lifecycle과 호환되는 alias를 유지하되, 사용자 scope가 필요한 연결 API는 user/session boundary를 통과한다.

## Data contracts

### Plugin catalog entry

```json
{
  "id": "notion",
  "name": "Notion",
  "version": "1.0.0",
  "description": "Notion pages connector",
  "authMode": "token-or-oauth",
  "permissions": ["pages.read", "pages.write"],
  "installSource": "bundled-optional",
  "defaultInstalled": false
}
```

### User plugin connection

```json
{
  "userId": "user-1",
  "pluginId": "notion",
  "status": "connected",
  "approvedPermissions": ["pages.read"],
  "accountLabel": "workspace name",
  "lastHealth": "healthy",
  "lastError": null,
  "updatedAt": "2026-10-13T00:00:00Z"
}
```

`credentialRef`는 내부 secure store key로만 존재하고 API response, memory, prompt, execution output에는 노출하지 않는다.

## Security and failure rules

- unknown manifest fields, unsupported protocol, unknown permission, path traversal, malformed credential, and invalid provider response는 fail-closed한다.
- plugin process는 기존 subprocess isolation과 timeout을 사용한다.
- plugin이 연결되지 않았거나 paused/failed면 invocation은 실행되지 않고 blocked envelope를 남긴다.
- 권한 승인 없이 connect하지 않는다. `pages.write`처럼 side effect가 있는 scope는 read scope와 분리해 표시한다.
- 모든 user connection lookup은 authenticated user id를 key로 사용한다. 다른 사용자의 connection id를 추측해도 404/unauthorized로 처리한다.
- credential은 `repr`, JSON, audit event, memory candidate, assistant response에 들어가지 않는다.
- Notion API의 401/403/429/5xx는 각각 사용자 재연결, 권한 재승인, 재시도 가능한 오류, provider unavailable로 변환한다.

## Verification scenarios

1. 신규 설치에서 Notion이 기본 연결되지 않고 optional catalog entry로만 보인다.
2. manifest가 설치되고 `connection required` 상태가 된다.
3. read-only permission 승인으로 연결되며 write scope는 승인 목록에 들어가지 않는다.
4. Notion health check가 성공하면 capability가 router에 나타난다.
5. Notion request는 injected transport를 통해 올바른 auth/version headers와 request body로 전송된다.
6. 연결 해제 후 token reference와 capability가 제거된다.
7. user A의 연결이 user B의 API 조회/실행에 노출되지 않는다.
8. provider failure는 실행한 척하지 않고 blocked/failed 상태와 재연결 안내를 남긴다.
9. 애플리케이션 재시작 후 registration, connection status, audit state가 일관되게 복원된다.

## Rollout

1. Existing plugin contracts and storage are normalized without changing current echo fixture behavior.
2. Optional catalog and connection service are added behind the current local API.
3. Notion adapter is registered but remains `defaultInstalled=false`.
4. Desktop/control-center surfaces consume the API and show install/connect/health actions.
5. Full Python + TypeScript verification and packaged desktop smoke test run before merge.
