const state = {
  user: null,
  clients: [],
  clientId: null,
  reports: [],
  reportId: null,
  summary: null,
  freshness: null,
  integrationProviders: [],
  aiThreadId: null,
  aiBusy: false,
};

const els = {
  loginView: document.querySelector("#login-view"),
  cabinetView: document.querySelector("#cabinet-view"),
  loginForm: document.querySelector("#login-form"),
  loginError: document.querySelector("#login-error"),
  reportTitle: document.querySelector("#report-title"),
  reportSubtitle: document.querySelector("#report-subtitle"),
  clientSelect: document.querySelector("#client-select"),
  reportSelect: document.querySelector("#report-select"),
  logoutButton: document.querySelector("#logout-button"),
  aiOpenButton: document.querySelector("#ai-open-button"),
  integrationsOpenButton: document.querySelector("#integrations-open-button"),
  readinessCard: document.querySelector("#readiness-card"),
  readinessLabel: document.querySelector("#readiness-label"),
  readinessAction: document.querySelector("#readiness-action"),
  readinessScore: document.querySelector("#readiness-score"),
  metaPeriod: document.querySelector("#meta-period"),
  metaSourceCoverage: document.querySelector("#meta-source-coverage"),
  metaGenerated: document.querySelector("#meta-generated"),
  metaMethodology: document.querySelector("#meta-methodology"),
  metaSource: document.querySelector("#meta-source"),
  sourceRefreshPanel: document.querySelector("#source-refresh-panel"),
  sourceRefreshStatus: document.querySelector("#source-refresh-status"),
  sourceRefreshMessage: document.querySelector("#source-refresh-message"),
  sourceRefreshMeta: document.querySelector("#source-refresh-meta"),
  sourceRefreshCollections: document.querySelector("#source-refresh-collections"),
  sourceRefreshNewReport: document.querySelector("#source-refresh-new-report"),
  qualityGrid: document.querySelector("#quality-grid"),
  blockingReasons: document.querySelector("#blocking-reasons"),
  reviewReasons: document.querySelector("#review-reasons"),
  lostSalesCount: document.querySelector("#lost-sales-count"),
  lostSalesRows: document.querySelector("#lost-sales-rows"),
  liquidityCount: document.querySelector("#liquidity-count"),
  liquidityGrid: document.querySelector("#liquidity-grid"),
  liquidityRows: document.querySelector("#liquidity-rows"),
  kpiGrid: document.querySelector("#kpi-grid"),
  excelLink: document.querySelector("#excel-link"),
  draftPanel: document.querySelector("#draft-panel"),
  draftStatus: document.querySelector("#draft-status"),
  draftRefreshButton: document.querySelector("#draft-refresh-button"),
  aiPanel: document.querySelector("#ai-panel"),
  aiSourceStatus: document.querySelector("#ai-source-status"),
  aiMessages: document.querySelector("#ai-messages"),
  aiEvents: document.querySelector("#ai-events"),
  aiForm: document.querySelector("#ai-form"),
  aiInput: document.querySelector("#ai-input"),
  aiSendButton: document.querySelector("#ai-send-button"),
  aiError: document.querySelector("#ai-error"),
  integrationsPanel: document.querySelector("#integrations-panel"),
  integrationsStatus: document.querySelector("#integrations-status"),
  integrationList: document.querySelector("#integration-list"),
  reviewRowsButton: document.querySelector("#review-rows-button"),
  rowsFilterForm: document.querySelector("#rows-filter-form"),
  resetFiltersButton: document.querySelector("#reset-filters-button"),
  filterQuery: document.querySelector("#filter-query"),
  filterStatus: document.querySelector("#filter-status"),
  filterMonth: document.querySelector("#filter-month"),
  filterPeriodStart: document.querySelector("#filter-period-start"),
  filterPeriodEnd: document.querySelector("#filter-period-end"),
  filterDocumentReport: document.querySelector("#filter-document-report"),
  filterCabinet: document.querySelector("#filter-cabinet"),
  filterOrganization: document.querySelector("#filter-organization"),
  filterScheme: document.querySelector("#filter-scheme"),
  filterLossClass: document.querySelector("#filter-loss-class"),
  reviewRows: document.querySelector("#review-rows"),
  rowsCount: document.querySelector("#rows-count"),
};

document.addEventListener("DOMContentLoaded", init);

function init() {
  els.loginForm.addEventListener("submit", onLogin);
  els.logoutButton.addEventListener("click", onLogout);
  els.clientSelect.addEventListener("change", () => selectClient(els.clientSelect.value));
  els.reportSelect.addEventListener("change", () => loadReport(els.reportSelect.value));
  els.aiOpenButton.addEventListener("click", () =>
    els.aiPanel.scrollIntoView({ behavior: "smooth" }),
  );
  els.integrationsOpenButton.addEventListener("click", () =>
    els.integrationsPanel.scrollIntoView({ behavior: "smooth" }),
  );
  els.sourceRefreshNewReport.addEventListener("click", () => {
    const reportId = els.sourceRefreshNewReport.dataset.reportId || "";
    if (reportId) {
      loadReport(reportId);
    }
  });
  els.reviewRowsButton.addEventListener("click", () => {
    els.filterStatus.value = "";
    loadReviewRows("review");
    document.querySelector(".products-panel").scrollIntoView({ behavior: "smooth" });
  });
  els.draftRefreshButton.addEventListener("click", loadClientDraft);
  els.aiForm.addEventListener("submit", (event) => {
    event.preventDefault();
    sendAiQuestion(els.aiInput.value);
  });
  document.querySelectorAll("[data-ai-question]").forEach((button) => {
    button.addEventListener("click", () => sendAiQuestion(button.dataset.aiQuestion || ""));
  });
  els.rowsFilterForm.addEventListener("submit", (event) => {
    event.preventDefault();
    loadReviewRows();
  });
  els.resetFiltersButton.addEventListener("click", () => {
    els.rowsFilterForm.reset();
    loadReviewRows();
  });
  boot();
}

async function boot() {
  try {
    state.user = await api("/api/me");
    showCabinet();
    await loadClients();
  } catch (error) {
    showLogin();
  }
}

async function onLogin(event) {
  event.preventDefault();
  els.loginError.textContent = "";
  const data = new FormData(els.loginForm);
  try {
    state.user = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: data.get("email"),
        password: data.get("password"),
        remember_me: data.get("rememberMe") === "on",
      }),
    });
    els.loginForm.reset();
    showCabinet();
    await loadClients();
  } catch (error) {
    els.loginError.textContent = "Не удалось войти. Проверьте email и пароль.";
  }
}

async function onLogout() {
  await api("/api/auth/logout", { method: "POST" }).catch(() => null);
  state.user = null;
  state.clients = [];
  state.clientId = null;
  state.reports = [];
  state.reportId = null;
  state.aiThreadId = null;
  els.integrationsPanel.hidden = true;
  els.integrationsOpenButton.hidden = true;
  showLogin();
}

async function loadClients() {
  const payload = await api("/api/clients");
  state.clients = payload.items || state.user?.clients || [];
  renderClientSelect();
  if (!state.clients.length) {
    resetClientScopedState();
    setEmptyCabinet("Нет доступных клиентов", "После назначения клиента здесь появится витрина.");
    return;
  }
  if (state.clients.length === 1) {
    await selectClient(state.clients[0].clientId || state.clients[0].id);
    return;
  }
  resetClientScopedState();
  setEmptyCabinet("Выберите клиента", "Отчеты загрузятся после выбора клиентского контура.");
}

async function selectClient(clientId) {
  if (!clientId) {
    resetClientScopedState();
    setEmptyCabinet("Выберите клиента", "Отчеты загрузятся после выбора клиентского контура.");
    return;
  }
  state.clientId = clientId;
  els.clientSelect.value = clientId;
  resetClientScopedState({ keepClient: true });
  await loadReports();
}

async function loadReports() {
  if (!state.clientId) {
    setEmptyCabinet("Выберите клиента", "Отчеты загрузятся после выбора клиентского контура.");
    return;
  }
  const payload = await api(
    `/api/clients/${encodeURIComponent(state.clientId)}/reports`,
  );
  state.reports = payload.items || [];
  renderReportSelect();
  if (!state.reports.length) {
    setEmptyCabinet();
    return;
  }
  await loadReport(state.reports[0].id);
}

async function loadReport(reportId) {
  state.reportId = reportId;
  state.aiThreadId = null;
  resetAiPanel();
  const [summary, freshness] = await Promise.all([
    api(`/api/reports/${encodeURIComponent(reportId)}/summary`),
    api(`/api/reports/${encodeURIComponent(reportId)}/freshness`),
  ]);
  state.summary = summary;
  state.freshness = freshness;
  renderReport();
  renderFilters(summary.options || {});
  await Promise.all([loadReviewRows(), loadClientDraft(), loadIntegrations()]);
}

async function loadReviewRows(preset = "") {
  if (!state.reportId) {
    return;
  }
  const params = rowsFilterParams(preset);
  const payload = await api(`/api/reports/${encodeURIComponent(state.reportId)}/rows?${params}`);
  renderReviewRows(payload.items || [], payload.total || 0);
}

async function loadClientDraft() {
  if (!state.reportId) {
    return;
  }
  try {
    const payload = await api(
      `/api/reports/${encodeURIComponent(state.reportId)}/client-draft`,
    );
    els.draftPanel.hidden = false;
    if (!payload.latest) {
      els.draftStatus.textContent = "Черновик еще не подготовлен.";
      return;
    }
    const status = payload.latest.status === "ready" ? "готов" : "черновик";
    els.draftStatus.textContent = `Версия v${payload.latest.revision}: ${status}.`;
  } catch (error) {
    els.draftPanel.hidden = true;
    els.draftStatus.textContent = "";
  }
}

async function loadIntegrations() {
  if (!isStaffUser() || !state.clientId) {
    els.integrationsPanel.hidden = true;
    els.integrationsOpenButton.hidden = true;
    return;
  }
  try {
    const payload = await api(
      `/api/clients/${encodeURIComponent(state.clientId)}/integrations`,
    );
    els.integrationsOpenButton.hidden = false;
    els.integrationsPanel.hidden = false;
    state.integrationProviders = payload.providers || [];
    renderIntegrations(payload.items || []);
  } catch (error) {
    els.integrationsPanel.hidden = true;
    els.integrationsOpenButton.hidden = true;
  }
}

async function ensureAiThread() {
  if (state.aiThreadId) {
    return state.aiThreadId;
  }
  const payload = await api("/api/ai/threads", {
    method: "POST",
    body: JSON.stringify({ report_id: state.reportId, client_id: state.clientId }),
  });
  state.aiThreadId = payload.id;
  return state.aiThreadId;
}

async function sendAiQuestion(rawQuestion) {
  const question = String(rawQuestion || "").trim();
  if (!question || state.aiBusy || !state.reportId) {
    return;
  }
  state.aiBusy = true;
  els.aiError.textContent = "";
  els.aiInput.value = "";
  els.aiSendButton.disabled = true;
  appendAiMessage("user", question);
  try {
    const threadId = await ensureAiThread();
    const response = await fetch(
      `/api/ai/threads/${encodeURIComponent(threadId)}/messages/stream`,
      {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: question }),
      },
    );
    if (!response.ok || !response.body) {
      throw new Error(`HTTP ${response.status}`);
    }
    await readAiStream(response);
  } catch (error) {
    els.aiError.textContent = "Не удалось получить ответ AI. Данные WB/1С не менялись.";
  } finally {
    state.aiBusy = false;
    els.aiSendButton.disabled = false;
  }
}

async function readAiStream(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    chunks.forEach(handleSseChunk);
  }
  if (buffer.trim()) {
    handleSseChunk(buffer);
  }
}

function handleSseChunk(chunk) {
  const lines = chunk.split("\n");
  const eventLine = lines.find((line) => line.startsWith("event:"));
  const dataLine = lines.find((line) => line.startsWith("data:"));
  if (!dataLine) {
    return;
  }
  const eventName = eventLine ? eventLine.replace("event:", "").trim() : "message";
  let payload = {};
  try {
    payload = JSON.parse(dataLine.replace("data:", "").trim());
  } catch (error) {
    return;
  }
  if (eventName === "final") {
    appendAiMessage("assistant", payload.content || "");
    renderAiSource(payload);
    return;
  }
  if (eventName === "error") {
    els.aiError.textContent = payload.message || "AI временно недоступен.";
    return;
  }
  appendAiEvent(payload);
  if (payload.payload) {
    renderAiSource(payload.payload);
  }
}

function appendAiMessage(role, content) {
  if (!content) {
    return;
  }
  const item = document.createElement("div");
  item.className = `ai-message ${role}`;
  item.textContent = content;
  els.aiMessages.append(item);
  els.aiMessages.scrollTop = els.aiMessages.scrollHeight;
}

function appendAiEvent(event) {
  const item = document.createElement("li");
  const title = document.createElement("strong");
  title.textContent = event.title || "AI";
  const message = document.createElement("small");
  message.textContent = event.message || event.status || "";
  item.append(title, message);
  els.aiEvents.append(item);
}

function renderAiSource(payload) {
  const source = payload.answerSource;
  if (!source) {
    return;
  }
  els.aiSourceStatus.classList.remove("ok", "fallback");
  if (source === "openai") {
    els.aiSourceStatus.textContent = `OpenAI · ${payload.model || ""}`.trim();
    els.aiSourceStatus.classList.add("ok");
  } else {
    els.aiSourceStatus.textContent = isStaffUser()
      ? "Fallback · расчетная витрина"
      : "Расчетная витрина";
    els.aiSourceStatus.classList.add("fallback");
  }
}

function resetAiPanel() {
  els.aiMessages.replaceChildren();
  els.aiEvents.replaceChildren();
  els.aiSourceStatus.textContent = "Не запускался";
  els.aiSourceStatus.classList.remove("ok", "fallback");
  els.aiError.textContent = "";
}

function renderClientSelect() {
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Выберите клиента";
  els.clientSelect.replaceChildren(
    ...(state.clients.length > 1 ? [placeholder] : []),
    ...state.clients.map((client) => {
      const option = document.createElement("option");
      option.value = client.clientId || client.id;
      option.textContent = client.name || client.clientId || client.id;
      return option;
    }),
  );
  els.clientSelect.value = state.clientId || "";
}

function renderReportSelect() {
  els.reportSelect.replaceChildren(
    ...state.reports.map((report) => {
      const option = document.createElement("option");
      option.value = report.id;
      option.textContent = `${report.client} · ${report.period}`;
      return option;
    }),
  );
}

function renderReport() {
  const summary = state.summary || {};
  const freshness = state.freshness || {};
  const meta = summary.meta || {};
  const readiness = summary.readiness || {};
  const sourceLoads = asArray(freshness.sourceLoads);

  els.reportTitle.textContent = meta.title || "Кабинет отчета";
  els.reportSubtitle.textContent = [meta.client, meta.periodText || meta.period]
    .filter(Boolean)
    .join(" · ") || "Расчетная витрина клиента";
  els.reportSelect.value = state.reportId;
  els.metaPeriod.textContent = meta.periodText || meta.reportPeriod || meta.period || "-";
  els.metaSourceCoverage.textContent = meta.sourceCoverage || "-";
  els.metaGenerated.textContent = meta.generatedAt || freshness.generatedAt || "-";
  els.metaMethodology.textContent = meta.methodologyVersion || "-";
  els.metaSource.textContent = meta.sourceWorkbook || freshness.sourceWorkbook || "-";
  els.excelLink.href = `/api/reports/${encodeURIComponent(state.reportId)}/export.xlsx`;

  renderReadiness(readiness);
  renderSourceRefresh(summary.latestSourceRefresh || freshness.latestSourceRefresh);
  renderQuality(summary.quality || {}, sourceLoads, readiness);
  renderKpis(summary.kpis || {});
  renderLiquidity(asArray(summary.liquidityRows));
  renderLostSales(asArray(summary.lostSales));
  renderReasons(els.blockingReasons, asArray(readiness.blockingReasons));
  renderReasons(els.reviewReasons, asArray(readiness.reviewReasons));
}

function renderFilters(options) {
  setOptions(els.filterStatus, options.statuses || [], "Все статусы");
  setOptions(els.filterMonth, options.months || [], "Все месяцы");
  setDateBounds(els.filterPeriodStart, options.periodStart, options.periodEnd);
  setDateBounds(els.filterPeriodEnd, options.periodStart, options.periodEnd);
  setOptions(els.filterDocumentReport, options.documentReports || [], "Все документы");
  setOptions(els.filterCabinet, options.cabinets || [], "Все кабинеты");
  setOptions(els.filterOrganization, options.organizations || [], "Все организации");
  setOptions(els.filterScheme, options.schemes || [], "Все схемы");
  setOptions(els.filterLossClass, options.lossClasses || [], "Все классы");
}

function renderIntegrations(items) {
  els.integrationsStatus.textContent = `${items.length} подключения`;
  els.integrationList.replaceChildren(
    ...items.map((item) => {
      const card = document.createElement("article");
      card.className = "integration-card";
      const title = document.createElement("h3");
      title.textContent = item.label || integrationLabel(item.provider);
      const meta = document.createElement("p");
      meta.className = "muted";
      meta.textContent = integrationStatusText(item);
      const details = document.createElement("dl");
      details.className = "integration-details";
      details.append(
        detailItem("Тип", integrationLabel(item.providerBase || item.provider)),
        detailItem("Роль", integrationRoleLabel(item)),
        detailItem("Ключ", item.secretHint || "не сохранен"),
        detailItem("Хранение", storageModeText(item.storageMode)),
        detailItem(
          "Последняя проверка",
          item.lastCheckedAt ? formatDateTime(item.lastCheckedAt) : "не было",
        ),
      );
      if (item.lastCheck && item.lastCheck.message) {
        details.append(detailItem("Результат", item.lastCheck.message));
      }
      const form = document.createElement("form");
      form.dataset.provider = item.provider;
      const labelField = document.createElement("label");
      labelField.textContent = "Название";
      const labelInput = document.createElement("input");
      labelInput.name = "label";
      labelInput.type = "text";
      labelInput.value = item.label || integrationLabel(item.provider);
      labelField.append(labelInput);
      const secretField = document.createElement("label");
      secretField.textContent = "Новый ключ / строка подключения";
      const secretInput = document.createElement("input");
      secretInput.name = "secret";
      secretInput.type = "password";
      secretInput.autocomplete = "off";
      secretInput.placeholder = "Сохранить или заменить";
      secretField.append(secretInput);
      const roleField = document.createElement("label");
      roleField.textContent = "Роль доступа";
      const roleSelect = document.createElement("select");
      roleSelect.name = "connection_role";
      providerRoles(item.providerBase || item.provider).forEach((role) => {
        const option = document.createElement("option");
        option.value = role.id;
        option.textContent = role.label || role.id;
        roleSelect.append(option);
      });
      roleSelect.value = item.connectionRole || defaultProviderRole(item.providerBase);
      roleField.append(roleSelect);
      const actions = document.createElement("div");
      actions.className = "integration-actions";
      const saveButton = document.createElement("button");
      saveButton.type = "submit";
      saveButton.textContent = "Сохранить";
      const checkButton = document.createElement("button");
      checkButton.type = "button";
      checkButton.className = "secondary-button";
      checkButton.textContent = "Проверить";
      const disableButton = document.createElement("button");
      disableButton.type = "button";
      disableButton.className = "secondary-button";
      disableButton.textContent = "Отключить";
      actions.append(saveButton, checkButton, disableButton);
      form.append(labelField, roleField, secretField, actions);
      form.addEventListener("submit", onIntegrationSave);
      checkButton.addEventListener("click", () => onIntegrationAction(item.provider, "check"));
      disableButton.addEventListener("click", () =>
        onIntegrationAction(item.provider, "disable"),
      );
      card.append(title, meta, details, form);
      return card;
    }),
  );
}

function detailItem(term, value) {
  const fragment = document.createDocumentFragment();
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  dd.textContent = value || "-";
  fragment.append(dt, dd);
  return fragment;
}

async function onIntegrationSave(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const provider = form.dataset.provider;
  const data = new FormData(form);
  const secret = String(data.get("secret") || "").trim();
  if (!secret) {
    els.integrationsStatus.textContent = "Введите новый ключ перед сохранением.";
    return;
  }
  try {
    await api(`/api/integrations/${encodeURIComponent(provider)}`, {
      method: "PUT",
      body: JSON.stringify({
        label: String(data.get("label") || ""),
        connection_role: String(data.get("connection_role") || ""),
        client_id: state.clientId,
        secret,
      }),
    });
    form.reset();
    await loadIntegrations();
  } catch (error) {
    els.integrationsStatus.textContent = "Не удалось сохранить подключение.";
  }
}

async function onIntegrationAction(provider, action) {
  try {
    await api(`/api/integrations/${encodeURIComponent(provider)}/${action}`, {
      method: "POST",
      body: JSON.stringify({ client_id: state.clientId }),
    });
    await loadIntegrations();
  } catch (error) {
    els.integrationsStatus.textContent = "Не удалось выполнить действие.";
  }
}

function integrationStatusText(item) {
  const labels = {
    not_configured: "Не настроено",
    configured: `Сохранено ${item.secretHint || ""}`.trim(),
    check_ok: `Проверка пройдена ${item.secretHint || ""}`.trim(),
    check_failed: "Нужна проверка",
    disabled: "Отключено",
  };
  return labels[item.status] || item.status || "Не настроено";
}

function storageModeText(storageMode) {
  return {
    encrypted: "encrypted storage",
    hash_only: "hash-only, нужен повторный ввод",
    none: "не настроено",
  }[storageMode] || storageMode || "не настроено";
}

function integrationLabel(provider) {
  return providerMetadata(provider).label || provider;
}

function providerMetadata(provider) {
  const providerBase = String(provider || "").split(":")[0];
  return (
    state.integrationProviders.find((item) => item.providerBase === providerBase) || {
      providerBase,
      label: providerBase,
      roles: [],
    }
  );
}

function providerRoles(provider) {
  return providerMetadata(provider).roles || [];
}

function defaultProviderRole(provider) {
  const role = providerRoles(provider).find((item) => item.default);
  return role ? role.id : "";
}

function integrationRoleLabel(item) {
  const roleId = item.connectionRole || defaultProviderRole(item.providerBase);
  const role = providerRoles(item.providerBase || item.provider).find(
    (candidate) => candidate.id === roleId,
  );
  return role ? role.label : roleId || "-";
}

function setOptions(select, values, emptyLabel) {
  const current = select.value;
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = emptyLabel;
  const safeValues = asArray(values);
  const items = safeValues.map((value) => {
    const option = document.createElement("option");
    option.value = optionValue(value);
    option.textContent = optionLabel(value);
    return option;
  });
  select.replaceChildren(empty, ...items);
  select.value = safeValues.some((value) => optionValue(value) === current)
    ? current
    : "";
}

function optionValue(value) {
  if (value && typeof value === "object") {
    return String(value.id || value.value || value.label || "");
  }
  return String(value || "");
}

function optionLabel(value) {
  if (value && typeof value === "object") {
    return String(value.label || value.name || value.id || value.value || "");
  }
  return String(value || "");
}

function setDateBounds(input, min, max) {
  const current = input.value;
  input.min = min || "";
  input.max = max || "";
  input.value = current;
}

function renderReadiness(readiness) {
  els.readinessLabel.textContent = readiness.label || "Статус не рассчитан";
  els.readinessAction.textContent = readiness.nextAction || "Проверить отчет.";
  els.readinessScore.textContent = String(readiness.score ?? 0);
  els.readinessCard.className = "overview-panel";
  if (readiness.status === "ready") {
    els.readinessCard.classList.add("readiness-ready");
  } else if (["failed", "blocked"].includes(readiness.status)) {
    els.readinessCard.classList.add("readiness-blocked");
  } else {
    els.readinessCard.classList.add("readiness-review");
  }
}

function renderSourceRefresh(refresh) {
  if (!refresh) {
    els.sourceRefreshPanel.hidden = true;
    return;
  }
  els.sourceRefreshPanel.hidden = false;
  els.sourceRefreshStatus.className = "status-pill";
  els.sourceRefreshStatus.textContent = sourceRefreshStatusText(refresh.status);
  if (refresh.newReportRunId) {
    els.sourceRefreshStatus.classList.add("ok");
  } else if (["failed", "needs_configuration", "needs_review"].includes(refresh.status)) {
    els.sourceRefreshStatus.classList.add("fallback");
  }
  els.sourceRefreshMessage.textContent =
    refresh.safeMessage || refresh.errorMessage || sourceRefreshDefaultMessage(refresh);
  els.sourceRefreshMeta.replaceChildren(
    detailItem("Режим", refresh.mode || "-"),
    detailItem("Покрытие источников", sourceRefreshPeriod(refresh)),
    detailItem("Snapshot set", refresh.snapshotSetId || "-"),
    detailItem("Старт", formatDateTime(refresh.startedAt) || "-"),
    detailItem("Финиш", formatDateTime(refresh.finishedAt) || "-"),
    detailItem("Новый отчет", refresh.newReportRunId || "не создан"),
  );
  els.sourceRefreshCollections.replaceChildren(
    ...asArray(refresh.collections).map(sourceRefreshCollectionNode),
  );
  if (refresh.newReportRunId) {
    els.sourceRefreshNewReport.hidden = false;
    els.sourceRefreshNewReport.dataset.reportId = refresh.newReportRunId;
  } else {
    els.sourceRefreshNewReport.hidden = true;
    els.sourceRefreshNewReport.dataset.reportId = "";
  }
}

function sourceRefreshCollectionNode(item) {
  const node = document.createElement("div");
  node.className = "source-refresh-collection";
  const title = document.createElement("strong");
  title.textContent = item.sourceLabel || item.sourceType || "Источник";
  const status = document.createElement("span");
  status.textContent = `${sourceRefreshStatusText(item.status)} · ${number(item.rowCount || 0)} строк`;
  const kind = document.createElement("small");
  kind.textContent = item.required ? "обязательный источник" : "опциональный источник";
  node.append(title, status, kind);
  return node;
}

function sourceRefreshPeriod(refresh) {
  if (!refresh) {
    return "-";
  }
  return [refresh.periodStart, refresh.periodEnd].filter(Boolean).join(" - ") || "-";
}

function sourceRefreshStatusText(status) {
  return {
    queued: "В очереди",
    running: "Выполняется",
    source_loaded: "Источники загружены",
    rebuilding: "Сборка отчета",
    report_created: "Отчет обновлен",
    needs_review: "Нужна проверка",
    needs_configuration: "Нужна настройка",
    dry_run_ready: "Dry-run готов",
    failed: "Ошибка",
    loaded: "Загружен",
    empty_expected: "Пусто ожидаемо",
    empty_unexpected: "Пусто неожиданно",
    partial_source: "Неполный источник",
    rate_limited: "Rate limit",
    auth_failed: "Ошибка доступа",
    schema_error: "Ошибка схемы",
    stale: "Устарел",
  }[status] || status || "Не запускался";
}

function sourceRefreshDefaultMessage(refresh) {
  return refresh.newReportRunId
    ? "Последний refresh обновил отчет."
    : "Последний refresh не обновил отчет.";
}

function renderQuality(quality, sourceLoads, readiness) {
  const total = Number(quality.rowCount || 0);
  const okRows = Number(quality.okRows || 0);
  const missingCost = Number(quality.missingCostRows || 0);
  const mapping = Number(quality.mappingRows || 0);
  const incompleteSources = asArray(sourceLoads).filter(
    (load) =>
      !["loaded", "ok", "ready", "completed", "empty_expected"].includes(
        normalize(load.status),
      ),
  ).length;
  const partialPeriod =
    quality.partialPeriod || readinessHasCode(readiness, "partial_period")
      ? "Да"
      : "Нет";
  const okShare = `${Math.round(Number(quality.okShare || 0) * 100)}%`;
  renderMetrics(els.qualityGrid, [
    ["Строк ОК", `${okRows} из ${total}`],
    ["Доля ОК", okShare],
    ["Без себестоимости", missingCost],
    ["Маппинг / сопоставление", mapping],
    ["Неполный период", partialPeriod],
    ["Неполные источники", Number(quality.incompleteSources ?? incompleteSources)],
  ]);
}

function renderKpis(kpis) {
  const revenue = Number(kpis.revenue || 0);
  const profit = Number(kpis.profit || 0);
  const returns = Number(kpis.returns || 0);
  const sales = Number(kpis.sales || 0);
  const lossRows = Number(kpis.lossRows || 0);
  const margin =
    kpis.margin === null || kpis.margin === undefined
      ? "-"
      : `${Math.round(Number(kpis.margin || 0) * 1000) / 10}%`;
  renderMetrics(els.kpiGrid, [
    ["Выручка после СПП", money(revenue)],
    ["Прибыль после налогов", money(profit)],
    ["Маржа", margin],
    ["Продажи, шт", number(sales)],
    ["Возвраты, шт", number(returns)],
    ["Убыточных строк", lossRows],
  ]);
}

function renderLiquidity(rows) {
  const safeRows = asArray(rows);
  els.liquidityCount.textContent = safeRows.length
    ? `${safeRows.length} групп`
    : "Нет групп";
  const lossRows = safeRows.filter((row) => Number(row.profit || 0) < 0);
  const reviewRows = safeRows.filter((row) => normalize(row.status) !== "ок");
  const bestRows = safeRows.filter((row) => Number(row.profit || 0) > 0);
  renderMetrics(els.liquidityGrid, [
    ["Групп", number(safeRows.length)],
    ["Убыточных", number(lossRows.length)],
    ["Нужна проверка", number(reviewRows.length)],
    ["Лучший МД", money(Math.max(0, ...bestRows.map((row) => Number(row.profit || 0))))],
  ]);
  const sorted = [...safeRows].sort((left, right) => {
    const leftProfit = Number(left.profit || 0);
    const rightProfit = Number(right.profit || 0);
    if (leftProfit !== rightProfit) {
      return leftProfit - rightProfit;
    }
    return String(left.product || "").localeCompare(String(right.product || ""), "ru");
  });
  const visible = [
    ...sorted.filter((row) => Number(row.profit || 0) < 0).slice(0, 12),
    ...sorted.filter((row) => Number(row.profit || 0) >= 0).slice(-8).reverse(),
  ];
  if (!visible.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 11;
    cell.textContent = "Нет данных для витрины ликвидности.";
    row.append(cell);
    els.liquidityRows.replaceChildren(row);
    return;
  }
  els.liquidityRows.replaceChildren(
    ...visible.map((item) => {
      const row = document.createElement("tr");
      [
        item.month || "-",
        item.liquidityStatus || "-",
        item.liquidityDriver || "-",
        item.product || "-",
        item.articleWb || "-",
        item.article1c || "-",
        number(item.sales || 0),
        money(item.revenue || 0),
        money(item.profit || 0),
        item.unitProfit || item.unitProfit === 0 ? money(item.unitProfit) : "-",
        item.status || "-",
      ].forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = String(value);
        row.append(cell);
      });
      return row;
    }),
  );
}

function renderMetrics(target, items) {
  target.replaceChildren(
    ...items.map(([label, value]) => {
      const item = document.createElement("div");
      item.className = "metric";
      const labelNode = document.createElement("span");
      labelNode.textContent = label;
      const valueNode = document.createElement("strong");
      valueNode.textContent = String(value);
      item.append(labelNode, valueNode);
      return item;
    }),
  );
}

function renderReasons(target, reasons) {
  const safeReasons = asArray(reasons);
  if (!safeReasons.length) {
    const item = document.createElement("li");
    item.textContent = "Нет";
    target.replaceChildren(item);
    return;
  }
  target.replaceChildren(
    ...safeReasons.map((reason) => {
      const item = document.createElement("li");
      const count = reason.count || reason.count === 0 ? ` (${reason.count})` : "";
      item.textContent = `${reason.message}${count}`;
      return item;
    }),
  );
}

function renderReviewRows(rows, total) {
  const safeRows = asArray(rows);
  els.rowsCount.textContent = total ? `${total} строк` : "Нет строк";
  if (!safeRows.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 15;
    cell.textContent = "Строки не найдены. Измените фильтры или сбросьте поиск.";
    row.append(cell);
    els.reviewRows.replaceChildren(row);
    return;
  }
  els.reviewRows.replaceChildren(
    ...safeRows.map((item) => {
      const row = document.createElement("tr");
      [
        item.month || "-",
        item.documentReport || "-",
        item.wbReportId || "-",
        item.wbReportDate || "-",
        item.cabinet || "-",
        item.product || "-",
        item.articleWb || "-",
        item.article1c || "-",
        item.barcode || "-",
        item.scheme || "-",
        item.status || "-",
        number(item.sales || 0),
        number(item.returns || 0),
        money(item.revenue || 0),
        money(item.profit || 0),
      ].forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = String(value);
        row.append(cell);
      });
      return row;
    }),
  );
}

function renderLostSales(rows) {
  const sorted = [...asArray(rows)]
    .filter((row) => Number(row.lostProfit || 0) > 0 || Number(row.zeroStockDays || 0) > 0)
    .sort(
      (left, right) =>
        Number(right.lostProfit || 0) - Number(left.lostProfit || 0) ||
        Number(right.lostRevenue || 0) - Number(left.lostRevenue || 0),
    )
    .slice(0, 30);
  els.lostSalesCount.textContent = sorted.length ? `${sorted.length} строк` : "Нет строк";
  if (!sorted.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 10;
    cell.textContent = "Нет строк для предварительной оценки упущенных продаж.";
    row.append(cell);
    els.lostSalesRows.replaceChildren(row);
    return;
  }
  els.lostSalesRows.replaceChildren(
    ...sorted.map((item) => {
      const row = document.createElement("tr");
      [
        item.cabinet || "-",
        item.product || "-",
        item.article1c || "-",
        item.barcode || "-",
        number(item.zeroStockDays || 0),
        number(item.onecStock || 0),
        item.onecWarehouses || "-",
        number(item.lostUnits || 0),
        money(item.lostProfit || 0),
        item.note || "-",
      ].forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = String(value);
        row.append(cell);
      });
      return row;
    }),
  );
}

function rowsFilterParams(preset) {
  const params = new URLSearchParams();
  params.set("limit", "50");
  const values = {
    query: els.filterQuery.value.trim(),
    status_filter: els.filterStatus.value,
    period_start: els.filterPeriodStart.value,
    period_end: els.filterPeriodEnd.value,
    month: els.filterMonth.value,
    document_report: els.filterDocumentReport.value,
    wb_cabinet_id: els.filterCabinet.value,
    client_company_id: els.filterOrganization.value,
    scheme: els.filterScheme.value,
    loss_class: els.filterLossClass.value,
    preset,
  };
  Object.entries(values).forEach(([key, value]) => {
    if (value) {
      params.set(key, value);
    }
  });
  return params.toString();
}

function resetClientScopedState(options = {}) {
  if (!options.keepClient) {
    state.clientId = null;
  }
  state.reports = [];
  state.reportId = null;
  state.summary = null;
  state.freshness = null;
  state.integrationProviders = [];
  state.aiThreadId = null;
  els.reportSelect.replaceChildren();
  els.rowsFilterForm.reset();
  resetAiPanel();
  els.sourceRefreshPanel.hidden = true;
  els.integrationsPanel.hidden = true;
  els.integrationsOpenButton.hidden = true;
  els.draftPanel.hidden = true;
  renderReviewRows([], 0);
  renderLostSales([]);
  renderLiquidity([]);
}

function setEmptyCabinet(title = "Нет доступных отчетов", subtitle = "После импорта отчета здесь появится расчетная витрина.") {
  els.reportTitle.textContent = title;
  els.reportSubtitle.textContent = subtitle;
  renderMetrics(els.kpiGrid, []);
  renderMetrics(els.qualityGrid, []);
}

function showLogin() {
  els.loginView.hidden = false;
  els.cabinetView.hidden = true;
}

function showCabinet() {
  els.loginView.hidden = true;
  els.cabinetView.hidden = false;
}

function isStaffUser() {
  const client = selectedClient();
  if (client) {
    return ["admin", "consultant"].includes(client.role);
  }
  return (state.user?.tenants || []).some((tenant) =>
    ["admin", "consultant"].includes(tenant.role),
  );
}

function selectedClient() {
  return state.clients.find((client) => (client.clientId || client.id) === state.clientId);
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

function escapeAttribute(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function readinessHasCode(readiness, code) {
  const reasons = [
    ...asArray(readiness.blockingReasons),
    ...asArray(readiness.reviewReasons),
  ];
  return reasons.some((reason) => reason.code === code);
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function qualityText(row) {
  return normalize(
    [row.status, row.statusReason, row.lossClass, row.lossDriver]
      .filter(Boolean)
      .join(" "),
  );
}

function normalize(value) {
  return String(value || "").trim().toLowerCase();
}

function sum(rows, key) {
  return rows.reduce((total, row) => total + Number(row[key] || 0), 0);
}

function money(value) {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(
    Number(value || 0),
  )} ₽`;
}

function number(value) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(
    Number(value || 0),
  );
}

function formatDateTime(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}
