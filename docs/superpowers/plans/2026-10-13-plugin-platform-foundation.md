# Plugin Platform Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** EEEE가 먼저 자연스러운 개인 비서 대화·기억·후속 맥락을 안정적으로 처리한 뒤, 선택형 플러그인을 설치하고 사용자별로 권한 승인·계정 연결·상태 확인·안전한 capability 라우팅을 수행하도록 만든다.

**Architecture:** 먼저 개인 비서 코어가 대화 history·선호·안전하게 추출한 기억을 하나의 bounded context로 컴파일하고, 로컬 대화 lane이 그 context를 실제 프롬프트와 후속 응답에 반영하게 한다. 그 위에 기존 `PluginHost`의 subprocess 경계와 `PluginRegistrationStore`를 로컬 플러그인 실행용으로 유지하면서 카탈로그·설치 상태·사용자별 연결·credential 저장소·provider connector를 담당하는 `PluginPlatformService`를 추가하고, Notion은 기존 `NotionClient`를 감싸는 첫 번째 connector로 연결한다. capability router와 데스크톱 control center는 연결되고 health가 정상인 capability만 소비한다.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, SQLite, httpx, keyring, pytest, 기존 PySide6/static control-center API.

**Spec:** `docs/superpowers/specs/2026-10-13-plugin-platform-foundation-design.md`

## Global Constraints

- 외부 서비스 플러그인은 기본 설치되지 않으며 catalog에서 선택적으로 설치한다.
- 상태 흐름은 `미설치 → 설치됨 → 연결 필요 → 연결 중 → 연결됨 → 일시정지/오류`를 API의 `not_installed`, `available`, `awaiting_authentication`, `connecting`, `connected`, `paused`, `failed`로 표현한다.
- 연결 완료 전에는 해당 plugin capability를 EEEE 자동 라우팅 목록에 넣지 않는다.
- credential 원문은 API response, prompt, execution output, audit event, 일반 로그에 넣지 않는다.
- 권한 승인 없이 connect하지 않으며 `pages.write` 같은 side effect scope는 read scope와 분리한다.
- 기존 local subprocess plugin protocol, timeout, correlation id, health probe, echo fixture 동작을 깨지 않는다.
- Notion 기능을 새로 설계하지 않고 기존 `NotionClient`를 adapter 경계 안에서 재사용한다.
- 이번 범위에서는 원격 marketplace, 자동 다운로드, 포트폴리오·ISEOL 플러그인 구현을 하지 않는다.
- 모든 플러그인 연결 조회와 실행은 authenticated/local principal의 user id로 격리한다.
- 일반 대화는 연결된 로컬 대화 모델을 우선 사용하고, GPT Web은 전문 작업 lane에서만 사용한다.
- 로컬 모델이 없을 때 canned 응답을 실제 AI처럼 가장하지 않고, 가능한 범위와 다음 선택지를 명확히 말한다.

## Review Focus

- 잘못된 manifest와 알 수 없는 permission이 설치·연결을 통과하지 않는지 — Task 1의 manifest/catalog rejection test.
- credential이 오류·audit·API 응답에 노출되지 않는지 — Task 2의 redaction/secure-reference test와 Task 5의 response test.
- 사용자 A의 연결이 사용자 B의 상태·capability·실행에 노출되지 않는지 — Task 2/5의 cross-user isolation tests.
- Notion 401/403/429/5xx가 provider-neutral 상태와 사용자 행동으로 변환되는지 — Task 3의 transport error matrix test.
- restart와 health failure 뒤 capability가 거짓으로 노출되지 않는지 — Task 4/7의 persistence and routing tests.
- 같은 대화의 후속 질문이 최근 대화·선호·안전한 기억을 실제 provider 입력에 반영하는지 — Task 0의 secretary context tests.

---

### Task 0: Personal secretary conversation core

**Files:**
- Create: `apps/eeee/app/assistant/secretary.py`
- Modify: `apps/eeee/app/agent/local_runtime.py`
- Modify: `apps/eeee/app/agent/hybrid_runtime.py`
- Modify: `apps/eeee/app/kernel/capabilities.py`
- Modify: `apps/eeee/app/assistant/service.py`
- Modify: `apps/eeee/app/main.py`
- Test: `apps/eeee/tests/assistant/test_secretary_core.py`
- Test: `apps/eeee/tests/agent/test_local_runtime.py`
- Test: `apps/eeee/tests/agent/test_hybrid_runtime.py`

**Interfaces:**
- `SecretaryContext` carries `conversation_id`, recent turns, preference values, and compiled safe memory text with bounded sizes.
- `PersonalSecretary.build_prompt(text: str, context: SecretaryContext) -> str` produces a Korean assistant prompt that contains the current request, recent turns in chronological order, and only the safe memory packet.
- `PersonalSecretary.rememberable_facts(text: str) -> list[tuple[str, str]]` extracts only non-sensitive explicit or strongly implied user preferences/facts; secrets and credentials are rejected.
- `LocalConversationRuntime.run` and `OllamaBackend.complete_text` accept the compiled context without changing the `AgentRuntime` public contract.
- `FastLocalConversationRuntime` must not return one generic sentence for every unknown input; it returns a context-aware acknowledgement or a truthful unavailable response with the next action.
- `GeneralConversationCapability` uses `PersonalSecretary` for every ordinary conversation and returns provider metadata plus the actual assistant message.

- [ ] **Step 1: Write failing secretary conversation tests**

  Test that a follow-up request receives the previous turn and a saved preference in the provider prompt; unrelated conversation history is bounded; a user secret is omitted; a plain backend receives a natural Korean prompt instead of the old fixed “편하게 말해줘” loop; provider identity remains truthful.

- [ ] **Step 2: Run the focused tests and verify they fail**

  Run: `pytest apps/eeee/tests/assistant/test_secretary_core.py apps/eeee/tests/agent/test_local_runtime.py apps/eeee/tests/agent/test_hybrid_runtime.py -q`

  Expected: FAIL because the secretary context compiler and context-aware fallback do not exist.

- [ ] **Step 3: Implement the bounded secretary context**

  Add the typed context compiler and safe fact extraction. Reuse `MemoryContextCompiler` and `MemoryStore.recent_conversation_turns` instead of creating a second persistence ledger. Keep the prompt bounded and redact sensitive values before they reach any provider.

- [ ] **Step 4: Implement context-aware local conversation**

  Pass context as structured provider input, preserve the fast local-first policy, and replace generic canned fallback behavior with deterministic responses for greetings, acknowledgements, follow-ups, capability questions, and unavailable-provider cases. Do not route ordinary chat to GPT Web merely because the local provider failed.

- [ ] **Step 5: Wire the secretary into the general capability and automatic memory path**

  Make `GeneralConversationCapability` build the secretary prompt for every turn. Persist only safe preferences/facts through the existing memory lifecycle, keep short-term turns in the conversation store, and ensure the assistant response is what the user sees—not a routing status or internal placeholder.

- [ ] **Step 6: Run focused and assistant regression tests**

  Run: `pytest apps/eeee/tests/assistant/test_secretary_core.py apps/eeee/tests/assistant/test_assistant_service.py apps/eeee/tests/agent/test_local_runtime.py apps/eeee/tests/agent/test_hybrid_runtime.py apps/eeee/tests/api/test_provider_wiring.py -q`

  Expected: PASS; ordinary chat is local-first, context-aware, truthful, and existing project routing remains separate.

- [ ] **Step 7: Commit**

  ```bash
  git add apps/eeee/app/assistant/secretary.py apps/eeee/app/agent/local_runtime.py apps/eeee/app/agent/hybrid_runtime.py apps/eeee/app/kernel/capabilities.py apps/eeee/app/assistant/service.py apps/eeee/app/main.py apps/eeee/tests/assistant/test_secretary_core.py apps/eeee/tests/assistant/test_assistant_service.py apps/eeee/tests/agent/test_local_runtime.py apps/eeee/tests/agent/test_hybrid_runtime.py apps/eeee/tests/api/test_provider_wiring.py
  git commit -m "feat: strengthen EEEE personal secretary core"
  ```

---

### Task 1: Plugin catalog and normalized lifecycle contracts

**Files:**
- Create: `apps/eeee/app/plugins/catalog.py`
- Modify: `apps/eeee/app/plugins/models.py`
- Modify: `apps/eeee/app/plugins/__init__.py`
- Test: `apps/eeee/tests/plugins/test_catalog.py`
- Test: `apps/eeee/tests/plugins/test_manifest.py`

**Interfaces:**
- Produces `PluginCatalogEntry`, `PluginCatalog`, and normalized `PluginStatus` values used by Tasks 2–6.
- `PluginCatalog.list() -> list[PluginCatalogEntry]` returns bundled optional entries with `default_installed=False`.
- `PluginCatalog.get(plugin_id: str) -> PluginCatalogEntry` raises `KeyError` for unknown ids.
- `PluginCatalogEntry` exposes `id`, `name`, `version`, `description`, `auth_mode`, `permissions`, `install_source`, `default_installed`, and connector type using the repository's camelCase aliases.

- [ ] **Step 1: Write the failing catalog and status tests**

  Pin the bundled Notion entry to `id="notion"`, `authMode="token-or-oauth"`, permissions `pages.read` and `pages.write`, `installSource="bundled-optional"`, and `defaultInstalled=False`. Pin invalid permission metadata and unsupported status values to fail closed.

- [ ] **Step 2: Run the focused tests and verify they fail**

  Run: `pytest apps/eeee/tests/plugins/test_catalog.py apps/eeee/tests/plugins/test_manifest.py -q`

  Expected: FAIL because the catalog contract and normalized status surface do not exist yet.

- [ ] **Step 3: Implement the catalog and model normalization**

  Add the immutable Pydantic catalog contract and a bundled catalog containing metadata only; do not create a fake remote registry or auto-install anything. Expand the plugin status type to include the lifecycle states already accepted by `PluginRegistrationStore`, while retaining the existing local plugin manifest validation rules.

- [ ] **Step 4: Run focused and existing plugin model tests**

  Run: `pytest apps/eeee/tests/plugins/test_catalog.py apps/eeee/tests/plugins/test_manifest.py -q`

  Expected: PASS with no credential values present in any catalog model.

- [ ] **Step 5: Commit**

  ```bash
  git add apps/eeee/app/plugins/catalog.py apps/eeee/app/plugins/models.py apps/eeee/app/plugins/__init__.py apps/eeee/tests/plugins/test_catalog.py apps/eeee/tests/plugins/test_manifest.py
  git commit -m "feat: add optional plugin catalog contracts"
  ```

### Task 2: Persistent installations, user connections, and secure credential references

**Files:**
- Create: `apps/eeee/app/plugins/credentials.py`
- Create: `apps/eeee/app/plugins/connections.py`
- Modify: `apps/eeee/app/storage/sqlite.py`
- Modify: `apps/eeee/app/runtime/store.py`
- Modify: `apps/eeee/app/runtime/__init__.py`
- Modify: `apps/eeee/pyproject.toml`
- Test: `apps/eeee/tests/plugins/test_connections.py`
- Test: `apps/eeee/tests/runtime/test_store.py`

**Interfaces:**
- `CredentialStore.put(user_id: str, plugin_id: str, value: str) -> str` returns only an opaque reference; `get(reference: str) -> str | None`; `delete(reference: str) -> None`.
- `KeyringCredentialStore` is the production adapter; `MemoryCredentialStore` is the deterministic test double. Neither exposes the value in `repr`, JSON, audit, or API DTOs.
- `PluginInstallationStore.install(plugin_id, catalog_version)`, `.remove(plugin_id)`, `.is_installed(plugin_id)`, and `.list()` persist global optional installations.
- `PluginConnectionStore.save(connection)`, `.get(user_id, plugin_id)`, `.list(user_id)`, `.set_status(user_id, plugin_id, status, ...)`, and `.remove(user_id, plugin_id)` persist user-scoped connection projections.
- `PluginConnectionService` validates lifecycle transitions and returns redacted `PluginConnectionView` objects with `userId` omitted from public responses unless explicitly needed internally.

- [ ] **Step 1: Write failing persistence and isolation tests**

  Cover: a fresh database has no installed optional plugins; installing Notion persists across a reopened SQLite store; user A and user B receive separate connection rows; `pages.write` is not implicitly approved by approving `pages.read`; disconnect removes the credential reference and capability eligibility; credential values never appear in serialized connection/audit data.

- [ ] **Step 2: Run focused tests and verify they fail**

  Run: `pytest apps/eeee/tests/plugins/test_connections.py apps/eeee/tests/runtime/test_store.py -q`

  Expected: FAIL because the connection tables, stores, and secure credential boundary are not implemented.

- [ ] **Step 3: Add SQLite tables and store methods**

  Add idempotent `plugin_installations` and `plugin_connections` tables plus indexes. Store only `credential_ref`, approved scopes, account label, health projection, status, error code/message safe for users, and timestamps. Keep existing plugin registration/audit tables unchanged for local subprocess plugins.

- [ ] **Step 4: Implement credential adapters and lifecycle service**

  Use `keyring` under a namespaced service key for the default adapter and an in-memory map for tests. Enforce `not_installed → available → awaiting_authentication → connecting → connected`, and allow only explicit `disconnect`, `pause`, `resume`, or provider failure transitions. Validate user ids and plugin ids before any lookup so cross-user references cannot be guessed into another connection.

- [ ] **Step 5: Run tests and verify persistence/redaction**

  Run: `pytest apps/eeee/tests/plugins/test_connections.py apps/eeee/tests/runtime/test_store.py -q`

  Expected: PASS, including reopen-after-restart and user A/B isolation assertions.

- [ ] **Step 6: Commit**

  ```bash
  git add apps/eeee/app/plugins/credentials.py apps/eeee/app/plugins/connections.py apps/eeee/app/storage/sqlite.py apps/eeee/app/runtime/store.py apps/eeee/app/runtime/__init__.py apps/eeee/pyproject.toml apps/eeee/tests/plugins/test_connections.py apps/eeee/tests/runtime/test_store.py
  git commit -m "feat: persist user-scoped plugin connections"
  ```

### Task 3: Connector boundary and real Notion adapter

**Files:**
- Create: `apps/eeee/app/plugins/connectors.py`
- Create: `apps/eeee/app/plugins/notion_connector.py`
- Modify: `apps/eeee/app/integrations/notion_client.py`
- Test: `apps/eeee/tests/plugins/test_notion_connector.py`
- Test: `apps/eeee/tests/project_runtime/test_notion_documents.py`

**Interfaces:**
- `PluginConnector.connect(user_id: str, credential: Mapping[str, str], approved_permissions: set[str]) -> ConnectorConnection`.
- `PluginConnector.disconnect(user_id: str, connection: PluginConnection) -> None`.
- `PluginConnector.health(connection: PluginConnection) -> ConnectorHealth`.
- `PluginConnector.invoke(connection: PluginConnection, action: str, value: dict[str, object]) -> dict[str, object]`.
- `NotionConnector` implements the interface using `NotionClient`; its supported actions remain `get_page`, `create_project_page`, and `append_revision`, with `pages.read`/`pages.write` checks before the corresponding existing client methods.
- Provider errors map to safe codes `reauthentication_required`, `permission_denied`, `retryable_provider_error`, and `provider_unavailable` without including token or response secrets.

- [ ] **Step 1: Write failing injected-transport tests**

  Use `httpx.MockTransport` to assert Notion-Version and Authorization headers, parent page request shape, read/write scope enforcement, successful health, invalid response handling, and status mappings for 401, 403, 429, and 5xx.

- [ ] **Step 2: Run focused tests and verify they fail**

  Run: `pytest apps/eeee/tests/plugins/test_notion_connector.py apps/eeee/tests/project_runtime/test_notion_documents.py -q`

  Expected: FAIL because the generic connector protocol and Notion adapter do not exist.

- [ ] **Step 3: Implement connector protocol and typed safe errors**

  Create immutable connector result/error contracts. Keep provider-specific token handling inside the adapter and never put the raw credential into a `PluginConnection`, `ExecutionEnvelope`, exception message, or audit payload.

- [ ] **Step 4: Implement `NotionConnector` around the existing `NotionClient`**

  Reuse the existing client methods and transport injection. Add only the adapter's scope checks and provider-neutral error classification; preserve current project-document tests and headers.

- [ ] **Step 5: Run focused tests and verify the error matrix**

  Run: `pytest apps/eeee/tests/plugins/test_notion_connector.py apps/eeee/tests/project_runtime/test_notion_documents.py -q`

  Expected: PASS with no token in failure strings or serialized outputs.

- [ ] **Step 6: Commit**

  ```bash
  git add apps/eeee/app/plugins/connectors.py apps/eeee/app/plugins/notion_connector.py apps/eeee/app/integrations/notion_client.py apps/eeee/tests/plugins/test_notion_connector.py apps/eeee/tests/project_runtime/test_notion_documents.py
  git commit -m "feat: add Notion plugin connector boundary"
  ```

### Task 4: Platform service and capability routing gate

**Files:**
- Create: `apps/eeee/app/plugins/platform.py`
- Modify: `apps/eeee/app/plugins/host.py`
- Modify: `apps/eeee/app/assistant/registry.py`
- Modify: `apps/eeee/app/assistant/router.py`
- Modify: `apps/eeee/app/kernel/service.py`
- Modify: `apps/eeee/app/main.py`
- Test: `apps/eeee/tests/plugins/test_platform.py`
- Test: `apps/eeee/tests/api/test_assistant_routes.py`

**Interfaces:**
- `PluginPlatformService.catalog() -> list[PluginCatalogEntry]`.
- `PluginPlatformService.install(plugin_id: str) -> PluginInstallationView` and `.uninstall(plugin_id: str) -> None`.
- `PluginPlatformService.connect(user_id: str, plugin_id: str, approved_permissions: set[str], credential: Mapping[str, str], account_label: str | None) -> PluginConnectionView`.
- `PluginPlatformService.disconnect(user_id: str, plugin_id: str) -> None`.
- `PluginPlatformService.health(user_id: str, plugin_id: str) -> ConnectorHealth`.
- `PluginPlatformService.capabilities(user_id: str = "local-user") -> list[CapabilityDescriptor]` returns only installed, connected, healthy capabilities.
- `PluginPlatformService.invoke(user_id: str, capability_id: str, value: dict[str, object]) -> ExecutionEnvelope` uses the same execution/audit boundary as local plugins.
- Existing `PluginHost` endpoints and echo fixture remain compatible; `CapabilityRegistry` uses a default local principal provider for current desktop routing while API requests pass explicit user scope to the platform service.

- [ ] **Step 1: Write failing platform and routing tests**

  Assert Notion is absent from routing before install, appears as `plugin:notion:pages` only after install/connect/healthy, disappears after disconnect or health failure, and never runs when paused or disconnected. Preserve existing local echo plugin routing tests. Assert a Notion request before connection returns `plugin_required` with a truthful install/connect action instead of a fake completion.

- [ ] **Step 2: Run focused tests and verify they fail**

  Run: `pytest apps/eeee/tests/plugins/test_platform.py apps/eeee/tests/api/test_assistant_routes.py -q`

  Expected: FAIL because the platform orchestration and connector capability projection are not wired into the kernel.

- [ ] **Step 3: Implement `PluginPlatformService`**

  Compose the catalog, installation store, connection service, connector registry, and execution store. Map connector lifecycle to safe capability descriptors and reuse `PluginHost` only for local manifest plugins. On provider health failure, set `failed`, hide the capability, and return a reconnectable blocked result.

- [ ] **Step 4: Wire the service into application startup and kernel routing**

  Create one platform service in `create_app`, register the Notion connector, expose it on application state, and make the dynamic capability provider use the local principal. Update optional plugin hints so the existing natural-language response distinguishes “설치 필요” from “계정 연결 필요” without claiming work was performed.

- [ ] **Step 5: Run focused and regression routing tests**

  Run: `pytest apps/eeee/tests/plugins/test_platform.py apps/eeee/tests/api/test_assistant_routes.py apps/eeee/tests/plugins/test_routes.py apps/eeee/tests/plugins/test_host.py -q`

  Expected: PASS; existing subprocess lifecycle tests and truthful assistant routing remain green.

- [ ] **Step 6: Commit**

  ```bash
  git add apps/eeee/app/plugins/platform.py apps/eeee/app/plugins/host.py apps/eeee/app/assistant/registry.py apps/eeee/app/assistant/router.py apps/eeee/app/kernel/service.py apps/eeee/app/main.py apps/eeee/tests/plugins/test_platform.py apps/eeee/tests/api/test_assistant_routes.py
  git commit -m "feat: gate assistant routing on plugin health"
  ```

### Task 5: User-scoped management API and redacted control-center contract

**Files:**
- Create: `apps/eeee/app/plugins/api_models.py`
- Modify: `apps/eeee/app/api/routes.py`
- Modify: `apps/eeee/app/main.py`
- Test: `apps/eeee/tests/plugins/test_platform_routes.py`
- Test: `apps/eeee/tests/api/test_desktop_routes.py`

**Interfaces:**
- Add `X-EEEE-User-Id` principal extraction for local API calls, defaulting only to `local-user` when the request is the local desktop. Reject malformed/remote user scope rather than silently switching users.
- Add `GET /api/plugins/catalog`.
- Add `POST /api/plugins/{plugin_id}/install` and `DELETE /api/plugins/{plugin_id}/install`.
- Add `GET /api/plugins/{plugin_id}/connection`.
- Add `POST /api/plugins/{plugin_id}/connect` with `approvedPermissions`, `credential`, and optional `accountLabel`; the response is a redacted connection view.
- Add `POST /api/plugins/{plugin_id}/disconnect`, `POST /api/plugins/{plugin_id}/pause`, `POST /api/plugins/{plugin_id}/resume`, and `GET /api/plugins/{plugin_id}/health` through the platform service.
- Preserve existing discover/register/invoke routes for local manifest plugins and avoid changing their response shapes unless adding non-sensitive lifecycle fields.
- Extend `/api/desktop/state` control-center plugin entries with catalog state, connection status, approved permissions, health, and next action; never include credential material.

- [ ] **Step 1: Write failing route and redaction tests**

  Test catalog default state, install/connect response, missing approval, missing connection, health endpoint, disconnect, user A/B isolation, malformed user id, and response/audit payloads containing no token. Test desktop state exposes actionable status rather than only a raw local registration list.

- [ ] **Step 2: Run focused tests and verify they fail**

  Run: `pytest apps/eeee/tests/plugins/test_platform_routes.py apps/eeee/tests/api/test_desktop_routes.py -q`

  Expected: FAIL because the management routes and principal boundary are not exposed.

- [ ] **Step 3: Implement API DTOs, principal extraction, and route mapping**

  Use `SecretStr` or an equivalent write-only credential input and construct the provider credential without serializing the request model. Convert lifecycle errors to 400/401/403/404/409/503 consistently, with safe provider-neutral detail messages.

- [ ] **Step 4: Add control-center projection**

  Have `build_desktop_router` consume the platform service and return catalog entries plus per-principal connection projections. Keep existing plugin registration entries so local echo plugins remain visible.

- [ ] **Step 5: Run focused and full API regression tests**

  Run: `pytest apps/eeee/tests/plugins/test_platform_routes.py apps/eeee/tests/api/test_desktop_routes.py apps/eeee/tests/plugins/test_routes.py -q`

  Expected: PASS with all credential redaction and local-only checks green.

- [ ] **Step 6: Commit**

  ```bash
  git add apps/eeee/app/plugins/api_models.py apps/eeee/app/api/routes.py apps/eeee/app/api/__init__.py apps/eeee/app/main.py apps/eeee/tests/plugins/test_platform_routes.py apps/eeee/tests/api/test_desktop_routes.py
  git commit -m "feat: expose user-scoped plugin management API"
  ```

### Task 6: Desktop plugin status surface

**Files:**
- Modify: `apps/eeee/app/static/index.html`
- Modify: `apps/eeee/app/static/app.js`
- Modify: `apps/eeee/app/static/styles.css`
- Modify: `apps/eeee/app/desktop/workspace.py`
- Test: `apps/eeee/tests/api/test_plugin_control_center.py`
- Test: `apps/eeee/tests/desktop/test_workspace.py`

**Interfaces:**
- The web control center renders catalog entries with `미설치`, `연결 필요`, `연결됨`, `일시정지`, or `오류` and a next-action label.
- The existing summary card remains compatible, but counts installed/connected optional plugins from the new projection rather than assuming every registration is a plugin connection.
- No raw credential or token is ever placed in DOM text, dataset attributes, or browser storage.

- [ ] **Step 1: Write failing DOM/projection tests**

  Assert the control-center fixture renders an uninstalled Notion entry, changes to “연결 필요” after install, and shows “연결됨” only after health succeeds. Assert desktop workspace text includes the actionable plugin count/status without regressing existing panels.

- [ ] **Step 2: Run focused tests and verify they fail**

  Run: `pytest apps/eeee/tests/api/test_plugin_control_center.py apps/eeee/tests/desktop/test_workspace.py -q`

  Expected: FAIL because the static surface currently only shows a connected/total count.

- [ ] **Step 3: Implement the minimal control-center UI**

  Add a plugin status list and action labels backed by `/api/desktop/state`/catalog data. Keep actions as explicit install/connect/pause/resume requests and show provider errors as user-readable next steps; do not add a marketplace or credential persistence in browser storage.

- [ ] **Step 4: Run focused UI contract tests**

  Run: `pytest apps/eeee/tests/api/test_plugin_control_center.py apps/eeee/tests/desktop/test_workspace.py -q`

  Expected: PASS and no sensitive strings in the rendered fixture payload.

- [ ] **Step 5: Commit**

  ```bash
  git add apps/eeee/app/static/index.html apps/eeee/app/static/app.js apps/eeee/app/static/styles.css apps/eeee/app/desktop/workspace.py apps/eeee/tests/api/test_plugin_control_center.py apps/eeee/tests/desktop/test_workspace.py
  git commit -m "feat: show plugin lifecycle in control center"
  ```

### Task 7: Full verification, packaged smoke test, and release review

**Files:**
- Modify only if verification exposes a defect: the affected source/test file from Tasks 1–6.
- Test: existing `apps/eeee/tests` suite and desktop packaging smoke-test inputs.

**Interfaces:**
- No new public interface; this task proves the completed platform contract across restart, routing, API, UI, and the existing local plugin boundary.

- [ ] **Step 1: Run focused plugin suite**

  Run: `pytest apps/eeee/tests/plugins apps/eeee/tests/api/test_assistant_routes.py apps/eeee/tests/api/test_desktop_routes.py -q`.

  Expected: PASS.

- [ ] **Step 2: Run the complete Python suite**

  Run: `pytest apps/eeee/tests -q`.

  Expected: PASS with no unrelated test collection failures.

- [ ] **Step 3: Run static/build checks**

  Run the repository's documented lint/type/build commands, then build the desktop artifact using the existing project command. Verify the artifact starts, serves `/health`, lists the optional catalog, and does not open a browser or require a credential until an explicit connect action.

- [ ] **Step 4: Perform restart and security smoke checks**

  Start the app with a temporary data directory, install/connect using a test Notion transport, stop/restart, verify status persistence, disconnect, verify capability removal, and search logs/database/API responses for the test token.

- [ ] **Step 5: Review the complete diff and commit any fixes separately**

  Run `git diff origin/main...HEAD --check`, inspect changed files for accidental asset/temp files, and create a small fix commit per defect rather than rewriting earlier task commits.

- [ ] **Step 6: Commit any verification fixes separately**

  ```bash
  git add <affected-source-or-test-files>
  git commit -m "fix: address plugin platform verification finding"
  ```
