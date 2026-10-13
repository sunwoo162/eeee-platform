const RUNS_PAGE_SIZE = 50;
const RECENT_RUN_FILTERS_STORAGE_KEY = "gleave.recent-run-filters";
const RECENT_RUN_STATUSES = new Set(["all", "created", "running", "completed", "failed", "unavailable"]);
const RECENT_RUN_PAGE_SIZES = new Set(["25", "50", "100"]);
const RECENT_RUN_SORTS = new Set(["newest", "oldest"]);
const state = { requestId: null, requestSelectionId: 0, runId: null, candidates: [], selectedCandidates: null, decisionEvents: [], runs: [], allRuns: [], approved: false, hasMoreRuns: false, hasLoadedRuns: false, loadingRuns: false, runsRequestId: 0, runsError: null, totalRuns: 0, runsUpdatedAt: null, runsPageSize: RUNS_PAGE_SIZE, runsSort: "newest" };
let projectMapProjectId = null;
let projectMapCursor = 0;
let projectMapTimer = null;
const pendingApprovalRequestIds = new Set();
const pendingResearchRequestIds = new Set();
const pendingRunExecutionIds = new Set();
let designReferenceRequestId = 0;
let visualVerificationRequestId = 0;

const $ = (selector) => document.querySelector(selector);

const LANGUAGE_STORAGE_KEY = "gleave.language";
const LANGUAGE_TEXT = {
  ko: {
    eyebrow: "로컬 우선 개발 워크스페이스",
    heroDescription: "EEEE가 상황에 맞는 도구를 선택해 아이디어를 검증된 실행으로 나눠 처리합니다.",
    language: "언어",
    requestHeading: "1. 만들고 싶은 것 설명",
    ready: "준비됨",
    requestLabel: "프로젝트 요청",
    requestPlaceholder: "예: 일정과 작업을 관리하는 웹 앱을 만들어줘",
    workspaceLabel: "설정된 로컬 루트 안의 워크스페이스",
    workspacePlaceholder: "선택 사항: C:\\...\\workspaces\\my-app",
    createRequest: "요청 만들기",
    workPlan: "작업 계획",
    approvalHistory: "승인 기록",
    restoreLabel: "저장된 요청 복원",
    requestId: "요청 ID",
    restore: "복원",
    researchHeading: "2. 오픈소스 후보 비교",
    research: "조사",
    candidateHeading: "후보 근거와 선택",
    candidateEmpty: "요청을 만들면 조사가 시작됩니다.",
    approve: "선택한 후보 승인",
    designHeading: "디자인 레퍼런스",
    provenance: "출처 우선",
    referenceUrl: "레퍼런스 URL",
    keywords: "키워드",
    keywordsPlaceholder: "대시보드, 사이드바, 카드",
    targetType: "대상 유형",
    collectPack: "레퍼런스 팩 수집",
    visualUrl: "시각 검증용 로컬 앱 URL",
    baseline: "기준 스크린샷 경로",
    verifyScreenshot: "로컬 스크린샷 검증",
    noVisualRun: "아직 시각 비교를 실행하지 않았습니다.",
    runHeading: "3. 실행과 검증",
    runApproved: "승인한 작업 실행",
    retryUnavailable: "실행할 수 없던 작업 재시도",
    recentRuns: "최근 실행",
    loadingRuns: "저장된 실행을 불러오는 중…",
    searchRuns: "요청 또는 실행 ID로 검색",
    searchIds: "ID 검색",
    filterStatus: "상태로 필터",
    allStatuses: "모든 상태",
    created: "생성됨",
    running: "실행 중",
    completed: "완료됨",
    failed: "실패",
    unavailable: "사용 불가",
    createdAfter: "생성 시작 시각(현지 시간)",
    createdBefore: "생성 종료 시각(현지 시간)",
    pageSize: "페이지당 실행 수",
    sortRuns: "실행 정렬",
    newest: "최신순",
    oldest: "오래된 순",
    refreshRuns: "실행 새로고침",
    clearFilters: "필터 초기화",
    runHistory: "실행 기록",
  },
  en: {
    eyebrow: "LOCAL-FIRST BUILD WORKBENCH",
    heroDescription: "EEEE chooses the right capability for the situation and turns ideas into verified execution.",
    language: "Language",
    requestHeading: "1. Describe the product",
    ready: "Ready",
    requestLabel: "Product request",
    requestPlaceholder: "Build a web app for...",
    workspaceLabel: "Workspace inside the configured local root",
    workspacePlaceholder: "Optional: C:\\...\\workspaces\\my-app",
    createRequest: "Create request",
    workPlan: "Work plan",
    approvalHistory: "Approval history",
    restoreLabel: "Restore saved request",
    requestId: "Request ID",
    restore: "Restore",
    researchHeading: "2. Compare OSS candidates",
    research: "Research",
    candidateHeading: "Candidate evidence and selection",
    candidateEmpty: "Create a request to begin research.",
    approve: "Approve selected candidates",
    designHeading: "Design references",
    provenance: "Provenance first",
    referenceUrl: "Reference URL",
    keywords: "Keywords",
    keywordsPlaceholder: "dashboard, sidebar, cards",
    targetType: "Target type",
    collectPack: "Collect reference pack",
    visualUrl: "Local app URL for visual verification",
    baseline: "Baseline screenshot path",
    verifyScreenshot: "Verify local screenshot",
    noVisualRun: "No visual comparison run yet.",
    runHeading: "3. Execute and verify",
    runApproved: "Run approved task",
    retryUnavailable: "Retry unavailable run",
    recentRuns: "Recent runs",
    loadingRuns: "Loading saved runs…",
    searchRuns: "Search by request or run ID",
    searchIds: "Search IDs",
    filterStatus: "Filter by status",
    allStatuses: "All statuses",
    created: "Created",
    running: "Running",
    completed: "Completed",
    failed: "Failed",
    unavailable: "Unavailable",
    createdAfter: "Created after (local time)",
    createdBefore: "Created before (local time)",
    pageSize: "Runs per page",
    sortRuns: "Sort runs",
    newest: "Newest first",
    oldest: "Oldest first",
    refreshRuns: "Refresh runs",
    clearFilters: "Clear filters",
    runHistory: "Run history",
  },
};

let currentLanguage = "ko";

function uiText(key) {
  return LANGUAGE_TEXT[currentLanguage][key] || LANGUAGE_TEXT.en[key] || key;
}

function applyLanguage(language) {
  currentLanguage = LANGUAGE_TEXT[language] ? language : "ko";
  if (document.documentElement) document.documentElement.lang = currentLanguage;
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, currentLanguage);
  } catch (_error) {
    // Language selection remains available when local storage is disabled.
  }
  const textTargets = {
    "#eyebrow": "eyebrow",
    ".hero > p:not(.eyebrow)": "heroDescription",
    "#language-label": "language",
    "#request-heading": "requestHeading",
    "#status": "ready",
    "label[for=request-text]": "requestLabel",
    "label[for=workspace]": "workspaceLabel",
    "#request-form button": "createRequest",
    "#work-plan-heading": "workPlan",
    "#approval-history-heading": "approvalHistory",
    "label[for=restore-request-id]": "restoreLabel",
    "#restore-form button": "restore",
    "#research-heading": "researchHeading",
    "#research-button": "research",
    "#candidate-selection-heading": "candidateHeading",
    "#candidates > .muted": "candidateEmpty",
    "#approve-button": "approve",
    "#design-heading": "designHeading",
    "#design-status": "provenance",
    "label[for=reference-url]": "referenceUrl",
    "label[for=reference-keywords]": "keywords",
    "label[for=reference-target]": "targetType",
    "#collect-reference-button": "collectPack",
    "label[for=visual-url]": "visualUrl",
    "label[for=visual-baseline]": "baseline",
    "#verify-visual-button": "verifyScreenshot",
    "#visual-status": "noVisualRun",
    "#run-heading": "runHeading",
    "#run-button": "runApproved",
    "#retry-button": "retryUnavailable",
    "#recent-runs-heading": "recentRuns",
    "#recent-runs-status": "loadingRuns",
    "label[for=recent-run-search]": "searchRuns",
    "label[for=recent-run-status-filter]": "filterStatus",
    "label[for=recent-run-created-after]": "createdAfter",
    "label[for=recent-run-created-before]": "createdBefore",
    "label[for=recent-run-page-size]": "pageSize",
    "label[for=recent-run-sort]": "sortRuns",
    "#refresh-recent-runs": "refreshRuns",
    "#clear-recent-run-filters": "clearFilters",
    "#run-history-heading": "runHistory",
  };
  for (const [selector, key] of Object.entries(textTargets)) {
    const element = $(selector);
    if (element) element.textContent = uiText(key);
  }
  $("#request-text").placeholder = uiText("requestPlaceholder");
  $("#workspace").placeholder = uiText("workspacePlaceholder");
  $("#restore-request-id").placeholder = uiText("requestId");
  $("#reference-keywords").placeholder = uiText("keywordsPlaceholder");
  $("#recent-run-search").placeholder = uiText("searchIds");
  $("#language-label").setAttribute("aria-label", uiText("language"));
  $("#language-select").value = currentLanguage;
  const statusOptions = {
    all: "allStatuses",
    created: "created",
    running: "running",
    completed: "completed",
    failed: "failed",
    unavailable: "unavailable",
  };
  for (const [value, key] of Object.entries(statusOptions)) {
    const option = $(`#recent-run-status-filter option[value=${value}]`);
    if (option) option.textContent = uiText(key);
  }
  $("#recent-run-sort option[value=newest]").textContent = uiText("newest");
  $("#recent-run-sort option[value=oldest]").textContent = uiText("oldest");
  const assistant = currentLanguage === "ko"
    ? {
        heading: "무엇을 해드릴까요?", status: "대기 중", label: "만들고 싶은 것을 한 문장으로 적어주세요",
        placeholder: "예: Todo 앱 만들어줘", button: "만들기", map: "프로젝트 진행 맵",
        project: ["프로젝트 만들기", "한 문장으로 앱을 만들고 진행 현황을 확인합니다."],
        secretary: ["일정·리마인더", "개인 일정과 다음 할 일을 정리합니다."],
        knowledge: ["기억·문서", "검증된 기록과 문서를 찾아 연결합니다."],
      }
    : {
        heading: "What should I do for you?", status: "Ready", label: "Describe what you want in one sentence",
        placeholder: "Example: Build a Todo app", button: "Build", map: "Project progress map",
        project: ["Build a project", "Create an app from one sentence and follow its progress."],
        secretary: ["Schedule & reminders", "Organize personal events and next actions."],
        knowledge: ["Memory & documents", "Find and connect verified records and documents."],
      };
  const assistantHeading = $("#assistant-heading");
  if (assistantHeading) assistantHeading.textContent = assistant.heading;
  const assistantStatus = $("#assistant-status");
  if (assistantStatus) assistantStatus.textContent = assistant.status;
  const requestLabel = $("label[for=project-request]");
  if (requestLabel) requestLabel.textContent = assistant.label;
  const projectInput = $("#project-request");
  if (projectInput) projectInput.placeholder = assistant.placeholder;
  const projectButton = $("#project-request-form button");
  if (projectButton) projectButton.textContent = assistant.button;
  const mapHeading = $("#project-map-heading");
  if (mapHeading) mapHeading.textContent = assistant.map;
  const cards = document.querySelectorAll(".capability-card");
  [assistant.project, assistant.secretary, assistant.knowledge].forEach((copy, index) => {
    const card = cards[index];
    if (!card) return;
    const strong = card.querySelector("strong");
    const description = card.querySelector("span");
    if (strong) strong.textContent = copy[0];
    if (description) description.textContent = copy[1];
  });
}

function initializeLanguage() {
  const search = typeof window !== "undefined" && typeof window.location?.search === "string"
    ? window.location.search
    : "";
  const queryLanguage = search.match(/[?&]lang=(ko|en)(?:&|$)/)?.[1];
  let savedLanguage = "ko";
  try {
    savedLanguage = localStorage.getItem(LANGUAGE_STORAGE_KEY) || "ko";
  } catch (_error) {
    // Korean is the deterministic default.
  }
  applyLanguage(LANGUAGE_TEXT[queryLanguage] ? queryLanguage : savedLanguage);
  $("#language-select").addEventListener("change", (event) => {
    applyLanguage(event.target.value);
  });
}

initializeLanguage();

async function refreshEeeeControlCenter() {
  const status = $("#eeee-control-status");
  if (!status) return;
  try {
    const snapshot = await requestJson("/api/desktop/state");
    const control = snapshot.controlCenter || {};
    const jobs = Array.isArray(control.jobs) ? control.jobs : [];
    const memory = control.memory || {};
    const plugins = Array.isArray(control.plugins) ? control.plugins : [];
    const activeJobs = jobs.filter((job) => ["queued", "running", "paused"].includes(job.status)).length;
    const connectedPlugins = plugins.filter((plugin) => plugin.status === "connected").length;
    $("#eeee-active-work").textContent = `${activeJobs}개 작업`;
    $("#eeee-memory-summary").textContent = `활성 ${memory.activeCount || 0}개 · 검토 대기 ${memory.candidateCount || 0}개`;
    $("#eeee-plugin-summary").textContent = `${connectedPlugins}/${plugins.length}개 연결`;
    renderEeeePluginStatus(plugins);
    $("#eeee-verification-summary").textContent = control.verification?.claimLatch?.status || "확인 필요";
    status.textContent = "연결됨";
    status.className = "status success";
  } catch (error) {
    status.textContent = error?.detail || "제어 센터 연결 대기";
    status.className = "status";
  }
}

function renderEeeePluginStatus(plugins) {
  const stateList = $("#eeee-plugin-list");
  const installedList = $("#eeee-installed-plugin-list");
  const availableList = $("#eeee-available-plugin-list");
  const search = $("#eeee-plugin-search");
  const lists = [installedList, availableList].filter(Boolean);
  if (!stateList || !lists.length) return;
  stateList.__eeeePlugins = plugins;
  const surface = lists[0].closest(".eeee-plugin-status") || stateList;
  if (!surface.dataset.bound) {
    surface.dataset.bound = "true";
    surface.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-plugin-id]");
      if (!button) return;
      const plugin = (stateList.__eeeePlugins || []).find((item) => item.pluginId === button.dataset.pluginId);
      if (!plugin) return;
      button.disabled = true;
      try {
        if (plugin.nextAction === "install") {
          await requestJson(`/api/plugins/${encodeURIComponent(plugin.pluginId)}/install`, { method: "POST" });
        } else if (["connect", "reconnect"].includes(plugin.nextAction)) {
          const popup = typeof window !== "undefined" && typeof window.open === "function"
            ? window.open("about:blank", "_blank", "noopener,noreferrer")
            : null;
          const result = await requestJson(`/api/plugins/${encodeURIComponent(plugin.pluginId)}/oauth/start`, {
            method: "POST",
            body: JSON.stringify({ approvedPermissions: plugin.permissions || [] }),
          });
          if (popup) popup.location.href = result.authorizationUrl;
          else if (typeof window !== "undefined") window.location.href = result.authorizationUrl;
        } else if (plugin.nextAction === "resume") {
          await requestJson(`/api/plugins/${encodeURIComponent(plugin.pluginId)}/resume`, { method: "POST" });
        }
        await refreshEeeeControlCenter();
      } catch (error) {
        const status = $("#eeee-control-status");
        status.textContent = error?.detail || "플러그인 연결에 실패했습니다.";
        status.className = "status error";
      } finally {
        button.disabled = false;
      }
    });
  }
  if (search && !search.dataset.bound) {
    search.dataset.bound = "true";
    search.addEventListener("input", () => renderEeeePluginStatus(stateList.__eeeePlugins || []));
  }
  lists.forEach((list) => list.replaceChildren());
  const query = (search?.value || "").trim().toLocaleLowerCase();
  const visible = plugins.filter((plugin) => {
    if (!query) return true;
    return [plugin.name, plugin.description, plugin.pluginId]
      .filter(Boolean)
      .some((value) => String(value).toLocaleLowerCase().includes(query));
  });
  const labels = {
    not_installed: "미설치",
    installed: "설치됨 · 연결 설정 필요",
    available: "연결 필요",
    awaiting_authentication: "연결 필요",
    connecting: "연결 중",
    connected: "연결됨",
    paused: "일시정지",
    failed: "오류",
    disabled: "설정 필요",
  };
  const nextActionLabels = { install: "설치", connect: "연결", reconnect: "다시 연결", resume: "재개" };
  const renderEmpty = (list, message) => {
    const empty = document.createElement("li");
    empty.className = "muted";
    empty.textContent = message;
    list.append(empty);
  };
  if (!visible.length) {
    renderEmpty(availableList, query ? "검색 결과가 없습니다." : "설치 가능한 플러그인이 없습니다.");
    return;
  }
  for (const plugin of visible) {
    const item = document.createElement("li");
    item.className = "eeee-plugin-item";
    const details = document.createElement("div");
    details.className = "eeee-plugin-details";
    const name = document.createElement("strong");
    name.textContent = plugin.name || plugin.pluginId || "플러그인";
    const description = document.createElement("span");
    description.className = "eeee-plugin-description";
    description.textContent = plugin.description || "설치 가능한 EEEE 플러그인";
    details.append(name, description);
    const status = document.createElement("span");
    status.className = `plugin-status plugin-status-${plugin.status || "unknown"}`;
    status.textContent = labels[plugin.status] || plugin.status || "확인 필요";
    if (nextActionLabels[plugin.nextAction]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "plugin-action";
      button.dataset.pluginId = plugin.pluginId || "";
      button.textContent = nextActionLabels[plugin.nextAction];
      item.append(details, status, button);
    } else {
      const action = document.createElement("span");
      action.className = "plugin-next-action";
      action.textContent = plugin.nextAction === "configure" ? "연결 설정 준비 중" : "";
      item.append(details, status, action);
    }
    (plugin.status === "not_installed" ? availableList : installedList).append(item);
  }
  if (!installedList.children.length) renderEmpty(installedList, "아직 설치된 플러그인이 없습니다.");
  if (!availableList.children.length) renderEmpty(availableList, "모든 플러그인이 설치되어 있습니다.");
}

refreshEeeeControlCenter();
if (typeof setInterval === "function") {
  setInterval(refreshEeeeControlCenter, 3000);
}

function setStatus(message, kind = "") {
  const status = $("#status");
  status.textContent = message;
  status.className = `status ${kind}`.trim();
}

function beginRequestSelection() {
  const selectionId = ++state.requestSelectionId;
  if ($("#restore-status").textContent === "Restoring…") {
    $("#restore-status").textContent = "Selection changed";
  }
  if ($("#recent-runs-status").textContent === "Loading selected run…") {
    $("#recent-runs-status").textContent = "Selection changed";
  }
  if ($("#status").textContent === "Creating request…") {
    setStatus("Selection changed");
  }
  return selectionId;
}

function showError(error) {
  const message = error?.detail || error?.message || "Request failed";
  setStatus(message, "error");
  $("#run-summary").textContent = message;
}

function syncResearchButton() {
  const pending = Boolean(state.requestId && pendingResearchRequestIds.has(state.requestId));
  $("#research-button").disabled = state.approved || pending;
  $("#candidates").setAttribute("aria-busy", String(pending));
}

function syncRunButton(run = state.runs.find((item) => item.id === state.runId)) {
  $("#run-button").disabled = !state.approved
    || !run
    || pendingRunExecutionIds.has(state.runId)
    || !["created", "running"].includes(run.status);
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json();
  if (!response.ok) throw body;
  return body;
}

function renderProjectMapDetails(node) {
  const details = $("#project-map-details");
  details.replaceChildren();
  if (!node) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "작업 노드를 선택하면 커밋, QA, ClaimLatch, 파일과 문제 해결 기록이 표시됩니다.";
    details.append(empty);
    return;
  }
  const title = document.createElement("h3");
  title.textContent = node.title;
  const status = document.createElement("p");
  status.className = `map-detail-status ${node.status}`;
  status.textContent = `${node.role} · ${node.status}`;
  const facts = document.createElement("dl");
  const fields = [
    ["설명", node.reason || "기록 없음"],
    ["선택 이유", node.selectedBecause || "기록 없음"],
    ["검토한 대안", (node.alternatives || []).join(", ") || "기록 없음"],
    ["현재 커밋", node.currentCommit || "기록 없음"],
    ["변경 파일", (node.changedFiles || []).join(", ") || "기록 없음"],
    ["ClaimLatch", node.claimLatchStatus || "unavailable"],
    ["QA", node.qaStatus || "unavailable"],
    ["차단 사유", (node.trustBlockers || []).join(", ") || "없음"],
    ["증거", (node.evidenceIds || []).join(", ") || "기록 없음"],
    ["트러블슈팅", (node.troubleshootingIds || []).join(", ") || "기록 없음"],
  ];
  fields.forEach(([label, value]) => {
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = value;
    facts.append(term, description);
  });
  details.append(title, status, facts);
}

function renderProjectMap(snapshot) {
  projectMapCursor = snapshot.cursor || 0;
  const container = $("#project-map-nodes");
  const active = new Set(snapshot.currentNodeIds || []);
  const incoming = new Map();
  (snapshot.edges || []).forEach((edge) => {
    if (!incoming.has(edge.target)) incoming.set(edge.target, []);
    incoming.get(edge.target).push(edge);
  });
  container.replaceChildren();
  (snapshot.nodes || []).forEach((node) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `project-map-node ${node.status}${active.has(node.id) ? " active" : ""}`;
    card.dataset.group = node.group || "execution";
    card.dataset.nodeId = node.id;
    card.dataset.claimlatch = node.claimLatchStatus || "unavailable";
    card.dataset.qa = node.qaStatus || "unavailable";
    const heading = document.createElement("strong");
    heading.textContent = node.title;
    const meta = document.createElement("span");
    const parents = (incoming.get(node.id) || [])
      .filter((edge) => edge.kind === "dependency")
      .map((edge) => edge.source.replace(/^agent:/, ""));
    meta.textContent = `${node.role} · ${node.status}${parents.length ? ` · ← ${parents.join(", ")}` : ""}`;
    card.append(heading, meta);
    card.addEventListener("click", () => renderProjectMapDetails(node));
    container.append(card);
  });
  $("#project-map-summary").textContent = `${snapshot.title} · revision ${snapshot.projectRevision} · ${snapshot.nodes.length}개 작업 · cursor ${projectMapCursor}`;
  $("#project-map-status").textContent = snapshot.warnings?.length
    ? `확인 필요: ${snapshot.warnings.join("; ")}`
    : "실시간 기록 반영됨";
  if (active.size) renderProjectMapDetails((snapshot.nodes || []).find((node) => active.has(node.id)));
}

async function refresh_project_map(projectId) {
  if (!projectId || projectId !== projectMapProjectId) return;
  try {
    const snapshot = await requestJson(`/api/projects/${projectId}/map`);
    if (projectId !== projectMapProjectId) return;
    renderProjectMap(snapshot);
  } catch (error) {
    $("#project-map-status").textContent = error?.detail || "프로젝트 맵을 불러오지 못했습니다.";
  }
}

function open_project(projectId) {
  projectMapProjectId = projectId;
  projectMapCursor = 0;
  $("#project-map").hidden = false;
  $("#project-map").scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const url = new URL(window.location.href);
    url.searchParams.set("project", projectId);
    window.history.replaceState({}, "", url);
  } catch (_error) {
    // The project remains open even when the browser history API is unavailable.
  }
  refresh_project_map(projectId);
  if (projectMapTimer) clearInterval(projectMapTimer);
  projectMapTimer = setInterval(() => refresh_project_map(projectId), 1500);
}

function renderCandidates() {
  const container = $("#candidates");
  container.replaceChildren();
  syncResearchButton();
  $("#approve-button").disabled = true;
  if (!state.candidates.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No candidate evidence yet.";
    container.append(empty);
    return;
  }
  state.candidates.forEach((candidate, index) => {
    const repository = candidate.repository;
    const card = document.createElement("label");
    card.className = "candidate-card";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = repository.full_name;
    checkbox.checked = state.selectedCandidates === null
      ? index === 0
      : state.selectedCandidates.includes(repository.full_name);
    checkbox.disabled = state.approved;
    checkbox.addEventListener("change", () => {
      state.selectedCandidates = [...document.querySelectorAll("#candidates input:checked")]
        .map((input) => input.value);
    });
    const title = document.createElement("strong");
    title.textContent = candidate.repository.full_name;
    const description = document.createElement("span");
    description.textContent = repository.description || "No description";
    const metadata = document.createElement("small");
    metadata.className = "candidate-metadata";
    metadata.textContent = `License ${repository.license_spdx || "unknown"} · ${repository.stars.toLocaleString()} stars · ${repository.forks.toLocaleString()} forks · Last push ${formatRunTime(repository.pushed_at)}`;
    const dimensionScores = document.createElement("small");
    dimensionScores.className = "candidate-dimensions";
    dimensionScores.textContent = Object.entries(candidate.dimension_scores)
      .map(([dimension, score]) => `${dimension}: ${score}`)
      .join(" · ") || "No score breakdown";
    const evidence = document.createElement("small");
    evidence.textContent = `Score ${candidate.total} · ${candidate.evidence.join("; ")}`;
    const risks = document.createElement("small");
    risks.className = "candidate-risks";
    risks.textContent = candidate.risks.length ? `Risks: ${candidate.risks.join("; ")}` : "Risks: none reported";
    card.append(checkbox, title, description, metadata, dimensionScores, evidence, risks);
    container.append(card);
  });
  $("#approve-button").disabled = state.approved || pendingApprovalRequestIds.has(state.requestId);
}

function renderRun(run) {
  if (!run) {
    $("#run-summary").textContent = "No saved runs for this request yet.";
    $("#events").replaceChildren();
    $("#changed-files").replaceChildren();
    $("#test-commands").replaceChildren();
    $("#run-artifacts").replaceChildren();
    $("#retry-button").disabled = true;
    $("#run-button").disabled = true;
    return;
  }
  const artifacts = run.artifacts || [];
  const resultArtifact = artifacts.find((artifact) => artifact.type === "agent_result")
    || artifacts.find((artifact) => artifact.summary || artifact.changed_files || artifact.test_commands)
    || {};
  const summary = run.error || resultArtifact.summary || "No summary";
  $("#run-summary").textContent = run.status === "unavailable"
    ? `Runtime unavailable: ${summary}. Configure LLM_API_KEY and LLM_MODEL.`
    : `${run.status}: ${summary}`;
  $("#events").replaceChildren(...run.events.map((event) => {
    const item = document.createElement("li");
    item.textContent = JSON.stringify(event);
    return item;
  }));
  const changedFiles = resultArtifact.changed_files || [];
  $("#changed-files").replaceChildren(...changedFiles.map((file) => {
    const item = document.createElement("li");
    item.textContent = file;
    return item;
  }));
  const testCommands = resultArtifact.test_commands || [];
  $("#test-commands").replaceChildren(...testCommands.map((command) => {
    const item = document.createElement("li");
    item.textContent = command;
    return item;
  }));
  const artifactPaths = (run.artifacts || [])
    .map((artifact) => artifact.path)
    .filter(Boolean);
  $("#run-artifacts").replaceChildren(...artifactPaths.map((path) => {
    const item = document.createElement("li");
    item.textContent = path;
    return item;
  }));
  $("#retry-button").disabled = !["failed", "unavailable"].includes(run.status);
  syncRunButton(run);
}

function backgroundRunStatus(runId) {
  return `Run ${runId.slice(0, 8)} continues in background`;
}

function setSelectedRun(runId) {
  if (state.runId && state.runId !== runId && $("#status").textContent === "Running…") {
    setStatus(backgroundRunStatus(state.runId), "busy");
  }
  state.runId = runId;
  document.querySelectorAll(".run-history-item[data-run-id]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.runId === runId));
  });
}

function renderRunHistory(runs) {
  const history = $("#run-history");
  history.replaceChildren();
  if (!runs.length) {
    const empty = document.createElement("li");
    empty.className = "muted";
    empty.textContent = "No saved runs yet.";
    history.append(empty);
    return;
  }
  [...runs].reverse().forEach((run) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "run-history-item";
    button.dataset.runId = run.id;
    button.setAttribute("aria-pressed", String(run.id === state.runId));
    button.title = `Created ${formatRunTime(run.created_at)}`;
    button.textContent = `${run.status} · ${formatRunTime(run.created_at)} · ${run.id.slice(0, 8)}`;
    button.addEventListener("click", () => {
      beginRequestSelection();
      setSelectedRun(run.id);
      renderRun(run);
    });
    item.append(button);
    history.append(item);
  });
}

function renderRecentRuns() {
  const list = $("#recent-runs");
  list.replaceChildren();
  const filteredRuns = state.allRuns;
  const loadedRuns = filteredRuns.length;
  const runsRange = `Showing ${loadedRuns ? `1–${loadedRuns}` : "0"} of ${state.totalRuns} matching runs`;
  const refreshedAt = state.runsUpdatedAt ? ` · Updated ${formatRunTime(state.runsUpdatedAt)}` : "";
  $("#recent-runs-status").textContent = state.runsError && loadedRuns
    ? `${runsRange} · ${state.runsError}${refreshedAt}`
    : state.runsError || (state.loadingRuns && !loadedRuns
      ? "Loading runs…"
      : `${runsRange}${state.loadingRuns ? " · Loading more…" : ""}${refreshedAt}`);
  $("#load-more-runs").hidden = !state.hasMoreRuns;
  $("#load-more-runs").disabled = state.loadingRuns;
  $("#refresh-recent-runs").disabled = state.loadingRuns;
  $("#recent-run-page-size").disabled = state.loadingRuns;
  $("#recent-run-sort").disabled = state.loadingRuns;
  if (!filteredRuns.length) {
    if (!state.hasLoadedRuns || state.loadingRuns) return;
    const empty = document.createElement("li");
    empty.className = "muted";
    const hasFilters = $("#recent-run-search").value.trim()
      || $("#recent-run-status-filter").value !== "all"
      || $("#recent-run-created-after").value
      || $("#recent-run-created-before").value;
    empty.textContent = hasFilters ? "No runs match the current filters (0 total)." : "No saved runs yet.";
    list.append(empty);
    return;
  }
  filteredRuns.forEach((run) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "run-history-item";
    button.dataset.runId = run.id;
    button.setAttribute("aria-pressed", String(run.id === state.runId));
    button.textContent = `${run.status} · ${formatRunTime(run.created_at)} · request ${run.request_id.slice(0, 8)} · run ${run.id.slice(0, 8)}`;
    button.addEventListener("click", () => openRecentRun(run));
    item.append(button);
    list.append(item);
  });
}

function formatRunTime(value) {
  if (!value) return "Time unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Time unavailable" : date.toLocaleString();
}

function normaliseRecentRunPageSize(value) {
  const pageSizeText = typeof value === "string"
    ? value
    : Number.isInteger(value) ? String(value) : "";
  return RECENT_RUN_PAGE_SIZES.has(pageSizeText) ? Number(pageSizeText) : RUNS_PAGE_SIZE;
}

function normaliseRecentRunSort(value) {
  return RECENT_RUN_SORTS.has(value) ? value : "newest";
}

function readRecentRunFilters() {
  try {
    const saved = JSON.parse(localStorage.getItem(RECENT_RUN_FILTERS_STORAGE_KEY) || "null");
    if (!saved || typeof saved !== "object") return {};
    return {
      search: typeof saved.search === "string" ? saved.search : "",
      status: RECENT_RUN_STATUSES.has(saved.status) ? saved.status : "all",
      createdAfter: typeof saved.createdAfter === "string" ? saved.createdAfter : "",
      createdBefore: typeof saved.createdBefore === "string" ? saved.createdBefore : "",
      pageSize: normaliseRecentRunPageSize(saved.pageSize),
      sort: normaliseRecentRunSort(saved.sort),
    };
  } catch (_error) {
    return {};
  }
}

function saveRecentRunFilters() {
  try {
    state.runsPageSize = normaliseRecentRunPageSize($("#recent-run-page-size").value);
    state.runsSort = normaliseRecentRunSort($("#recent-run-sort").value);
    localStorage.setItem(RECENT_RUN_FILTERS_STORAGE_KEY, JSON.stringify({
      search: $("#recent-run-search").value,
      status: $("#recent-run-status-filter").value,
      createdAfter: $("#recent-run-created-after").value,
      createdBefore: $("#recent-run-created-before").value,
      pageSize: $("#recent-run-page-size").value,
      sort: $("#recent-run-sort").value,
    }));
  } catch (_error) {
    // Local storage is an optional convenience; filtering remains usable.
  }
}

function restoreRecentRunFilters() {
  const filters = readRecentRunFilters();
  $("#recent-run-search").value = filters.search || "";
  $("#recent-run-status-filter").value = filters.status || "all";
  $("#recent-run-created-after").value = filters.createdAfter || "";
  $("#recent-run-created-before").value = filters.createdBefore || "";
  state.runsPageSize = filters.pageSize || RUNS_PAGE_SIZE;
  $("#recent-run-page-size").value = String(state.runsPageSize);
  state.runsSort = filters.sort || "newest";
  $("#recent-run-sort").value = state.runsSort;
}

function clearStoredRecentRunFilters() {
  try {
    localStorage.removeItem(RECENT_RUN_FILTERS_STORAGE_KEY);
  } catch (_error) {
    // Local storage is an optional convenience; filtering remains usable.
  }
}

function refreshRecentRunsForFilterChange() {
  clearTimeout(recentRunsSearchTimer);
  saveRecentRunFilters();
  refreshRecentRuns();
}

async function refreshRecentRuns() {
  const requestId = state.runsRequestId + 1;
  state.runsRequestId = requestId;
  state.allRuns = [];
  state.hasMoreRuns = false;
  state.hasLoadedRuns = false;
  state.loadingRuns = false;
  state.runsError = null;
  state.totalRuns = 0;
  state.runsUpdatedAt = null;
  renderRecentRuns();
  await loadMoreRecentRuns(requestId);
}

async function loadMoreRecentRuns(requestId = state.runsRequestId) {
  if (state.loadingRuns || requestId !== state.runsRequestId) return;
  state.runsError = null;
  state.loadingRuns = true;
  renderRecentRuns();
  try {
    const offset = state.allRuns.length;
    const params = new URLSearchParams({ limit: String(state.runsPageSize), offset: String(offset) });
    const sort = state.runsSort;
    const search = $("#recent-run-search").value.trim();
    const status = $("#recent-run-status-filter").value;
    const createdAfter = $("#recent-run-created-after").value;
    const createdBefore = $("#recent-run-created-before").value;
    if (search) params.set("search", search);
    if (status !== "all") params.set("status", status);
    params.set("sort", sort);
    setRunTimeFilter(params, "created_after", createdAfter);
    setRunTimeFilter(params, "created_before", createdBefore);
    const response = await fetch(`/api/runs?${params}`);
    const page = await response.json();
    if (!response.ok) throw page;
    if (requestId !== state.runsRequestId) return;
    state.allRuns.push(...page);
    state.hasMoreRuns = response.headers.get("X-Has-More") === "true";
    state.totalRuns = Number(response.headers.get("X-Total-Count") || state.allRuns.length);
    state.hasLoadedRuns = true;
    state.runsUpdatedAt = new Date().toISOString();
    state.runsError = null;
  } catch (error) {
    if (requestId === state.runsRequestId) {
      state.runsError = error?.detail || "Could not load more runs";
    }
  } finally {
    if (requestId === state.runsRequestId) {
      state.loadingRuns = false;
      renderRecentRuns();
    }
  }
}

function setRunTimeFilter(params, name, value) {
  if (!value) return;
  const timestamp = new Date(value);
  if (!Number.isNaN(timestamp.getTime())) params.set(name, timestamp.toISOString());
}

function clearRunHistoryFilters() {
  clearTimeout(recentRunsSearchTimer);
  clearStoredRecentRunFilters();
  $("#recent-run-search").value = "";
  $("#recent-run-status-filter").value = "all";
  $("#recent-run-created-after").value = "";
  $("#recent-run-created-before").value = "";
  state.runsPageSize = RUNS_PAGE_SIZE;
  $("#recent-run-page-size").value = String(RUNS_PAGE_SIZE);
  state.runsSort = "newest";
  $("#recent-run-sort").value = state.runsSort;
  refreshRecentRuns();
}

async function openRecentRun(run) {
  const selectionId = beginRequestSelection();
  try {
    $("#recent-runs-status").textContent = "Loading selected run…";
    if (state.requestId !== run.request_id) {
      const snapshot = await requestJson(`/api/requests/${run.request_id}`);
      if (state.requestSelectionId !== selectionId) return;
      applySnapshot(snapshot);
    }
    setSelectedRun(run.id);
    renderRun(run);
    $("#recent-runs-status").textContent = `Showing run ${run.id.slice(0, 8)} from request ${run.request_id.slice(0, 8)}`;
    setStatus("Run restored", "success");
  } catch (error) {
    if (state.requestSelectionId !== selectionId) return;
    $("#recent-runs-status").textContent = error?.detail || "Could not restore selected run";
  }
}

function renderDecisionEvents(events) {
  $("#decision-events").replaceChildren(...events.map((event) => {
    const item = document.createElement("li");
    const selected = Array.isArray(event.selected) ? ` (${event.selected.join(", ")})` : "";
    item.textContent = `${event.action || "event"}${selected}`;
    return item;
  }));
}

function renderSnapshotEvidence(snapshot) {
  const plan = snapshot?.work_plan?.steps || [];
  $("#work-plan").replaceChildren(...plan.map((step) => {
    const item = document.createElement("li");
    item.textContent = `${step.title}: ${step.description}`;
    return item;
  }));
  renderDecisionEvents(snapshot?.decision_events || []);
}

function rememberRequest(requestId) {
  try {
    localStorage.setItem("gleave.request-id", requestId);
  } catch (_error) {
    // Local storage is an optional convenience; the API flow remains usable.
  }
}

function forgetRequest(requestId) {
  try {
    if (!requestId || localStorage.getItem("gleave.request-id") === requestId) {
      localStorage.removeItem("gleave.request-id");
    }
  } catch (_error) {
    // Local storage is an optional convenience; the API flow remains usable.
  }
}

async function restoreRequest(requestId, quiet = false) {
  const selectionId = beginRequestSelection();
  try {
    if (!quiet) $("#restore-status").textContent = "Restoring…";
    const snapshot = await requestJson(`/api/requests/${requestId}`);
    if (state.requestSelectionId !== selectionId) return false;
    if (quiet && state.requestId && state.requestId !== requestId) return false;
    applySnapshot(snapshot);
    $("#restore-status").textContent = quiet ? "Saved request restored" : "Request restored";
    setStatus(quiet ? "Saved request restored" : "Request restored", "success");
    return true;
  } catch (error) {
    if (state.requestSelectionId !== selectionId) return false;
    if (quiet) {
      if (String(error?.detail || "").toLowerCase().includes("request not found")) {
        forgetRequest(requestId);
        $("#restore-request-id").value = "";
      }
      return false;
    }
    $("#restore-status").textContent = error?.detail || "Request restore failed";
    return false;
  }
}

function applySnapshot(snapshot) {
  state.requestId = snapshot.request_id;
  state.candidates = snapshot.candidates || [];
  state.selectedCandidates = snapshot.decision ? snapshot.decision.selected : null;
  state.decisionEvents = snapshot.decision_events || [];
  state.runs = snapshot.runs || [];
  state.approved = snapshot.decision?.approved === true;
  setSelectedRun(state.runs.at(-1)?.id || null);
  $("#restore-request-id").value = state.requestId;
  $("#request-text").value = snapshot.brief.raw_text;
  $("#workspace").value = snapshot.workspace;
  $("#brief").textContent = `${snapshot.brief.goal} · ${snapshot.brief.target_type}`;
  renderCandidates();
  renderSnapshotEvidence(snapshot);
  renderRunHistory(state.runs);
  syncResearchButton();
  renderRun(state.runs.at(-1));
  rememberRequest(state.requestId);
}

document.querySelectorAll(".capability-card").forEach((card) => {
  card.addEventListener("click", () => {
    document.querySelectorAll(".capability-card").forEach((item) => item.classList.remove("selected"));
    card.classList.add("selected");
    $("#project-request").focus();
  });
});

$("#project-request-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = $("#project-request").value.trim();
  if (!text) return;
  const status = $("#assistant-status");
  const requestStatus = $("#project-request-status");
  status.textContent = "분석 중";
  status.className = "status busy";
  requestStatus.textContent = "EEEE가 프로젝트 도구를 준비하고 있습니다…";
  try {
    const result = await requestJson("/api/assistant/route", {
      method: "POST",
      body: JSON.stringify({ text, workspace: $("#project-workspace").value || null }),
    });
    if (result.project_id) {
      requestStatus.textContent = `${result.message} · ${result.project_id}`;
      status.textContent = "프로젝트 생성됨";
      status.className = "status success";
      open_project(result.project_id);
    } else {
      requestStatus.textContent = result.message || "추가 확인이 필요합니다.";
      status.textContent = result.status || "확인 필요";
      status.className = "status";
    }
  } catch (error) {
    const message = error?.detail || error?.message || "프로젝트 요청에 실패했습니다.";
    status.textContent = "실패";
    status.className = "status error";
    requestStatus.textContent = message;
  }
});

$("#request-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const selectionId = beginRequestSelection();
  try {
    setStatus("Creating request…", "busy");
    const body = {
      text: $("#request-text").value,
      workspace: $("#workspace").value || null,
    };
    const created = await requestJson("/api/requests", {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (state.requestSelectionId !== selectionId) return;
    state.requestId = created.request_id;
    setSelectedRun(created.run_id);
    state.approved = false;
    state.candidates = [];
    state.selectedCandidates = null;
    state.decisionEvents = [];
    state.runs = [];
    rememberRequest(state.requestId);
    $("#brief").textContent = `${created.brief.goal} · ${created.brief.target_type}`;
    renderCandidates();
    renderSnapshotEvidence(null);
    renderRunHistory(state.runs);
    renderRun(null);
    refreshRecentRuns();
    $("#research-button").disabled = false;
    setStatus("Request created", "success");
  } catch (error) {
    if (state.requestSelectionId === selectionId) showError(error);
  }
});

$("#research-button").addEventListener("click", async () => {
  const requestId = state.requestId;
  if (!requestId || pendingResearchRequestIds.has(requestId)) return;
  pendingResearchRequestIds.add(requestId);
  syncResearchButton();
  try {
    setStatus("Researching…", "busy");
    const result = await requestJson(`/api/requests/${requestId}/research`, { method: "POST" });
    if (state.requestId !== requestId) return;
    state.candidates = result.candidates;
    if (!state.approved) state.selectedCandidates = null;
    renderCandidates();
    renderSnapshotEvidence({
      work_plan: result.work_plan,
      decision_events: state.approved ? state.decisionEvents : [],
    });
    setStatus(`${state.candidates.length} candidates compared`, "success");
  } catch (error) {
    if (state.requestId === requestId) showError(error);
  } finally {
    pendingResearchRequestIds.delete(requestId);
    syncResearchButton();
  }
});

$("#approve-button").addEventListener("click", async () => {
  const requestId = state.requestId;
  const selectionId = state.requestSelectionId;
  if (!requestId || pendingApprovalRequestIds.has(requestId)) return;
  pendingApprovalRequestIds.add(requestId);
  $("#approve-button").disabled = true;
  try {
    const selected = [...document.querySelectorAll("#candidates input:checked")].map((input) => input.value);
    state.selectedCandidates = selected;
    const result = await requestJson(`/api/requests/${requestId}/approve`, {
      method: "POST",
      body: JSON.stringify({ selected }),
    });
    if (state.requestId !== requestId) return;
    const preserveRunSelection = state.requestSelectionId !== selectionId;
    state.approved = result.decision.approved;
    state.selectedCandidates = result.decision.selected;
    state.decisionEvents = result.decision_events || [];
    if (!preserveRunSelection) setSelectedRun(result.run_id);
    renderCandidates();
    renderDecisionEvents(state.decisionEvents);
    $("#research-button").disabled = state.approved;
    $("#run-button").disabled = !state.approved;
    if (!preserveRunSelection) {
      $("#run-summary").textContent = "Selection approved. Execution is ready.";
    }
    const snapshot = await requestJson(`/api/requests/${requestId}`);
    if (state.requestId !== requestId) return;
    const selectedRunId = state.requestSelectionId !== selectionId ? state.runId : result.run_id;
    applySnapshot(snapshot);
    if (state.requestSelectionId !== selectionId) {
      const selectedRun = state.runs.find((run) => run.id === selectedRunId);
      setSelectedRun(selectedRunId);
      renderRun(selectedRun);
    } else {
      setSelectedRun(result.run_id);
      $("#run-button").disabled = false;
      $("#run-summary").textContent = "Selection approved. Execution is ready.";
    }
    setStatus("Approved", "success");
  } catch (error) {
    if (state.requestId !== requestId) return;
    if (state.approved) {
      const detail = error?.detail || error?.message || "Unknown error";
      setStatus(`Approval saved. Request refresh failed: ${detail}`, "error");
    } else if (state.requestSelectionId !== selectionId) {
      setStatus(error?.detail || error?.message || "Approval failed", "error");
    } else {
      showError(error);
    }
  } finally {
    pendingApprovalRequestIds.delete(requestId);
    if (state.requestId === requestId) {
      $("#approve-button").disabled = state.approved || !state.candidates.length;
    }
  }
});

$("#design-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const requestId = ++designReferenceRequestId;
  $("#collect-reference-button").disabled = true;
  $("#design-form").setAttribute("aria-busy", "true");
  try {
    $("#design-status").textContent = "Collecting…";
    const result = await requestJson("/api/design/references", {
      method: "POST",
      body: JSON.stringify({
        urls: [$("#reference-url").value],
        keywords: $("#reference-keywords").value.split(",").map((item) => item.trim()).filter(Boolean),
        target_type: $("#reference-target").value,
      }),
    });
    if (requestId !== designReferenceRequestId) return;
    const list = $("#references");
    list.replaceChildren(...result.pack.references.map((reference) => {
      const card = document.createElement("article");
      card.className = "reference-card";
      const title = document.createElement("strong");
      title.textContent = reference.title;
      const source = document.createElement("span");
      source.textContent = `${reference.source_url} · ${reference.license_name || "license unknown"}`;
      const uses = document.createElement("small");
      uses.textContent = `Allowed uses: ${reference.allowed_uses.join(", ")}`;
      card.append(title, source, uses);
      return card;
    }));
    $("#tokens").textContent = `Tokens: ${JSON.stringify(result.tokens)}`;
    $("#attribution").textContent = `Attribution: ${result.pack.attribution.join(" | ")}`;
    $("#design-status").textContent = "Pack recorded";
  } catch (error) {
    if (requestId !== designReferenceRequestId) return;
    $("#design-status").textContent = error?.detail || "Reference collection failed";
  } finally {
    if (requestId === designReferenceRequestId) {
      $("#collect-reference-button").disabled = false;
      $("#design-form").setAttribute("aria-busy", "false");
    }
  }
});

$("#visual-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const requestId = ++visualVerificationRequestId;
  $("#verify-visual-button").disabled = true;
  $("#visual-status").textContent = "Verifying…";
  $("#visual-form").setAttribute("aria-busy", "true");
  try {
    const result = await requestJson("/api/design/verify", {
      method: "POST",
      body: JSON.stringify({
        url: $("#visual-url").value,
        baseline: $("#visual-baseline").value,
      }),
    });
    if (requestId !== visualVerificationRequestId) return;
    const report = result.report;
    $("#visual-status").textContent = `${report.status}: ${report.blocking_reason || report.differences?.join("; ") || "No differences"} (ID: ${result.id})`;
  } catch (error) {
    if (requestId !== visualVerificationRequestId) return;
    $("#visual-status").textContent = error?.detail || "Visual verification failed";
  } finally {
    if (requestId === visualVerificationRequestId) {
      $("#verify-visual-button").disabled = false;
      $("#visual-form").setAttribute("aria-busy", "false");
    }
  }
});

$("#run-button").addEventListener("click", async () => {
  const runId = state.runId;
  if (!runId || pendingRunExecutionIds.has(runId)) return;
  pendingRunExecutionIds.add(runId);
  syncRunButton();
  try {
    setStatus("Running…", "busy");
    const run = await requestJson(`/api/runs/${runId}/execute`, { method: "POST" });
    if (state.requestId === run.request_id) {
      state.runs = state.runs.map((item) => item.id === run.id ? run : item);
      renderRunHistory(state.runs);
    }
    refreshRecentRuns();
    if (state.runId !== runId) {
      const backgroundStatus = backgroundRunStatus(runId);
      if ($("#status").textContent === backgroundStatus) {
        setStatus(`Run ${runId.slice(0, 8)} ${run.status} in background`, run.status === "completed" ? "success" : "error");
      }
      return;
    }
    renderRun(run);
    setStatus(run.status, run.status === "completed" ? "success" : "error");
  } catch (error) {
    let refreshedRun = null;
    try {
      refreshedRun = await requestJson(`/api/runs/${runId}`);
      if (state.requestId === refreshedRun.request_id) {
        state.runs = state.runs.some((item) => item.id === refreshedRun.id)
          ? state.runs.map((item) => item.id === refreshedRun.id ? refreshedRun : item)
          : [...state.runs, refreshedRun];
        renderRunHistory(state.runs);
      }
      if (state.runId === runId) {
        renderRun(refreshedRun);
        if (refreshedRun.status !== "created") {
          setStatus(
            refreshedRun.status,
            refreshedRun.status === "completed" ? "success" : refreshedRun.status === "running" ? "busy" : "error",
          );
        }
      }
    } catch (_refreshError) {
      // Preserve the execution error if the run status cannot be refreshed.
    }
    if (state.runId !== runId) {
      refreshRecentRuns();
      const backgroundStatus = backgroundRunStatus(runId);
      if ($("#status").textContent === backgroundStatus) {
        setStatus(
          refreshedRun
            ? `Run ${runId.slice(0, 8)} ${refreshedRun.status} in background`
            : `Run ${runId.slice(0, 8)} result unavailable`,
          refreshedRun?.status === "completed" ? "success" : "error",
        );
      }
      return;
    }
    if (!refreshedRun || refreshedRun.status === "created") showError(error);
  } finally {
    pendingRunExecutionIds.delete(runId);
    syncRunButton();
  }
});

$("#restore-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const requestId = $("#restore-request-id").value.trim();
  if (!requestId) return;
  await restoreRequest(requestId);
});

try {
const savedRequestId = localStorage.getItem("gleave.request-id");
  if (savedRequestId) {
    $("#restore-request-id").value = savedRequestId;
    restoreRequest(savedRequestId, true);
  }
} catch (_error) {
  // Local storage is an optional convenience; the API flow remains usable.
}

try {
  const initialProject = new URL(window.location.href).searchParams.get("project");
  if (initialProject) open_project(initialProject);
} catch (_error) {
  // A project can still be opened from the assistant form.
}

restoreRecentRunFilters();
refreshRecentRuns();
$("#load-more-runs").addEventListener("click", loadMoreRecentRuns);
$("#refresh-recent-runs").addEventListener("click", refreshRecentRunsForFilterChange);

let recentRunsSearchTimer;
$("#recent-run-search").addEventListener("input", () => {
  saveRecentRunFilters();
  clearTimeout(recentRunsSearchTimer);
  recentRunsSearchTimer = setTimeout(refreshRecentRuns, 250);
});
$("#recent-run-status-filter").addEventListener("change", () => {
  refreshRecentRunsForFilterChange();
});
$("#recent-run-created-after").addEventListener("change", () => {
  refreshRecentRunsForFilterChange();
});
$("#recent-run-created-before").addEventListener("change", () => {
  refreshRecentRunsForFilterChange();
});
$("#recent-run-page-size").addEventListener("change", refreshRecentRunsForFilterChange);
$("#recent-run-sort").addEventListener("change", refreshRecentRunsForFilterChange);
$("#clear-recent-run-filters").addEventListener("click", clearRunHistoryFilters);

$("#retry-button").addEventListener("click", async () => {
  const runId = state.runId;
  if (!runId) return;
  try {
    const run = await requestJson(`/api/runs/${runId}/retry`, { method: "POST" });
    if (state.requestId === run.request_id) {
      state.runs = state.runs.map((item) => item.id === run.id ? run : item);
      renderRunHistory(state.runs);
    }
    refreshRecentRuns();
    if (state.runId !== runId) return;
    renderRun(run);
    $("#run-summary").textContent = "Retry queued. Check the workspace for partial changes before executing again.";
    setStatus(run.status, "success");
  } catch (error) {
    if (state.runId !== runId) {
      refreshRecentRuns();
      return;
    }
    showError(error);
  }
});
