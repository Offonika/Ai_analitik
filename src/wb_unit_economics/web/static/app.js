const state = {
  user: null,
  clients: [],
  clientId: null,
  reports: [],
  reportId: null,
  clientLoadToken: 0,
  summary: null,
  freshness: null,
  integrationProviders: [],
  integrationItems: [],
  integrationNotices: {},
  editingIntegrationKey: "",
  integrationProviderFilter: "",
  draftIntegration: null,
  latestSourceRefresh: null,
  latestOzonDiagnostics: null,
  ozonDiagnosticsParams: "",
  ozonUnitStatusFilter: "",
  sourceRefreshPollTimer: 0,
  aiThreadId: null,
  aiBusy: false,
  onecReconciliationLoaded: false,
  rowPreset: "",
};

const els = {
  loginView: document.querySelector("#login-view"),
  cabinetView: document.querySelector("#cabinet-view"),
  loginForm: document.querySelector("#login-form"),
  loginError: document.querySelector("#login-error"),
  reportTitle: document.querySelector("#report-title"),
  reportSubtitle: document.querySelector("#report-subtitle"),
  clientSelect: document.querySelector("#client-select"),
  topbarCabinetSelect: document.querySelector("#topbar-cabinet-select"),
  topbarPeriodStart: document.querySelector("#topbar-period-start"),
  topbarPeriodEnd: document.querySelector("#topbar-period-end"),
  logoutButton: document.querySelector("#logout-button"),
  clientOutputButton: document.querySelector("#client-output-button"),
  aiOpenButton: document.querySelector("#ai-open-button"),
  integrationsOpenButton: document.querySelector("#integrations-open-button"),
  newClientButton: document.querySelector("#new-client-button"),
  newClientWidgetOverlay: document.querySelector("#new-client-widget-overlay"),
  newClientWidgetClose: document.querySelector("#new-client-widget-close"),
  newClientForm: document.querySelector("#new-client-form"),
  newClientName: document.querySelector("#new-client-name"),
  newClientTenantId: document.querySelector("#new-client-tenant-id"),
  newClientClientId: document.querySelector("#new-client-client-id"),
  newClientCompanies: document.querySelector("#new-client-companies"),
  newClientCabinets: document.querySelector("#new-client-cabinets"),
  newClientStatus: document.querySelector("#new-client-status"),
  newClientSubmit: document.querySelector("#new-client-submit"),
  aiWidgetOverlay: document.querySelector("#ai-widget-overlay"),
  aiWidgetClose: document.querySelector("#ai-widget-close"),
  clientOutputWidgetOverlay: document.querySelector("#client-output-widget-overlay"),
  clientOutputWidgetClose: document.querySelector("#client-output-widget-close"),
  integrationsWidgetOverlay: document.querySelector("#integrations-widget-overlay"),
  integrationsWidgetClose: document.querySelector("#integrations-widget-close"),
  drilldownWidgetOverlay: document.querySelector("#drilldown-widget-overlay"),
  drilldownWidgetClose: document.querySelector("#drilldown-widget-close"),
  drilldownTitle: document.querySelector("#drilldown-title"),
  drilldownSubtitle: document.querySelector("#drilldown-subtitle"),
  drilldownCount: document.querySelector("#drilldown-count"),
  drilldownTabs: document.querySelectorAll("[data-drilldown-preset]"),
  drilldownSources: document.querySelector("#drilldown-sources"),
  drilldownTableWrap: document.querySelector("#drilldown-table-wrap"),
  drilldownRows: document.querySelector("#drilldown-rows"),
  reportOnlyControls: document.querySelectorAll(".report-only-control"),
  reportPageSections: document.querySelectorAll(".report-page-section"),
  readinessCard: document.querySelector("#readiness-card"),
  overviewTitle: document.querySelector("#overview-title"),
  readinessLabel: document.querySelector("#readiness-label"),
  readinessAction: document.querySelector("#readiness-action"),
  readinessScore: document.querySelector("#readiness-score"),
  nextActionTitle: document.querySelector("#next-action-title"),
  nextActionCopy: document.querySelector("#next-action-copy"),
  nextActionButton: document.querySelector("#next-action-button"),
  nextActionMeta: document.querySelector("#next-action-meta"),
  nextActionUploadForm: document.querySelector("#next-action-upload-form"),
  nextActionUploadFile: document.querySelector("#next-action-upload-file"),
  nextActionUploadStatus: document.querySelector("#next-action-upload-status"),
  nextActionUploadSubmit: document.querySelector("#next-action-upload-submit"),
  commandStatus: document.querySelector("#command-status"),
  commandChecklist: document.querySelector("#command-checklist"),
  qualitySummaryText: document.querySelector("#quality-summary-text"),
  qualityProgressFill: document.querySelector("#quality-progress-fill"),
  qualityGrid: document.querySelector("#quality-grid"),
  blockingReasons: document.querySelector("#blocking-reasons"),
  reviewReasons: document.querySelector("#review-reasons"),
  doneReasons: document.querySelector("#done-reasons"),
  lostSalesCount: document.querySelector("#lost-sales-count"),
  lostSalesRows: document.querySelector("#lost-sales-rows"),
  liquidityCount: document.querySelector("#liquidity-count"),
  liquiditySummary: document.querySelector("#liquidity-summary"),
  liquidityGrid: document.querySelector("#liquidity-grid"),
  liquidityRows: document.querySelector("#liquidity-rows"),
  kpiEyebrow: document.querySelector("#kpi-eyebrow"),
  kpiTitle: document.querySelector("#kpi-title"),
  kpiGrid: document.querySelector("#kpi-grid"),
  actionInsightsList: document.querySelector("#action-insights-list"),
  moneyTrendTitle: document.querySelector("#money-trend-title"),
  moneyTrendCopy: document.querySelector("#money-trend-title")?.nextElementSibling,
  moneyTrendChart: document.querySelector("#money-trend-chart"),
  unitPlTitle: document.querySelector("#unit-pl-title"),
  unitPlCopy: document.querySelector("#unit-pl-title")?.nextElementSibling,
  unitPlTable: document.querySelector("#unit-pl-table"),
  lossDriversTitle: document.querySelector("#loss-drivers-title"),
  lossDriversCopy: document.querySelector("#loss-drivers-title")?.nextElementSibling,
  lossDriversChart: document.querySelector("#loss-drivers-chart"),
  returnsChartTitle: document.querySelector("#returns-chart-title"),
  returnsChartCopy: document.querySelector("#returns-chart-title")?.nextElementSibling,
  returnsChart: document.querySelector("#returns-chart"),
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
  integrationProviderTabButtons: document.querySelectorAll(
    "[data-integration-provider-filter]",
  ),
  integrationList: document.querySelector("#integration-list"),
  sourceRefreshPanel: document.querySelector("#source-refresh-panel"),
  sourceRefreshStatus: document.querySelector("#source-refresh-status"),
  sourceRefreshSteps: document.querySelector("#source-refresh-steps"),
  sourceRefreshCollections: document.querySelector("#source-refresh-collections"),
  sourceRefreshMappingForm: document.querySelector("#source-refresh-mapping-form"),
  sourceRefreshMappingFile: document.querySelector("#source-refresh-mapping-file"),
  sourceRefreshMappingStatus: document.querySelector("#source-refresh-mapping-status"),
  sourceRefreshUploadSubmit: document.querySelector("#source-refresh-upload-submit"),
  sourceRefreshDryRun: document.querySelector("#source-refresh-dry-run"),
  sourceRefreshFullRun: document.querySelector("#source-refresh-full-run"),
  sourceRefreshOzonRun: document.querySelector("#source-refresh-ozon-run"),
  sourceRefreshReload: document.querySelector("#source-refresh-reload"),
  reviewRowsButton: document.querySelector("#review-rows-button"),
  detailTabs: document.querySelectorAll("[data-detail-tab]"),
  detailPanels: document.querySelectorAll("[data-detail-panel]"),
  onecReconciliationCount: document.querySelector("#onec-reconciliation-count"),
  onecReconciliationGrid: document.querySelector("#onec-reconciliation-grid"),
  onecReconciliationRows: document.querySelector("#onec-reconciliation-rows"),
  onecReconciliationFilterForm: document.querySelector(
    "#onec-reconciliation-filter-form",
  ),
  onecResetFiltersButton: document.querySelector("#onec-reset-filters-button"),
  onecFilterQuery: document.querySelector("#onec-filter-query"),
  onecFilterStatus: document.querySelector("#onec-filter-status"),
  onecFilterPeriodStart: document.querySelector("#onec-filter-period-start"),
  onecFilterPeriodEnd: document.querySelector("#onec-filter-period-end"),
  onecFilterCabinet: document.querySelector("#onec-filter-cabinet"),
  onecFilterOrganization: document.querySelector("#onec-filter-organization"),
  onecFilterDocumentType: document.querySelector("#onec-filter-document-type"),
  onecFilterDeltaOnly: document.querySelector("#onec-filter-delta-only"),
  ozonDiagnosticsPanel: document.querySelector("#ozon-diagnostics-panel"),
  ozonTab: document.querySelector("#detail-tab-ozon"),
  ozonPreviewSummary: document.querySelector("#ozon-preview-summary"),
  ozonPreviewCount: document.querySelector("#ozon-preview-count"),
  ozonExcelLink: document.querySelector("#ozon-excel-link"),
  ozonPreviewGrid: document.querySelector("#ozon-preview-grid"),
  ozonVitrineStatus: document.querySelector("#ozon-vitrine-status"),
  ozonIssuesPanel: document.querySelector("#ozon-issues-panel"),
  ozonIssueList: document.querySelector("#ozon-issue-list"),
  ozonIssueEmpty: document.querySelector("#ozon-issue-empty"),
  ozonPnlSection: document.querySelector("#ozon-pnl-section"),
  ozonPnlMessage: document.querySelector("#ozon-pnl-message"),
  ozonPnlGrid: document.querySelector("#ozon-pnl-grid"),
  ozonPnlEmpty: document.querySelector("#ozon-pnl-empty"),
  ozonUnitStatusFilter: document.querySelector("#ozon-unit-status-filter"),
  ozonUnitEmpty: document.querySelector("#ozon-unit-empty"),
  ozonUnitRows: document.querySelector("#ozon-unit-rows"),
  ozonBuyoutEmpty: document.querySelector("#ozon-buyout-empty"),
  ozonBuyoutRows: document.querySelector("#ozon-buyout-rows"),
  ozonDiagnosticMessage: document.querySelector("#ozon-diagnostic-message"),
  ozonPreviewEmpty: document.querySelector("#ozon-preview-empty"),
  ozonPreviewRows: document.querySelector("#ozon-preview-rows"),
  ozonMappingEmpty: document.querySelector("#ozon-mapping-empty"),
  ozonMappingRows: document.querySelector("#ozon-mapping-rows"),
  rowsFilterForm: document.querySelector("#rows-filter-form"),
  rowsPresetButtons: document.querySelectorAll("[data-row-preset]"),
  resetFiltersButton: document.querySelector("#reset-filters-button"),
  filterQuery: document.querySelector("#filter-query"),
  filterStatus: document.querySelector("#filter-status"),
  filterMonth: document.querySelector("#filter-month"),
  filterPeriodStart: document.querySelector("#filter-period-start"),
  filterPeriodEnd: document.querySelector("#filter-period-end"),
  filterCabinet: document.querySelector("#filter-cabinet"),
  filterOrganization: document.querySelector("#filter-organization"),
  filterScheme: document.querySelector("#filter-scheme"),
  filterLossClass: document.querySelector("#filter-loss-class"),
  rowsTitle: document.querySelector("#rows-title"),
  reviewRowsHead: document.querySelector("#review-rows-head"),
  reviewRows: document.querySelector("#review-rows"),
  rowsCount: document.querySelector("#rows-count"),
};

const OZON_UNIT_STATUS_OPTIONS = [
  { id: "ready", label: "Готово" },
  { id: "partial_source", label: "Частично" },
  { id: "missing_mapping", label: "Нет связи" },
  { id: "ambiguous_mapping", label: "Неоднозначно" },
  { id: "missing_cost", label: "Нет себестоимости" },
  { id: "missing_1c_commissioner", label: "Нет выручки 1C" },
  { id: "buyout_period_only", label: "Выкуп по периоду" },
];

const FILTER_STATE_STORAGE_KEY = "wb-unit-economics:cabinet-filters:v1";

document.addEventListener("DOMContentLoaded", init);

function init() {
  configurePageMode();
  els.loginForm.addEventListener("submit", onLogin);
  els.logoutButton.addEventListener("click", onLogout);
  els.clientSelect.addEventListener("change", () => selectClient(els.clientSelect.value));
  els.topbarCabinetSelect.addEventListener("change", () =>
    applyTopbarFilter("cabinet"),
  );
  els.topbarPeriodStart.addEventListener("change", () =>
    applyTopbarFilter("periodRange"),
  );
  els.topbarPeriodEnd.addEventListener("change", () =>
    applyTopbarFilter("periodRange"),
  );
  els.clientOutputButton.addEventListener("click", openClientOutputWidget);
  els.nextActionButton.addEventListener("click", onNextAction);
  els.nextActionUploadFile.addEventListener("change", () =>
    onMappingFileSelected("next"),
  );
  els.nextActionUploadForm.addEventListener("submit", (event) =>
    onMappingUpload(event, "next"),
  );
  els.sourceRefreshMappingFile.addEventListener("change", () =>
    onMappingFileSelected("sourceRefresh"),
  );
  els.sourceRefreshMappingForm.addEventListener("submit", (event) =>
    onMappingUpload(event, "sourceRefresh"),
  );
  els.sourceRefreshDryRun.addEventListener("click", () =>
    runClientSourceRefresh({ dryRun: true }),
  );
  els.sourceRefreshFullRun.addEventListener("click", () =>
    runClientSourceRefresh({ dryRun: false }),
  );
  if (els.sourceRefreshOzonRun) {
    els.sourceRefreshOzonRun.addEventListener("click", () =>
      runClientSourceRefresh({ dryRun: false, mode: "ozon-only" }),
    );
  }
  els.sourceRefreshReload.addEventListener("click", () =>
    loadSourceRefreshStatus(currentClientLoadContext()),
  );
  els.aiOpenButton.addEventListener("click", openAiWidget);
  els.aiWidgetClose.addEventListener("click", closeAiWidget);
  els.aiWidgetOverlay.addEventListener("click", (event) => {
    if (event.target === els.aiWidgetOverlay) {
      closeAiWidget();
    }
  });
  els.clientOutputWidgetClose.addEventListener("click", closeClientOutputWidget);
  els.clientOutputWidgetOverlay.addEventListener("click", (event) => {
    if (event.target === els.clientOutputWidgetOverlay) {
      closeClientOutputWidget();
    }
  });
  els.integrationsOpenButton.addEventListener("click", openIntegrationsWidget);
  els.integrationProviderTabButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.integrationProviderFilter =
        button.dataset.integrationProviderFilter || "";
      renderIntegrationsWithFallback(state.integrationItems);
    });
  });
  els.integrationsWidgetClose.addEventListener("click", closeIntegrationsWidget);
  els.integrationsWidgetOverlay.addEventListener("click", (event) => {
    if (event.target === els.integrationsWidgetOverlay) {
      closeIntegrationsWidget();
    }
  });
  els.newClientButton.addEventListener("click", openNewClientWidget);
  els.newClientWidgetClose.addEventListener("click", closeNewClientWidget);
  els.newClientWidgetOverlay.addEventListener("click", (event) => {
    if (event.target === els.newClientWidgetOverlay) {
      closeNewClientWidget();
    }
  });
  els.newClientForm.addEventListener("submit", onNewClientSubmit);
  els.drilldownWidgetClose.addEventListener("click", closeDrilldownWidget);
  els.drilldownWidgetOverlay.addEventListener("click", (event) => {
    if (event.target === els.drilldownWidgetOverlay) {
      closeDrilldownWidget();
    }
  });
  els.drilldownTabs.forEach((button) => {
    button.addEventListener("click", () =>
      selectDrilldownPreset(button.dataset.drilldownPreset || "review"),
    );
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeAllWidgets();
    }
  });
  els.reviewRowsButton.addEventListener("click", () => {
    openDrilldownWidget("review");
  });
  els.detailTabs.forEach((button) => {
    button.addEventListener("click", () =>
      selectDetailTab(button.dataset.detailTab || "products"),
    );
  });
  if (els.ozonUnitStatusFilter) {
    setOptions(els.ozonUnitStatusFilter, OZON_UNIT_STATUS_OPTIONS, "Все статусы");
    els.ozonUnitStatusFilter.addEventListener("change", () => {
      state.ozonUnitStatusFilter = els.ozonUnitStatusFilter.value;
      saveFilterState();
      renderOzonPreview(state.latestSourceRefresh, state.latestOzonDiagnostics);
    });
  }
  els.rowsPresetButtons.forEach((button) => {
    button.addEventListener("click", () =>
      selectRowsPreset(button.dataset.rowPreset || ""),
    );
  });
  document.addEventListener("click", onAnalyticsAction);
  document.addEventListener("keydown", onAnalyticsAction);
  els.draftRefreshButton.addEventListener("click", () =>
    loadClientDraft(currentClientLoadContext()),
  );
  els.aiForm.addEventListener("submit", (event) => {
    event.preventDefault();
    sendAiQuestion(els.aiInput.value);
  });
  document.querySelectorAll("[data-ai-question]").forEach((button) => {
    button.addEventListener("click", () => sendAiQuestion(button.dataset.aiQuestion || ""));
  });
  bindAutoApplyingFilters();
  bindOnecReconciliationFilters();
  els.rowsFilterForm.addEventListener("submit", (event) => {
    event.preventDefault();
    applyRowsFilters();
  });
  els.resetFiltersButton.addEventListener("click", () => {
    els.rowsFilterForm.reset();
    selectRowsPreset("", { load: false });
    saveFilterState();
    applyRowsFilters();
  });
  els.onecReconciliationFilterForm.addEventListener("submit", (event) => {
    event.preventDefault();
    applyOnecReconciliationFilters();
  });
  els.onecResetFiltersButton.addEventListener("click", () => {
    els.onecReconciliationFilterForm.reset();
    saveFilterState();
    applyOnecReconciliationFilters();
  });
  boot();
}

function bindAutoApplyingFilters() {
  [
    els.filterStatus,
    els.filterMonth,
    els.filterPeriodStart,
    els.filterPeriodEnd,
    els.filterCabinet,
    els.filterOrganization,
    els.filterScheme,
    els.filterLossClass,
  ].forEach((control) => {
    control.addEventListener("change", applyRowsFilters);
  });
  els.filterQuery.addEventListener("input", debounce(applyRowsFilters, 250));
}

function applyRowsFilters() {
  const previousOzonParams = state.ozonDiagnosticsParams || "";
  syncTopbarFiltersFromRows();
  saveFilterState();
  if (shouldUseOzonWorkingView()) {
    const nextOzonParams = ozonDiagnosticsParams();
    if (nextOzonParams !== previousOzonParams) {
      state.ozonDiagnosticsParams = nextOzonParams;
      loadOzonDiagnostics(currentClientLoadContext());
    } else {
      renderOzonWorkingView();
    }
    return;
  }
  loadReviewRows();
  const nextOzonParams = ozonDiagnosticsParams();
  if (nextOzonParams !== previousOzonParams) {
    state.ozonDiagnosticsParams = nextOzonParams;
    loadOzonDiagnostics(currentClientLoadContext());
  }
}

function selectRowsPreset(preset = "", options = {}) {
  state.rowPreset = preset || "";
  saveFilterState();
  syncRowsPresetButtons();
  if (options.load !== false) {
    applyRowsFilters();
  }
}

function syncRowsPresetButtons() {
  els.rowsPresetButtons.forEach((button) => {
    const selected = (button.dataset.rowPreset || "") === state.rowPreset;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", selected ? "true" : "false");
  });
}

function bindOnecReconciliationFilters() {
  [
    els.onecFilterStatus,
    els.onecFilterPeriodStart,
    els.onecFilterPeriodEnd,
    els.onecFilterCabinet,
    els.onecFilterOrganization,
    els.onecFilterDocumentType,
    els.onecFilterDeltaOnly,
  ].forEach((control) => {
    control.addEventListener("change", applyOnecReconciliationFilters);
  });
  els.onecFilterQuery.addEventListener(
    "input",
    debounce(applyOnecReconciliationFilters, 250),
  );
}

function applyOnecReconciliationFilters() {
  saveFilterState();
  loadOnecReconciliation(currentClientLoadContext());
}

function debounce(callback, delayMs) {
  let timeoutId = 0;
  return (...args) => {
    window.clearTimeout(timeoutId);
    timeoutId = window.setTimeout(() => callback(...args), delayMs);
  };
}

function selectDetailTab(tab = "products") {
  els.detailTabs.forEach((button) => {
    const selected = button.dataset.detailTab === tab;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", selected ? "true" : "false");
  });
  els.detailPanels.forEach((panel) => {
    const selected = panel.dataset.detailPanel === tab;
    panel.hidden = !selected;
    panel.classList.toggle("active", selected);
  });
  if (tab === "onecReconciliation" && !state.onecReconciliationLoaded) {
    loadOnecReconciliation(currentClientLoadContext());
  }
}

async function boot() {
  try {
    state.user = await api("/api/me");
    showCabinet();
    await loadClients();
  } catch (error) {
    showLogin();
    els.loginError.textContent =
      "Сессия временно занята длинной загрузкой. Откройте кабинет в инкогнито или подождите завершения полного обновления.";
  }
}

function isIntegrationsPage() {
  return window.location.pathname.replace(/\/+$/, "") === "/integrations";
}

function isAiPage() {
  return window.location.pathname.replace(/\/+$/, "") === "/ai";
}

function configurePageMode() {
  const integrationsPage = isIntegrationsPage();
  const aiPage = isAiPage();
  alignOzonDiagnosticsWithReportFlow();
  document.body.classList.toggle("integrations-page", integrationsPage);
  document.body.classList.toggle("ai-page", aiPage);
  els.reportOnlyControls.forEach((control) => {
    control.hidden = false;
  });
  els.reportPageSections.forEach((section) => {
    section.hidden = false;
  });
  if (integrationsPage && state.user) {
    openIntegrationsWidget({ focus: false });
  }
  if (aiPage && state.user && state.reportId) {
    openAiWidget({ focus: false });
  }
}

function alignOzonDiagnosticsWithReportFlow() {
  const analyticsPanel = document.querySelector("#analytics-panel");
  if (!analyticsPanel || !els.ozonDiagnosticsPanel) {
    return;
  }
  if (analyticsPanel.nextElementSibling !== els.ozonDiagnosticsPanel) {
    analyticsPanel.after(els.ozonDiagnosticsPanel);
  }
}

function renderAiPageHeader(title = "AI-аналитик отчета", subtitle = "") {
  els.reportTitle.textContent = title;
  els.reportSubtitle.textContent =
    subtitle || "Вопросы по уже рассчитанным фактам WB и 1C.";
}

function openAiWidget(options = {}) {
  els.aiWidgetOverlay.hidden = false;
  document.body.classList.add("widget-open");
  if (!state.reportId) {
    els.aiError.textContent = "Сначала выберите клиента и отчет.";
    return;
  }
  els.aiError.textContent = "";
  if (options.focus !== false) {
    window.setTimeout(() => els.aiInput.focus(), 0);
  }
}

function closeAiWidget() {
  els.aiWidgetOverlay.hidden = true;
  updateWidgetBodyState();
  if (isAiPage()) {
    window.history.replaceState({}, "", "/cabinet");
    document.body.classList.remove("ai-page");
  }
}

function openClientOutputWidget() {
  els.clientOutputWidgetOverlay.hidden = false;
  els.draftPanel.hidden = false;
  document.body.classList.add("widget-open");
  if (!state.reportId) {
    els.draftStatus.textContent = "Сначала выберите клиента и отчет.";
    return;
  }
  if (!els.draftStatus.textContent) {
    els.draftStatus.textContent = "Клиентский вывод еще не подготовлен.";
  }
  window.setTimeout(() => els.draftRefreshButton.focus(), 0);
}

function closeClientOutputWidget() {
  els.clientOutputWidgetOverlay.hidden = true;
  updateWidgetBodyState();
}

function openIntegrationsWidget(options = {}) {
  els.integrationsWidgetOverlay.hidden = false;
  els.integrationsPanel.hidden = false;
  document.body.classList.add("widget-open");
  syncSelectedClientFromControl();
  if (!state.clientId) {
    renderIntegrationsEmpty(
      "Клиент не выбран",
      "Выберите клиента в верхней панели, чтобы посмотреть подключения WB и 1C.",
    );
    return;
  }
  if (!isStaffUser()) {
    renderIntegrationsEmpty(
      "Нет доступа",
      "Раздел интеграций доступен только консультанту или администратору.",
    );
    return;
  }
  if (options.reload !== false) {
    renderIntegrationsEmpty(
      "Загружаем интеграции",
      "Получаем read-only подключения выбранного клиента.",
    );
    loadIntegrations(currentClientLoadContext());
  }
  if (options.focus !== false) {
    window.setTimeout(() => {
      const firstInput = els.integrationList.querySelector("input, select, button");
      firstInput?.focus();
    }, 0);
  }
}

function syncSelectedClientFromControl() {
  const selected = els.clientSelect.value || "";
  if (selected && selected !== state.clientId) {
    state.clientId = selected;
  }
}

function currentClientLoadContext() {
  return {
    clientId: state.clientId,
    clientLoadToken: state.clientLoadToken,
  };
}

function isCurrentClientLoad(context = {}) {
  const clientId = context.clientId || "";
  const clientLoadToken = context.clientLoadToken;
  if (clientId && clientId !== state.clientId) {
    return false;
  }
  return clientLoadToken === undefined || clientLoadToken === state.clientLoadToken;
}

function closeIntegrationsWidget() {
  els.integrationsWidgetOverlay.hidden = true;
  updateWidgetBodyState();
  if (isIntegrationsPage()) {
    window.history.replaceState({}, "", "/cabinet");
    document.body.classList.remove("integrations-page");
  }
}

function openNewClientWidget() {
  if (!canCreateClient()) {
    return;
  }
  els.newClientForm.reset();
  els.newClientStatus.textContent = "";
  els.newClientSubmit.disabled = false;
  els.newClientWidgetOverlay.hidden = false;
  document.body.classList.add("widget-open");
  els.newClientName.focus();
}

function closeNewClientWidget() {
  els.newClientWidgetOverlay.hidden = true;
  updateWidgetBodyState();
}

async function onNewClientSubmit(event) {
  event.preventDefault();
  if (!canCreateClient() || els.newClientSubmit.disabled) {
    return;
  }
  const name = els.newClientName.value.trim();
  if (!name) {
    els.newClientStatus.textContent = "Введите название клиента.";
    return;
  }
  els.newClientSubmit.disabled = true;
  els.newClientStatus.textContent = "Создаем клиента...";
  try {
    const payload = await api("/api/clients", {
      method: "POST",
      body: JSON.stringify({
        name,
        tenant_id: els.newClientTenantId.value.trim(),
        client_id: els.newClientClientId.value.trim(),
        companies: splitLines(els.newClientCompanies.value),
        cabinets: splitLines(els.newClientCabinets.value),
      }),
    });
    const created = payload.client || {};
    state.clients = upsertClientOption(state.clients, created);
    renderClientSelect();
    closeNewClientWidget();
    await selectClient(created.clientId || created.id);
    openIntegrationsWidget({ focus: false });
  } catch (error) {
    els.newClientStatus.textContent = clientCreateErrorMessage(error);
  } finally {
    els.newClientSubmit.disabled = false;
  }
}

function clientCreateErrorMessage(error) {
  const message = String(error?.message || "");
  if (error?.status === 401) {
    return "Сессия истекла. Войдите снова и создайте клиента.";
  }
  if (error?.status === 403) {
    return "Создать клиента может только консультант или администратор.";
  }
  if (error?.status === 405) {
    return "Сервер еще не подхватил обновление. Нужен перезапуск серверной части.";
  }
  if (error?.status === 422) {
    return "Проверьте поля: название, коды, организации и WB-кабинеты.";
  }
  if (message.includes("tenant already exists")) {
    return "Такой код контура уже используется. Укажите другой код или откройте существующего клиента.";
  }
  if (message.includes("tenant already has a client")) {
    return "Для этого контура уже есть клиент. Укажите отдельный код контура.";
  }
  if (message.includes("client id is required")) {
    return "Не удалось сформировать код клиента. Заполните название или код клиента вручную.";
  }
  return message && !message.startsWith("HTTP ")
    ? message
    : "Не удалось создать клиента.";
}

function splitLines(value) {
  return String(value || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function upsertClientOption(clients, client) {
  if (!client || !(client.clientId || client.id)) {
    return clients;
  }
  const clientId = client.clientId || client.id;
  const rest = clients.filter((item) => (item.clientId || item.id) !== clientId);
  return [...rest, client].sort((left, right) =>
    String(left.name || left.clientId || left.id).localeCompare(
      String(right.name || right.clientId || right.id),
      "ru",
    ),
  );
}

function openDrilldownWidget(preset = "review") {
  els.drilldownWidgetOverlay.hidden = false;
  document.body.classList.add("widget-open");
  selectDrilldownPreset(preset);
}

function closeDrilldownWidget() {
  els.drilldownWidgetOverlay.hidden = true;
  updateWidgetBodyState();
}

async function selectDrilldownPreset(preset = "review") {
  const descriptor = drilldownDescriptor(preset);
  els.drilldownTitle.textContent = descriptor.title;
  els.drilldownSubtitle.textContent = descriptor.subtitle;
  els.drilldownTabs.forEach((button) => {
    const selected = button.dataset.drilldownPreset === descriptor.preset;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", selected ? "true" : "false");
  });
  if (descriptor.preset === "sources") {
    els.drilldownTableWrap.hidden = true;
    els.drilldownSources.hidden = false;
    renderSourceDrilldown();
    return;
  }
  els.drilldownSources.hidden = true;
  els.drilldownTableWrap.hidden = false;
  await loadDrilldownRows(descriptor.preset);
}

async function loadDrilldownRows(preset) {
  if (!state.reportId) {
    return;
  }
  els.drilldownCount.textContent = "Загружаем строки...";
  els.filterQuery.value = "";
  els.filterStatus.value = "";
  const params = rowsFilterParams(preset);
  const payload = await api(`/api/reports/${encodeURIComponent(state.reportId)}/rows?${params}`);
  renderDrilldownRows(payload.items || [], payload.total || 0);
}

function drilldownDescriptor(preset) {
  return {
    sources: {
      preset: "sources",
      title: "Источники и последняя выгрузка",
      subtitle: "Показывает, что именно помешало обновить WB/1C-источники.",
    },
    missingCost: {
      preset: "missingCost",
      title: "Строки без себестоимости",
      subtitle: "Товары, где не подтянулась подтвержденная себестоимость из 1С.",
    },
    missingMapping: {
      preset: "missingMapping",
      title: "Проблемы mapping WB ↔ 1C",
      subtitle: "Товары без сопоставления WB-1С или с неоднозначным mapping.",
    },
    losses: {
      preset: "losses",
      title: "Убыточные строки",
      subtitle: "Строки с отрицательной прибылью для проверки экономики.",
    },
    review: {
      preset: "review",
      title: "Все строки к проверке",
      subtitle: "Все строки со статусом, отличным от OK, с учетом выбранных фильтров.",
    },
  }[preset] || {
    preset: "review",
    title: "Все строки к проверке",
    subtitle: "Все строки со статусом, отличным от OK, с учетом выбранных фильтров.",
  };
}

function closeAllWidgets() {
  closeAiWidget();
  closeClientOutputWidget();
  closeIntegrationsWidget();
  closeNewClientWidget();
  closeDrilldownWidget();
}

function updateWidgetBodyState() {
  document.body.classList.toggle(
    "widget-open",
      !els.aiWidgetOverlay.hidden ||
      !els.clientOutputWidgetOverlay.hidden ||
      !els.integrationsWidgetOverlay.hidden ||
      !els.drilldownWidgetOverlay.hidden,
  );
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
  state.integrationItems = [];
  state.editingIntegrationKey = "";
  state.draftIntegration = null;
  closeAllWidgets();
  els.integrationsPanel.hidden = true;
  els.integrationsOpenButton.hidden = true;
  els.newClientButton.hidden = true;
  showLogin();
}

async function loadClients() {
  const payload = await api("/api/clients");
  state.clients = payload.items || state.user?.clients || [];
  renderClientSelect();
  if (!state.clients.length) {
    resetClientScopedState();
    if (isIntegrationsPage()) {
      setEmptyCabinet(
        "Нет доступных клиентов",
        "После назначения клиента здесь появятся интеграции.",
      );
      renderIntegrationsEmpty(
        "Клиент не выбран",
        "Назначьте клиентский контур пользователю, чтобы открыть подключения.",
      );
      openIntegrationsWidget({ focus: false });
    } else if (isAiPage()) {
      renderAiPageHeader(
        "Нет доступных клиентов",
        "После назначения клиента здесь появится AI-аналитик отчета.",
      );
    } else {
      setEmptyCabinet("Нет доступных клиентов", "После назначения клиента здесь появится витрина.");
    }
    return;
  }
  const savedClientId = savedFilterState().clientId || "";
  const savedClient = savedClientId
    ? state.clients.find((client) => (client.clientId || client.id) === savedClientId)
    : null;
  if (savedClient) {
    await selectClient(savedClient.clientId || savedClient.id);
    return;
  }
  if (state.clients.length === 1) {
    await selectClient(state.clients[0].clientId || state.clients[0].id);
    return;
  }
  resetClientScopedState();
  if (isIntegrationsPage()) {
    openIntegrationsWidget({ focus: false });
  } else if (isAiPage()) {
    renderAiPageHeader(
      "Выберите клиента",
      "AI-аналитик загрузит текущий отчет после выбора клиентского контура.",
    );
  } else {
    setEmptyCabinet("Выберите клиента", "Отчеты загрузятся после выбора клиентского контура.");
  }
}

async function selectClient(clientId) {
  if (!clientId) {
    resetClientScopedState();
    if (isIntegrationsPage()) {
      setEmptyCabinet(
        "Выберите клиента",
        "Интеграции загрузятся после выбора клиентского контура.",
      );
      renderIntegrationsEmpty(
        "Клиент не выбран",
        "Выберите клиента в верхней панели, чтобы посмотреть подключения WB и 1C.",
      );
      openIntegrationsWidget({ focus: false });
    } else if (isAiPage()) {
      renderAiPageHeader(
        "Выберите клиента",
        "AI-аналитик загрузит текущий отчет после выбора клиентского контура.",
      );
    } else {
      setEmptyCabinet("Выберите клиента", "Отчеты загрузятся после выбора клиентского контура.");
    }
    return;
  }
  state.clientId = clientId;
  els.clientSelect.value = clientId;
  saveSelectedClientId();
  resetClientScopedState({ keepClient: true });
  syncIntegrationsEntryPoint();
  if (!isIntegrationsPage() && !isAiPage()) {
    setEmptyCabinet(
      "Загружаем клиента",
      "Получаем отчеты выбранного клиентского контура.",
    );
  }
  await loadReports(currentClientLoadContext());
}

async function loadReports(context = currentClientLoadContext()) {
  const clientId = context.clientId || state.clientId;
  if (!clientId) {
    if (isAiPage()) {
      renderAiPageHeader(
        "Выберите клиента",
        "AI-аналитик загрузит текущий отчет после выбора клиентского контура.",
      );
    } else {
      setEmptyCabinet("Выберите клиента", "Отчеты загрузятся после выбора клиентского контура.");
    }
    return;
  }
  const payload = await api(
    `/api/clients/${encodeURIComponent(clientId)}/reports`,
  );
  if (!isCurrentClientLoad(context)) {
    return;
  }
  state.reports = payload.items || [];
  if (!state.reports.length) {
    renderFilters(clientScopedFilterOptions());
    await loadIntegrations(context);
    if (isAiPage()) {
      renderAiPageHeader(
        "Нет доступных отчетов",
        "После импорта отчета AI-аналитик сможет отвечать по расчетной витрине.",
      );
    } else if (isIntegrationsPage()) {
      setEmptyCabinet();
      openIntegrationsWidget({ focus: false });
    } else {
      setEmptyCabinet();
      await loadOzonDiagnostics(context);
    }
    return;
  }
  await loadReport(state.reports[0].id, context);
}

async function loadReport(reportId, context = currentClientLoadContext()) {
  if (!isCurrentClientLoad(context)) {
    return;
  }
  state.reportId = reportId;
  state.aiThreadId = null;
  state.onecReconciliationLoaded = false;
  resetAiPanel();
  const [summary, freshness] = await Promise.all([
    api(`/api/reports/${encodeURIComponent(reportId)}/summary`),
    api(`/api/reports/${encodeURIComponent(reportId)}/freshness`),
  ]);
  if (!isCurrentClientLoad(context) || state.reportId !== reportId) {
    return;
  }
  state.summary = summary;
  state.freshness = freshness;
  renderReport();
  renderFilters(summary.options || {});
  renderOnecReconciliation([], 0, summary.quality || {});
  await Promise.all([
    loadReviewRows(state.rowPreset, { ...context, reportId }),
    loadClientDraft({ ...context, reportId }),
    loadIntegrations(context),
  ]);
  configurePageMode();
}

async function loadReviewRows(preset = state.rowPreset, context = {}) {
  if (shouldUseOzonWorkingView()) {
    renderOzonWorkingView();
    return;
  }
  const reportId = context.reportId || state.reportId;
  if (!reportId) {
    return;
  }
  const params = rowsFilterParams(preset);
  const payload = await api(`/api/reports/${encodeURIComponent(reportId)}/rows?${params}`);
  if (reportId !== state.reportId || !isCurrentClientLoad(context)) {
    return;
  }
  renderKpis(payload.kpis || {});
  const analytics = filteredAnalyticsSummary(payload);
  renderAnalytics(analytics);
  renderLiquidity(asArray(analytics.liquidityRows));
  renderLostSales(asArray(analytics.lostSales));
  renderReviewRows(payload.items || [], payload.total || 0);
}

function filteredAnalyticsSummary(payload = {}) {
  const analytics = payload.analytics || {};
  return {
    ...(state.summary || {}),
    ...analytics,
    kpis: payload.kpis || analytics.kpis || {},
    quality: analytics.quality || (state.summary || {}).quality || {},
  };
}

async function loadOnecReconciliation(context = {}) {
  const reportId = context.reportId || state.reportId;
  if (!reportId) {
    return;
  }
  els.onecReconciliationCount.textContent = "Загружаем сверку...";
  const params = onecReconciliationFilterParams();
  const payload = await api(
    `/api/reports/${encodeURIComponent(reportId)}/document-reconciliation?${params}`,
  );
  if (reportId !== state.reportId || !isCurrentClientLoad(context)) {
    return;
  }
  state.onecReconciliationLoaded = true;
  renderOnecReconciliation(payload.items || [], payload.total || 0, payload.kpis || {});
}

async function loadClientDraft(context = {}) {
  const reportId = context.reportId || state.reportId;
  if (!reportId) {
    return;
  }
  try {
    const payload = await api(
      `/api/reports/${encodeURIComponent(reportId)}/client-draft`,
    );
    if (reportId !== state.reportId || !isCurrentClientLoad(context)) {
      return;
    }
    els.draftPanel.hidden = false;
    if (!payload.latest) {
      els.draftStatus.textContent = "Черновик еще не подготовлен.";
      return;
    }
    const status = payload.latest.status === "ready" ? "готов" : "черновик";
    els.draftStatus.textContent = `Версия v${payload.latest.revision}: ${status}.`;
  } catch (error) {
    if (reportId !== state.reportId || !isCurrentClientLoad(context)) {
      return;
    }
    els.draftPanel.hidden = false;
    els.draftStatus.textContent = isStaffUser()
      ? "Клиентский вывод пока не подготовлен."
      : "Клиентский вывод готовит консультант. Данные отчета не менялись.";
  }
}

async function loadIntegrations(context = {}) {
  if (!context.clientId) {
    syncSelectedClientFromControl();
  }
  const clientId = context.clientId || state.clientId;
  if (!isStaffUser() || !clientId) {
    els.integrationsOpenButton.hidden = true;
    els.integrationsPanel.hidden = false;
    resetSourceRefreshPanel({ hide: true });
    renderIntegrationsEmpty(
      clientId ? "Нет доступа" : "Клиент не выбран",
      clientId
        ? "Раздел интеграций доступен только консультанту или администратору."
        : "Выберите клиента в верхней панели, чтобы посмотреть подключения WB и 1C.",
    );
    return;
  }
  let payload;
  try {
    payload = await api(
      `/api/clients/${encodeURIComponent(clientId)}/integrations`,
    );
  } catch (error) {
    if (!isCurrentClientLoad(context)) {
      return;
    }
    syncIntegrationsEntryPoint();
    els.integrationsPanel.hidden = false;
    resetSourceRefreshPanel({ hide: true });
    renderIntegrationsEmpty(
      "Интеграции не загрузились",
      "Проверьте доступ консультанта и попробуйте обновить страницу.",
    );
    return;
  }
  if (!isCurrentClientLoad(context)) {
    return;
  }
  els.integrationsOpenButton.hidden = false;
  els.integrationsPanel.hidden = false;
  state.integrationProviders = payload.providers || [];
  state.integrationItems = payload.items || [];
  renderIntegrationsWithFallback(state.integrationItems);
  await loadSourceRefreshStatus(context).catch(() => {
    if (!isCurrentClientLoad(context)) {
      return;
    }
    state.latestSourceRefresh = null;
    els.sourceRefreshStatus.textContent =
      "Не удалось загрузить статус обновления источников.";
    renderSourceRefreshSteps(null);
    els.sourceRefreshCollections.replaceChildren();
  });
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
  els.newClientButton.hidden = !canCreateClient();
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

function renderReport() {
  const summary = state.summary || {};
  const freshness = state.freshness || {};
  const readiness = summary.readiness || {};
  const sourceLoads = asArray(freshness.sourceLoads);

  els.reportTitle.textContent = "Пульт подготовки отчета";
  els.reportSubtitle.textContent = "";
  els.excelLink.href = `/api/reports/${encodeURIComponent(state.reportId)}/export.xlsx`;

  renderReadiness(readiness);
  const latestRefresh = summary.latestSourceRefresh || freshness.latestSourceRefresh;
  renderNextAction({
    readiness,
    quality: summary.quality || {},
    sourceLoads,
    refresh: latestRefresh,
  });
  renderCommandChecklist({
    readiness,
    quality: summary.quality || {},
    sourceLoads,
    refresh: latestRefresh,
  });
  renderQuality(summary.quality || {}, sourceLoads, readiness);
  renderKpis(summary.kpis || {});
  renderAnalytics(summary);
  renderOzonPreview(latestRefresh, state.latestOzonDiagnostics);
  renderLiquidity(asArray(summary.liquidityRows));
  renderLostSales(asArray(summary.lostSales));
  const blockingReasons = asArray(readiness.blockingReasons);
  const reviewReasons = asArray(readiness.reviewReasons);
  const visibleBlockingReasons = blockingReasons.filter((reason) => !isTaskReviewed(reason));
  const visibleReviewReasons = reviewReasons.filter((reason) => !isTaskReviewed(reason));
  renderReasons(
    els.blockingReasons,
    visibleBlockingReasons,
    blockingReasons.length
      ? "Срочные задачи проверены."
      : "Блокеров нет, можно идти к проверкам ниже.",
    "blocker",
  );
  renderReasons(
    els.reviewReasons,
    visibleReviewReasons,
    reviewReasons.length
      ? "Проверки отмечены как разобранные."
      : "Дополнительных проверок нет.",
    "review",
  );
  renderDoneTasks(readiness, [...blockingReasons, ...reviewReasons]);
}

function renderFilters(options) {
  const clientOptions = clientScopedFilterOptions();
  const cabinetOptions = mergedCabinetOptions(options.cabinets, clientOptions.cabinets);
  const organizationOptions = asArray(options.organizations).length
    ? options.organizations
    : clientOptions.organizations;
  setOptions(els.filterStatus, options.statuses || [], "Все статусы");
  setOptions(els.filterMonth, options.months || [], "Все месяцы");
  setDateBounds(els.filterPeriodStart, options.periodStart, options.periodEnd);
  setDateBounds(els.filterPeriodEnd, options.periodStart, options.periodEnd);
  setDateBounds(els.topbarPeriodStart, options.periodStart, options.periodEnd);
  setDateBounds(els.topbarPeriodEnd, options.periodStart, options.periodEnd);
  setOptions(els.filterCabinet, cabinetOptions, "Все кабинеты");
  setOptions(els.topbarCabinetSelect, cabinetOptions, "Все кабинеты МП");
  setOptions(els.filterOrganization, organizationOptions, "Все организации");
  setOptions(els.filterScheme, options.schemes || [], "Все схемы");
  setOptions(els.filterLossClass, options.lossClasses || [], "Все классы");
  setOptions(
    els.onecFilterStatus,
    options.documentReconciliationStatuses || [],
    "Все статусы",
  );
  setDateBounds(els.onecFilterPeriodStart, options.periodStart, options.periodEnd);
  setDateBounds(els.onecFilterPeriodEnd, options.periodStart, options.periodEnd);
  setOptions(els.onecFilterCabinet, cabinetOptions, "Все кабинеты");
  setOptions(
    els.onecFilterOrganization,
    organizationOptions,
    "Все организации",
  );
  setOptions(els.onecFilterDocumentType, options.documentTypes || [], "Все типы");
  restoreFilterState();
  syncTopbarFiltersFromRows();
  syncRowsPresetButtons();
}

function applyTopbarFilter(kind) {
  if (kind === "cabinet") {
    const previousOzonParams = state.ozonDiagnosticsParams || "";
    els.filterCabinet.value = els.topbarCabinetSelect.value;
    saveFilterState();
    const nextOzonParams = ozonDiagnosticsParams();
    const useOzonWorkingView = shouldUseOzonWorkingView();
    const hasCurrentOzonDiagnostics =
      useOzonWorkingView &&
      state.latestOzonDiagnostics &&
      nextOzonParams === previousOzonParams;
    if (nextOzonParams !== previousOzonParams && shouldShowOzonPreview()) {
      state.ozonDiagnosticsParams = nextOzonParams;
      loadOzonDiagnostics(currentClientLoadContext());
    } else if (hasCurrentOzonDiagnostics) {
      renderOzonDiagnosticsPayload(state.latestOzonDiagnostics);
    } else if (useOzonWorkingView) {
      renderOzonWorkingView();
    } else {
      renderOzonPreview(state.latestSourceRefresh, state.latestOzonDiagnostics);
      renderKpis((state.summary || {}).kpis || {});
      renderAnalytics(state.summary || {});
    }
    if (useOzonWorkingView) {
      if (!hasCurrentOzonDiagnostics) {
        renderOzonWorkingView();
      }
      return;
    }
  }
  if (kind === "periodRange") {
    els.filterPeriodStart.value = els.topbarPeriodStart.value;
    els.filterPeriodEnd.value = els.topbarPeriodEnd.value;
    els.filterMonth.value = "";
    state.ozonDiagnosticsParams = ozonDiagnosticsParams();
    saveFilterState();
    loadOzonDiagnostics(currentClientLoadContext());
    if (shouldUseOzonWorkingView()) {
      renderOzonWorkingView();
      return;
    }
  }
  loadReviewRows();
}

function syncTopbarFiltersFromRows() {
  els.topbarCabinetSelect.value = els.filterCabinet.value;
  if (els.filterMonth.value) {
    els.topbarPeriodStart.value = "";
    els.topbarPeriodEnd.value = "";
    return;
  }
  els.topbarPeriodStart.value = els.filterPeriodStart.value;
  els.topbarPeriodEnd.value = els.filterPeriodEnd.value;
}

function savedFilterState() {
  try {
    return JSON.parse(window.localStorage.getItem(FILTER_STATE_STORAGE_KEY) || "{}") || {};
  } catch (error) {
    return {};
  }
}

function writeFilterState(payload) {
  try {
    window.localStorage.setItem(FILTER_STATE_STORAGE_KEY, JSON.stringify(payload));
  } catch (error) {
    // Keeping filters is a convenience; the cabinet must work without localStorage.
  }
}

function saveSelectedClientId() {
  const saved = savedFilterState();
  if (saved.clientId && saved.clientId !== state.clientId) {
    writeFilterState({ clientId: state.clientId || "" });
    return;
  }
  writeFilterState({
    ...saved,
    clientId: state.clientId || "",
  });
}

function saveFilterState() {
  if (!state.clientId) {
    return;
  }
  writeFilterState({
    clientId: state.clientId,
    rowPreset: state.rowPreset || "",
    ozonUnitStatusFilter: state.ozonUnitStatusFilter || "",
    rows: {
      query: els.filterQuery.value,
      status: els.filterStatus.value,
      month: els.filterMonth.value,
      periodStart: els.filterPeriodStart.value,
      periodEnd: els.filterPeriodEnd.value,
      cabinet: els.filterCabinet.value,
      organization: els.filterOrganization.value,
      scheme: els.filterScheme.value,
      lossClass: els.filterLossClass.value,
    },
    onec: {
      query: els.onecFilterQuery.value,
      status: els.onecFilterStatus.value,
      periodStart: els.onecFilterPeriodStart.value,
      periodEnd: els.onecFilterPeriodEnd.value,
      cabinet: els.onecFilterCabinet.value,
      organization: els.onecFilterOrganization.value,
      documentType: els.onecFilterDocumentType.value,
      deltaOnly: els.onecFilterDeltaOnly.checked,
    },
  });
}

function restoreFilterState() {
  const saved = savedFilterState();
  if (!saved.clientId || saved.clientId !== state.clientId) {
    return;
  }
  const rows = saved.rows || {};
  els.filterQuery.value = rows.query || "";
  setSelectValue(els.filterStatus, rows.status || "");
  setSelectValue(els.filterMonth, rows.month || "");
  setDateFilterValue(els.filterPeriodStart, rows.periodStart || "");
  setDateFilterValue(els.filterPeriodEnd, rows.periodEnd || "");
  setSelectValue(els.filterCabinet, rows.cabinet || "");
  setSelectValue(els.filterOrganization, rows.organization || "");
  setSelectValue(els.filterScheme, rows.scheme || "");
  setSelectValue(els.filterLossClass, rows.lossClass || "");

  const onec = saved.onec || {};
  els.onecFilterQuery.value = onec.query || "";
  setSelectValue(els.onecFilterStatus, onec.status || "");
  setDateFilterValue(els.onecFilterPeriodStart, onec.periodStart || "");
  setDateFilterValue(els.onecFilterPeriodEnd, onec.periodEnd || "");
  setSelectValue(els.onecFilterCabinet, onec.cabinet || "");
  setSelectValue(els.onecFilterOrganization, onec.organization || "");
  setSelectValue(els.onecFilterDocumentType, onec.documentType || "");
  els.onecFilterDeltaOnly.checked = Boolean(onec.deltaOnly);

  state.rowPreset = saved.rowPreset || "";
  state.ozonUnitStatusFilter = saved.ozonUnitStatusFilter || "";
  if (els.ozonUnitStatusFilter) {
    setSelectValue(els.ozonUnitStatusFilter, state.ozonUnitStatusFilter);
    state.ozonUnitStatusFilter = els.ozonUnitStatusFilter.value;
  }
}

function setDateFilterValue(input, value) {
  const nextValue = String(value || "");
  if (!nextValue) {
    input.value = "";
    return;
  }
  if ((input.min && nextValue < input.min) || (input.max && nextValue > input.max)) {
    input.value = "";
    return;
  }
  input.value = nextValue;
}

function renderIntegrationsWithFallback(items) {
  try {
    renderIntegrations(items);
  } catch (error) {
    renderIntegrationsRecovery(items);
  }
}

function renderIntegrations(items) {
  state.integrationItems = asArray(items);
  const rows = buildIntegrationRows(items);
  if (state.draftIntegration) {
    rows.unshift(state.draftIntegration);
  }
  if (
    state.editingIntegrationKey &&
    !rows.some((item) => integrationRowKey(item) === state.editingIntegrationKey)
  ) {
    state.editingIntegrationKey = "";
  }
  updateIntegrationProviderTabs(rows);
  const filteredRows = integrationRowsForActiveProvider(rows);
  const manager = renderCabinetManagerSafe();
  els.integrationsStatus.textContent = state.integrationProviderFilter
    ? `${filteredRows.length} строк: ${integrationLabel(state.integrationProviderFilter)}`
    : `${rows.length} строк подключения`;
  if (!filteredRows.length) {
    els.integrationList.replaceChildren(
      manager,
      integrationEmptyNode(...integrationEmptyCopy()),
    );
    return;
  }
  const header = document.createElement("div");
  header.className = "integration-list-header";
  ["Подключение", "Роль", "Доступ", "Статус", "Действия"].forEach((label) => {
    const cell = document.createElement("span");
    cell.textContent = label;
    header.append(cell);
  });
  els.integrationList.replaceChildren(
    manager,
    header,
    ...filteredRows.map(renderIntegrationRowSafe),
  );
}

function renderIntegrationsRecovery(items) {
  const rows = asArray(items);
  const filteredRows = integrationRowsForActiveProvider(rows);
  try {
    updateIntegrationProviderTabs(rows);
  } catch (error) {
    // Keep the modal usable even if tab counters fail.
  }
  const count = filteredRows.length;
  els.integrationsStatus.textContent = count
    ? `${count} строк подключения`
    : "Список загружен в упрощенном виде";
  if (!count) {
    els.integrationList.replaceChildren(
      integrationEmptyNode(
        "Подключения не найдены",
        "Сервер ответил, но список пуст для выбранного фильтра.",
      ),
    );
    return;
  }
  const notice = integrationEmptyNode(
    "Список открыт в упрощенном виде",
    "Настройки доступны, но часть расширенного интерфейса временно отключена.",
  );
  const header = document.createElement("div");
  header.className = "integration-list-header";
  ["Подключение", "Роль", "Доступ", "Статус", "Действия"].forEach((label) => {
    const cell = document.createElement("span");
    cell.textContent = label;
    header.append(cell);
  });
  els.integrationList.replaceChildren(
    notice,
    header,
    ...filteredRows.map(renderIntegrationMinimalFallbackRow),
  );
}

function renderIntegrationMinimalFallbackRow(item) {
  const row = document.createElement("article");
  row.className = "integration-card integration-card--warning";
  const data = item || {};
  const providerBase = providerBaseFromIntegration(data);
  const title = document.createElement("h3");
  title.textContent =
    data.label ||
    data.cabinetName ||
    data.organizationName ||
    integrationLabel(providerBase);
  const meta = document.createElement("p");
  meta.className = "muted";
  meta.textContent = [
    integrationLabel(providerBase),
    data.cabinetName || data.organizationName || "",
  ]
    .filter(Boolean)
    .join(" · ");
  const identity = document.createElement("div");
  identity.className = "integration-identity";
  identity.append(title, meta);

  const summary = document.createElement("div");
  summary.className = "integration-compact-row";
  const role = document.createElement("span");
  role.className = "integration-read-badge integration-role-badge";
  role.textContent = data.readOnly === false ? "доступ" : "read-only";
  const access = document.createElement("span");
  access.className = "integration-read-badge";
  access.textContent = data.configured || data.secretHint ? "Доступ сохранен" : "Нужно настроить";
  const status = document.createElement("span");
  status.className = "integration-status-pill";
  status.textContent = data.lastCheck?.ok
    ? "Проверка пройдена"
    : data.status === "disabled"
      ? "Отключено"
      : data.configured || data.secretHint
        ? "Нужна проверка"
        : "Не настроено";
  summary.append(role, access, status);
  row.append(identity, summary);
  return row;
}

function renderCabinetManagerSafe() {
  try {
    return renderCabinetManager();
  } catch (error) {
    const fragment = document.createDocumentFragment();
    return fragment;
  }
}

function renderIntegrationRowSafe(item) {
  try {
    return renderIntegrationRow(item);
  } catch (error) {
    return renderIntegrationFallbackRow(item);
  }
}

function renderIntegrationFallbackRow(item) {
  const row = document.createElement("article");
  row.className = "integration-card integration-card--warning";
  const identity = document.createElement("div");
  identity.className = "integration-identity";
  const title = document.createElement("h3");
  title.textContent = integrationDefaultLabel(item);
  const label = document.createElement("p");
  label.className = "muted";
  label.textContent = "Карточка загружена в упрощенном виде. Можно обновить страницу или открыть настройку позже.";
  identity.append(title, label);

  const summary = document.createElement("div");
  summary.className = "integration-compact-row";
  const role = document.createElement("span");
  role.className = "integration-read-badge integration-role-badge";
  role.textContent = integrationRoleLabel(item);
  const access = document.createElement("span");
  access.className = `integration-read-badge ${integrationAccessClass(item)}`;
  access.textContent = integrationAccessText(item);
  const status = document.createElement("span");
  status.className = "integration-status-pill";
  status.textContent = integrationStatusText(item);
  summary.append(role, access, status);
  row.append(identity, summary);
  return row;
}

function updateIntegrationProviderTabs(rows) {
  const counts = new Map();
  asArray(rows).forEach((item) => {
    const providerBase = providerBaseFromIntegration(item);
    counts.set(providerBase, (counts.get(providerBase) || 0) + 1);
  });
  els.integrationProviderTabButtons.forEach((button) => {
    const providerBase = button.dataset.integrationProviderFilter || "";
    button.classList.toggle(
      "active",
      providerBase === state.integrationProviderFilter,
    );
    const count = providerBase
      ? counts.get(providerBase) || 0
      : asArray(rows).length;
    button.dataset.count = String(count);
  });
}

function integrationRowsForActiveProvider(rows) {
  const providerBase = state.integrationProviderFilter;
  if (!providerBase) {
    return rows;
  }
  return asArray(rows).filter(
    (item) => providerBaseFromIntegration(item) === providerBase,
  );
}

function providerBaseFromIntegration(item) {
  return String(item.providerBase || item.provider || "").split(":")[0];
}

function integrationEmptyCopy() {
  if (state.integrationProviderFilter === "ozon_api") {
    return [
      "Ozon еще не подключен",
      "В форме выше выбран Ozon Seller API. Заполните Client-Id и API Key, затем сохраните и проверьте.",
    ];
  }
  if (state.integrationProviderFilter === "onec_readonly") {
    return [
      "1C еще не подключена",
      "В форме выше выбран 1C read-only. Заполните URL, пользователя и пароль.",
    ];
  }
  if (state.integrationProviderFilter === "wb_api") {
    return [
      "WB еще не подключен",
      "Добавьте кабинет клиента и сохраните read-only WB ключ.",
    ];
  }
  return [
    "Подключений пока нет",
    "Добавьте WB-кабинет или организацию клиента, затем сохраните ключ в отдельной строке.",
  ];
}

async function loadSourceRefreshStatus(context = {}) {
  const clientId = context.clientId || state.clientId;
  if (!isStaffUser() || !clientId) {
    resetSourceRefreshPanel({ hide: true });
    return;
  }
  els.sourceRefreshPanel.hidden = false;
  els.sourceRefreshStatus.textContent = "Проверяем последний refresh...";
  try {
    const payload = await api(
      `/api/clients/${encodeURIComponent(clientId)}/source-refresh/latest`,
    );
    if (!isCurrentClientLoad(context)) {
      return;
    }
    state.latestSourceRefresh = payload.latest || null;
    renderSourceRefreshControl(state.latestSourceRefresh);
    await loadOzonDiagnostics(context);
  } catch (error) {
    if (!isCurrentClientLoad(context)) {
      return;
    }
    state.latestSourceRefresh = null;
    state.latestOzonDiagnostics = null;
    els.sourceRefreshStatus.textContent =
      "Не удалось загрузить статус обновления источников.";
    renderSourceRefreshSteps(null);
    els.sourceRefreshCollections.replaceChildren();
    renderOzonPreview(null, null);
  }
}

async function loadOzonDiagnostics(context = {}) {
  const clientId = context.clientId || state.clientId;
  if (!isStaffUser() || !clientId) {
    state.latestOzonDiagnostics = null;
    updateOzonExcelLink(null);
    renderOzonPreview(state.latestSourceRefresh, null);
    return;
  }
  let diagnostics = null;
  let params = "";
  try {
    params = ozonDiagnosticsParams();
    state.ozonDiagnosticsParams = params;
    diagnostics = await api(
      `/api/clients/${encodeURIComponent(clientId)}/ozon-diagnostics?${params}`,
    );
  } catch (error) {
    if (!isCurrentClientLoad(context)) {
      return;
    }
    state.latestOzonDiagnostics = {
      status: "error",
      message: "Не удалось загрузить Ozon-диагностику.",
      collections: [],
    };
    updateOzonExcelLink(null);
    renderOzonPreview(state.latestSourceRefresh, state.latestOzonDiagnostics);
    if (shouldRenderOzonAnalytics()) {
      renderOzonKpis(state.latestOzonDiagnostics);
      renderOzonAnalytics(state.latestOzonDiagnostics);
    }
    return;
  }
  if (!isCurrentClientLoad(context) || params !== state.ozonDiagnosticsParams) {
    return;
  }
  state.latestOzonDiagnostics = diagnostics;
  renderOzonDiagnosticsPayload(diagnostics);
}

function renderOzonDiagnosticsPayload(diagnostics = state.latestOzonDiagnostics) {
  try {
    updateOzonExcelLink(diagnostics);
    renderOzonPreview(state.latestSourceRefresh, diagnostics);
    if (shouldRenderOzonAnalytics()) {
      renderOzonKpis(diagnostics);
      renderOzonAnalytics(diagnostics);
    }
    if (shouldRenderOzonMartInReportRows()) {
      renderOzonMartReportRows();
    }
  } catch (error) {
    console.error("Ozon diagnostics render failed", error);
    if (els.ozonDiagnosticMessage) {
      els.ozonDiagnosticMessage.className = "ozon-diagnostic-message warning";
      els.ozonDiagnosticMessage.textContent =
        "Ozon-данные загружены, но один из блоков витрины не отрисовался.";
    }
  }
}

function ozonDiagnosticsParams() {
  const params = new URLSearchParams();
  params.set("limit", "50");
  if (els.filterPeriodStart.value) {
    params.set("period_start", els.filterPeriodStart.value);
  }
  if (els.filterPeriodEnd.value) {
    params.set("period_end", els.filterPeriodEnd.value);
  }
  const cabinetId = selectedMarketplaceCabinetId();
  if (cabinetId && isOzonMarketplaceCabinet(selectedMarketplaceCabinet())) {
    params.set("wb_cabinet_id", cabinetId);
  }
  return params.toString();
}

function ozonDiagnosticsExportParams() {
  const params = new URLSearchParams(ozonDiagnosticsParams());
  params.delete("limit");
  return params.toString();
}

function updateOzonExcelLink(diagnostics = state.latestOzonDiagnostics) {
  if (!els.ozonExcelLink) {
    return;
  }
  const clientId = state.clientId;
  const hasExport = Boolean(isStaffUser() && clientId && diagnostics?.latestRun);
  els.ozonExcelLink.hidden = !hasExport;
  if (!hasExport) {
    els.ozonExcelLink.href = "#";
    return;
  }
  const params = ozonDiagnosticsExportParams();
  els.ozonExcelLink.href =
    `/api/clients/${encodeURIComponent(clientId)}/ozon-diagnostics/export.xlsx` +
    (params ? `?${params}` : "");
}

function renderSourceRefreshControl(refresh) {
  els.sourceRefreshPanel.hidden = false;
  renderSourceRefreshSteps(refresh);
  if (!refresh) {
    const title = document.createElement("strong");
    title.textContent = "Загрузок еще не было.";
    const copy = document.createElement("span");
    copy.textContent =
      "Загрузите сопоставление, проверьте готовность и запустите полное обновление.";
    els.sourceRefreshStatus.replaceChildren(title, copy);
    els.sourceRefreshCollections.replaceChildren(
      sourceRefreshEmptyActionNode(),
    );
    setSourceRefreshActiveLock(false);
    scheduleSourceRefreshPolling(null);
    return;
  }

  const active = isActiveSourceRefresh(refresh);
  els.sourceRefreshStatus.replaceChildren(
    sourceRefreshStatusLine("Статус", sourceStatusText(refresh.status)),
    sourceRefreshStatusLine("Режим", refresh.mode || "-"),
    sourceRefreshStatusLine("Период", sourcePeriodText(refresh)),
    sourceRefreshStatusLine(
      normalize(refresh.mode) === "ozon-only" ? "Диагностика" : "Отчет",
      refresh.newReportRunId ||
        (normalize(refresh.mode) === "ozon-only"
          ? active
            ? "готовится"
            : "готова без отчета"
          : active
            ? "создается"
            : "не создан"),
    ),
  );
  const collections = asArray(refresh.collections);
  const nodes = [sourceRefreshCompactMessage(refresh)];
  if (collections.length) {
    nodes.push(...collections.map(sourceRefreshCollectionChip));
  } else {
    nodes.push(sourceRefreshEmptyDetailsNode(refresh));
  }
  els.sourceRefreshCollections.replaceChildren(...nodes);
  setSourceRefreshActiveLock(active);
  scheduleSourceRefreshPolling(refresh);
}

function renderSourceRefreshSteps(refresh) {
  const steps = sourceRefreshSteps(refresh);
  els.sourceRefreshSteps.replaceChildren(
    ...steps.map((step, index) => {
      const item = document.createElement("li");
      item.className = `source-refresh-step is-${step.state}`;
      item.setAttribute("aria-current", step.state === "active" ? "step" : "false");
      const marker = document.createElement("span");
      marker.className = "source-refresh-step-marker";
      marker.textContent = step.state === "done" ? "✓" : String(index + 1);
      const label = document.createElement("span");
      label.className = "source-refresh-step-label";
      label.textContent = step.label;
      item.append(marker, label);
      return item;
    }),
  );
}

function sourceRefreshSteps(refresh) {
  const status = normalize(refresh?.status);
  const isOzonOnly = normalize(refresh?.mode) === "ozon-only";
  const hasSelectedMapping = Boolean(els.sourceRefreshMappingFile?.files?.[0]);
  const isActive = isActiveSourceRefresh(refresh);
  const hasReport = Boolean(refresh?.newReportRunId);
  const reportCreated = status === "report_created" || hasReport;
  const refreshCompleted =
    ["ok", "loaded", "success", "ready", "completed"].includes(status) ||
    (isOzonOnly && status === "source_loaded" && !isActive);
  const checkPassed = [
    "dry_run_ready",
    "queued",
    "running",
    "source_loaded",
    "rebuilding",
  ].includes(status) || refreshCompleted || reportCreated;
  const mappingReady =
    hasSelectedMapping ||
    isActive ||
    reportCreated ||
    status === "dry_run_ready" ||
    refreshCompleted ||
    sourceRefreshHasReadyMapping(refresh);
  return [
    {
      label: "Сопоставление",
      state: mappingReady ? "done" : "active",
    },
    {
      label: "Проверка",
      state: checkPassed
        ? "done"
        : mappingReady
          ? "active"
          : "pending",
    },
    {
      label: "Обновление",
      state: reportCreated || refreshCompleted ? "done" : isActive ? "active" : "pending",
    },
    {
      label: isOzonOnly ? "Диагностика" : "Отчет",
      state: reportCreated ? "done" : refreshCompleted ? "active" : "pending",
    },
  ];
}

function sourceRefreshHasReadyMapping(refresh) {
  return asArray(refresh?.collections).some((item) => {
    const sourceType = normalize(item.sourceType || item.source_type);
    const status = normalize(item.status);
    return (
      sourceType === "sku_mapping" &&
      ["ok", "loaded", "success", "ready", "completed"].includes(status)
    );
  });
}

function sourceRefreshCompactMessage(refresh) {
  const node = document.createElement("div");
  node.className = `source-refresh-compact-status ${sourceStatusTone(refresh.status)}`;
  const title = document.createElement("strong");
  title.textContent =
    normalize(refresh.status) === "dry_run_ready"
      ? "Готово к полному обновлению. Отчет еще не создан."
      : refresh.safeMessage || sourceStatusHint(refresh.status);
  const meta = document.createElement("span");
  meta.textContent = sourceRefreshAdvice(refresh.status);
  node.append(title, meta);
  return node;
}

function sourceRefreshCollectionChip(item) {
  const chip = document.createElement("div");
  chip.className = `source-refresh-chip ${sourceStatusTone(item.status)}`;
  const title = document.createElement("strong");
  title.textContent = item.sourceLabel || item.sourceType || "Источник";
  const meta = document.createElement("span");
  meta.textContent = [
    sourceStatusText(item.status),
    item.required === false ? "optional" : "required",
    `${number(item.rowCount || 0)} строк`,
  ].join(" · ");
  chip.append(title, meta);
  return chip;
}

function renderOzonPreview(refresh, diagnostics = state.latestOzonDiagnostics) {
  if (
    !els.ozonPreviewSummary ||
    !els.ozonPreviewCount ||
    !els.ozonPreviewGrid ||
    !els.ozonVitrineStatus ||
    !els.ozonIssueList ||
    !els.ozonIssueEmpty ||
    !els.ozonPnlMessage ||
    !els.ozonPnlGrid ||
    !els.ozonPnlEmpty ||
    !els.ozonUnitEmpty ||
    !els.ozonUnitRows ||
    !els.ozonBuyoutEmpty ||
    !els.ozonBuyoutRows ||
    !els.ozonDiagnosticMessage ||
    !els.ozonPreviewEmpty ||
    !els.ozonPreviewRows ||
    !els.ozonMappingEmpty ||
    !els.ozonMappingRows
  ) {
    return;
  }
  const visible = shouldShowOzonPreview(diagnostics);
  if (els.ozonDiagnosticsPanel) {
    els.ozonDiagnosticsPanel.hidden = !visible;
  }
  if (els.ozonTab) {
    els.ozonTab.hidden = !visible;
  }
  if (!visible) {
    if (
      document.querySelector('[data-detail-tab="ozon"]')?.classList.contains("active")
    ) {
      selectDetailTab("products");
    }
    clearOzonPreview();
    return;
  }

  const diagnosticCollections = asArray(diagnostics?.collections);
  const collections = diagnosticCollections.length
    ? diagnosticCollections
    : ozonCollections(refresh);
  const visibleCollections = collections.filter((item) => !isOzonCashFlowSource(item));
  const sourceSummary = diagnostics?.sourceSummary || {};
  const mappingSummary = sourceSummary.mapping || {};
  const onecSummary = sourceSummary.onec || {};
  const realizationSummary = sourceSummary.ozonRealization || {};
  const productSummary = sourceSummary.ozonProducts || {};
  const extraSummary = sourceSummary.ozonExtra || {};
  const buyoutSummary = diagnostics?.ozonBuyouts || {};
  const buyoutCheckSummary = buyoutSummary.summary || {};
  const ozonMapping = diagnostics?.ozonMapping || {};
  const issues = diagnostics?.issues || {};
  const pnl = diagnostics?.pnl || {};
  const reconciliation = diagnostics?.reconciliation || {};
  const expenseReconciliation = diagnostics?.expenseReconciliation || {};
  const mappingCheckRows = asArray(ozonMapping.rows);
  const mappingCheckSummary = ozonMapping.summary || {};
  const blockingIssues = Number(issues.blockingCount || 0);
  const reviewIssues = Number(issues.reviewCount || 0);
  const issueCount = blockingIssues + reviewIssues;
  const onecLoadedLabel = onecSummary.required
    ? `${number(onecSummary.loaded || 0)} / ${number(onecSummary.required || 0)}`
    : number(onecSummary.loaded || 0);

  if (diagnostics?.latestRun) {
    els.ozonPreviewSummary.textContent = `Ozon + 1C: ${sourceStatusText(
      diagnostics.latestRun.status,
    )}, ${sourcePeriodText(diagnostics.latestRun)}.`;
  } else if (diagnostics?.message) {
    els.ozonPreviewSummary.textContent = diagnostics.message;
  } else {
    els.ozonPreviewSummary.textContent = refresh
      ? `Последний refresh: ${sourceStatusText(refresh.status)}, ${sourcePeriodText(refresh)}.`
      : "Refresh еще не запускался для выбранного клиента.";
  }
  els.ozonPreviewCount.textContent = Number(realizationSummary.rowCount || 0)
    ? `Ozon реализации: ${number(realizationSummary.rowCount || 0)} строк`
    : visibleCollections.length
      ? `${visibleCollections.length} источников`
      : "Нет источников";
  els.ozonDiagnosticMessage.className = `ozon-diagnostic-message ${ozonDiagnosticTone(
    diagnostics,
  )}`;
  els.ozonDiagnosticMessage.textContent =
    diagnostics?.message ||
    "Полноценный Ozon-отчет пока не создается: здесь показана диагностика источников.";
  renderMetrics(els.ozonPreviewGrid, [
    [
      "Ozon реализации",
      number(realizationSummary.rowCount || 0),
      "аналог выкупов",
      realizationSummary.loaded ? "ok" : "warning",
    ],
    [
      "Сопоставление",
      number(mappingSummary.rowCount || 0),
      diagnostics?.readiness?.mappingLoaded ? "загружен" : "нужна проверка",
      diagnostics?.readiness?.mappingLoaded ? "ok" : "warning",
    ],
    [
      "Товары Ozon",
      number(productSummary.rowCount || ozonMapping.rowCount || 0),
      productSummary.loaded ? "каталог загружен" : "нужен каталог",
      productSummary.loaded ? "ok" : "warning",
    ],
    [
      "Доп. Ozon",
      number(extraSummary.rowCount || 0),
      extraSummary.loaded ? "для сверки" : "проверить доступ",
      extraSummary.loaded ? "ok" : "warning",
    ],
    [
      "Выкупы Ozon",
      number(buyoutSummary.rowCount || 0),
      buyoutSummary.rowCount
        ? `${number(buyoutCheckSummary.foundInOzonApi || 0)} сверено / ${number(
            buyoutCheckSummary.missingInOzonApi || 0,
          )} нет`
        : "1C накладных нет",
      Number(buyoutCheckSummary.missingInOzonApi || 0) ? "warning" : "ok",
    ],
    [
      "Ozon → 1C",
      `${number(mappingCheckSummary.matched || 0)} / ${number(
        ozonMapping.checkedRows || 0,
      )}`,
      "сопоставлено",
      ozonMapping.status === "ready" ? "ok" : "warning",
    ],
    [
      "Ошибки",
      number(issueCount),
      issueCount ? "к проверке" : "критичных нет",
      blockingIssues ? "bad" : issueCount ? "warning" : "ok",
    ],
    [
      "1C",
      onecLoadedLabel,
      "обязательные источники",
      diagnostics?.readiness?.onecRequiredLoaded ? "ok" : "warning",
    ],
  ]);
  if (els.ozonIssuesPanel) {
    els.ozonIssuesPanel.hidden = true;
  }
  const showDiagnosticCalculation = !shouldUseOzonWorkingView();
  setOzonDiagnosticCalculationSectionsVisible(showDiagnosticCalculation);
  renderOzonIssues(issues);
  if (showDiagnosticCalculation) {
    renderOzonPnl(pnl, reconciliation, expenseReconciliation);
    renderOzonUnitEconomics(diagnostics?.ozonMart || diagnostics?.unitRows || {}, pnl);
  }
  renderOzonBuyouts(buyoutSummary);
  els.ozonPreviewEmpty.hidden = visibleCollections.length > 0 || Boolean(diagnostics);
  els.ozonPreviewRows.replaceChildren(
    ...visibleCollections.map((item) => ozonPreviewRowNode(item)),
  );
  els.ozonMappingEmpty.hidden = mappingCheckRows.length > 0;
  els.ozonMappingEmpty.textContent =
    ozonMapping.message || "Нужен Ozon catalog: товары, offer_id, SKU и штрихкоды.";
  els.ozonMappingRows.replaceChildren(
    ...mappingCheckRows.map((item) => ozonMappingRowNode(item)),
  );
}

function setOzonDiagnosticCalculationSectionsVisible(visible) {
  if (els.ozonPnlSection) {
    els.ozonPnlSection.hidden = !visible;
  }
  const unitSection = els.ozonUnitRows?.closest(".ozon-table-section");
  if (unitSection) {
    unitSection.hidden = !visible;
  }
}

function clearOzonPreview() {
  if (!els.ozonPreviewSummary) {
    return;
  }
  els.ozonPreviewSummary.textContent = "Ozon-диагностика доступна консультанту.";
  els.ozonPreviewCount.textContent = "";
  els.ozonPreviewGrid.replaceChildren();
  els.ozonVitrineStatus.textContent = "";
  els.ozonVitrineStatus.className = "status-pill";
  if (els.ozonIssuesPanel) {
    els.ozonIssuesPanel.hidden = true;
  }
  els.ozonIssueList.replaceChildren();
  els.ozonIssueEmpty.hidden = true;
  els.ozonPnlMessage.textContent = "";
  els.ozonPnlMessage.className = "ozon-diagnostic-message";
  els.ozonPnlGrid.replaceChildren();
  els.ozonPnlEmpty.hidden = true;
  state.ozonUnitStatusFilter = "";
  if (els.ozonUnitStatusFilter) {
    els.ozonUnitStatusFilter.value = "";
  }
  els.ozonUnitEmpty.hidden = true;
  els.ozonUnitRows.replaceChildren();
  els.ozonBuyoutEmpty.hidden = true;
  els.ozonBuyoutRows.replaceChildren();
  els.ozonDiagnosticMessage.textContent = "";
  els.ozonDiagnosticMessage.className = "ozon-diagnostic-message";
  els.ozonPreviewEmpty.hidden = false;
  els.ozonPreviewRows.replaceChildren();
  els.ozonMappingEmpty.hidden = false;
  els.ozonMappingRows.replaceChildren();
}

function renderOzonPnl(pnl = {}, reconciliation = {}, expenseReconciliation = {}) {
  const status = normalize(pnl.status);
  if (els.ozonPnlSection) {
    els.ozonPnlSection.hidden = false;
  }
  els.ozonPnlMessage.className = `ozon-diagnostic-message ${ozonPnlTone(status)}`;
  els.ozonPnlMessage.textContent =
    pnl.message ||
    "Ozon v1 считает выручку по регистру продаж 1C для контрагента Ozon.";
  renderMetrics(
    els.ozonPnlGrid,
    ozonPnlMetricItems(pnl, reconciliation, expenseReconciliation),
  );
  els.ozonPnlEmpty.hidden = normalize(pnl.onecOzon?.status) === "loaded";
}

function ozonPnlMetricItems(pnl = {}, reconciliation = {}, expenseReconciliation = {}) {
  const totals = pnl.totals || {};
  const onecOzon = pnl.onecOzon || {};
  const ozonExpenses = pnl.ozonExpenses || {};
  const expenseSummary = ozonExpenses.summary || {};
  const onecOzonRegister = onecOzon.salesRegister || {};
  const hasOnecOzon = normalize(onecOzon.status) === "loaded";
  const registerAmount = Number(onecOzonRegister.amount || 0);
  const registerCost = Number(onecOzonRegister.cost || 0);
  const hasRegisterCost = hasOnecOzon && registerCost > 0;
  const apiExpenseAmount = Number(totals.ozonExpenses || expenseSummary.expenseAmount || 0);
  const topCogs = hasRegisterCost ? registerCost : totals.onecCogs;
  const grossProfit =
    hasRegisterCost && registerAmount
      ? registerAmount - registerCost - apiExpenseAmount
      : totals.profitAfterCogs;
  const itemLevelRows = Number(pnl.itemLevelRows || 0);
  const costedItemRows = Number(pnl.costedItemRows || 0);
  const realizationRows = Number(pnl.realizationRows || 0);
  const realizationRowsUsed = Number(pnl.realizationRowsUsed || itemLevelRows);
  const realizationRowsLimited = Boolean(pnl.realizationRowsLimited);
  const realizationRowsCaption =
    realizationRowsLimited && realizationRows
      ? `проверено ${number(realizationRowsUsed)} из ${number(realizationRows)}`
      : "с 1C-себестоимостью";
  const reconciliationStatus = normalize(reconciliation.status);
  const hasReconciliation = reconciliationStatus && reconciliationStatus !== "missing";
  const reconciliationDelta = Number(reconciliation.deltaAmount || 0);
  const expenseDelta = Number(expenseReconciliation.deltaAmount || 0);
  const expenseStatus = normalize(expenseReconciliation.status);
  const buyoutCaption = Number(reconciliation.matchedWithoutReportNumber || 0)
    ? "сверено без номера"
    : "отдельная сверка";
  return [
    [
      "Выручка 1C Ozon",
      optionalMoney(totals.revenue),
      "регистр продаж",
      hasOnecOzon ? "ok" : "warning",
    ],
    [
      "Отчет комиссионера",
      hasOnecOzon ? optionalMoney(onecOzon.netSalesAmount) : "не найдено",
      hasOnecOzon
        ? `${number(onecOzon.salesLines || 0)} реализация / ${number(
            onecOzon.returnLines || 0,
          )} возвраты`
        : "ООО Интернет Решения",
      hasOnecOzon ? "ok" : "warning",
    ],
    [
      "Выкупы Ozon",
      hasReconciliation ? optionalMoney(reconciliation.buyoutAmount) : "-",
      hasReconciliation
        ? `${number(reconciliation.buyoutQuantity || 0)} шт · ${buyoutCaption}`
        : "нет сверки",
      hasReconciliation && !Number(reconciliation.missingBuyouts || 0)
        ? "ok"
        : "warning",
    ],
    [
      "Итог Ozon",
      hasReconciliation ? optionalMoney(reconciliation.ozonTotalAmount) : "-",
      "отчет комиссионера + выкупы",
      reconciliationStatus === "matched" ? "ok" : "warning",
    ],
    [
      "Дельта Ozon ↔ 1C",
      hasReconciliation ? signedMoney(reconciliationDelta) : "-",
      "после выкупов",
      reconciliationStatus === "matched" ? "ok" : "warning",
    ],
    [
      "Прямые расходы Ozon по товарам",
      optionalMoney(totals.ozonExpenses ?? expenseSummary.expenseAmount),
      normalize(ozonExpenses.status) === "loaded"
        ? ozonExpenseSourceCaption(ozonExpenses, totals)
        : "нет API-расходов",
      normalize(ozonExpenses.status) === "loaded" ? "ok" : "warning",
    ],
    [
      "1C контроль расходов",
      ozonExpenseOnecValue(expenseReconciliation),
      ozonExpenseOnecCaption(expenseReconciliation),
      expenseStatus === "matched" ? "ok" : "warning",
    ],
    [
      "Дельта расходов",
      expenseReconciliation.deltaAmount == null ? "-" : signedMoney(expenseDelta),
      "1C минус Ozon API",
      expenseStatus === "matched" ? "ok" : "warning",
    ],
    [
      "Количество",
      hasOnecOzon ? `${number(onecOzonRegister.quantity || 0)} шт` : "-",
      hasOnecOzon
        ? `${number(onecOzon.salesQuantity || 0)} в отчете комиссионера`
        : "нет данных",
      "",
    ],
    [
      "Себестоимость 1C",
      topCogs == null ? "не рассчитана" : optionalMoney(topCogs),
      hasRegisterCost
        ? "полный регистр продаж"
        : totals.onecCogs == null
        ? realizationRows
          ? "нужна себестоимость или сопоставление"
          : "нужны товарные продажи"
        : realizationRowsLimited
          ? "предварительный расчет"
          : "по товарным строкам",
      topCogs == null || (!hasRegisterCost && realizationRowsLimited) ? "warning" : "",
    ],
    [
      "Товарные строки",
      `${number(costedItemRows)} / ${number(itemLevelRows)}`,
      realizationRowsCaption,
      costedItemRows ? "ok" : "warning",
    ],
    [
      "Прибыль до налогов",
      grossProfit == null
        ? optionalMoney(totals.profitBeforeCogs)
        : optionalMoney(grossProfit),
      hasRegisterCost
        ? "после себестоимости и Ozon API"
        : totals.profitAfterCogs == null
        ? "до себестоимости"
        : realizationRowsLimited
          ? "предварительно после себестоимости"
          : "после себестоимости",
      metricToneForAmount(grossProfit ?? totals.profitBeforeCogs),
    ],
  ];
}

function ozonExpenseSourceCaption(ozonExpenses = {}, totals = {}) {
  const basis = ozonExpenses.basis || totals.expenseBasis || "";
  if (totals.expenseAllocationBasis === "onec_revenue_share") {
    return "распределено по 1C-выручке";
  }
  if (basis === "ozon_mutual_settlement_expense_documents") {
    return "отчет взаиморасчетов Ozon";
  }
  if (basis === "ozon_cash_flow_statement") {
    return "денежный контроль Ozon";
  }
  return "финансы Seller API";
}

function ozonExpenseOnecValue(expenseReconciliation = {}) {
  const amount = ozonExpenseOnecAmount(expenseReconciliation);
  if (amount == null) {
    return "не найдено";
  }
  return optionalMoney(amount);
}

function ozonExpenseOnecCaption(expenseReconciliation = {}) {
  const onec = expenseReconciliation.onec || {};
  const rowCount = Number(onec.rowCount || 0);
  const amount = ozonExpenseOnecAmount(expenseReconciliation);
  if (amount == null) {
    return onec.message || "поступления/услуги 1C не найдены";
  }
  if (rowCount) {
    return `найдено в 1C: ${number(rowCount)} строк`;
  }
  return "приходные/услуги 1C найдены";
}

function ozonExpenseOnecAmount(expenseReconciliation = {}) {
  const onec = expenseReconciliation.onec || {};
  return (
    expenseReconciliation.onecExpenseAmount ??
    onec.amount ??
    onec.serviceAmount ??
    null
  );
}

function renderOzonUnitEconomics(payload = {}, pnl = {}) {
  const allRows = asArray(payload.rows);
  const selectedStatus = state.ozonUnitStatusFilter || "";
  if (els.ozonUnitStatusFilter) {
    setOptions(els.ozonUnitStatusFilter, OZON_UNIT_STATUS_OPTIONS, "Все статусы");
    els.ozonUnitStatusFilter.value = selectedStatus;
  }
  const rows = selectedStatus
    ? allRows.filter((item) => item.qualityStatus === selectedStatus)
    : allRows;
  const rowCount = Number(payload.rowCount || allRows.length || 0);
  const limited = Boolean(payload.previewLimited);
  if (!allRows.length) {
    els.ozonUnitEmpty.hidden = false;
    els.ozonUnitEmpty.textContent =
      Number(pnl.realizationRows || 0) > 0
        ? "Для детализации нужны товарные ключи, сопоставление и 1C-себестоимость."
        : "Для детализации нужен отчет Ozon за выбранный период.";
    els.ozonUnitRows.replaceChildren();
    return;
  }
  if (!rows.length) {
    els.ozonUnitEmpty.hidden = false;
    els.ozonUnitEmpty.textContent =
      "Строки с выбранным статусом не найдены в текущем списке.";
    els.ozonUnitRows.replaceChildren();
    return;
  }
  els.ozonUnitEmpty.hidden = false;
  els.ozonUnitEmpty.textContent = limited
    ? `Показано ${number(rows.length)} из ${number(rowCount)} строк.`
    : `Показано ${number(rows.length)} строк.`;
  els.ozonUnitRows.replaceChildren(...rows.map(ozonUnitEconomicsRowNode));
}

function ozonUnitEconomicsRowNode(item) {
  const row = document.createElement("tr");
  row.className = ozonUnitRowClass(item);
  const cogsAmount = item.cogsAmount ?? item.cogs;
  const profitAmount = item.profitAmount ?? item.profit;
  appendTableCells(row, [
    { value: ozonUnitOfferText(item), className: "text-code" },
    { value: item.productName || "-", className: "text-wide" },
    {
      value: item.quantity == null ? "-" : number(item.quantity),
      className: "numeric",
    },
    {
      value: ozonUnitRevenueText(item),
      className: "numeric",
      title: ozonUnitRevenueTitle(item.revenueBasis),
    },
    {
      value: ozonUnitNullableMoney(cogsAmount),
      className: "numeric",
    },
    {
      value: ozonUnitExpenseText(item, "commissionServices"),
      className: "numeric",
    },
    {
      value: ozonUnitExpenseText(item, "partnerServices"),
      className: "numeric",
    },
    {
      value: ozonUnitExpenseText(item, "logisticsStorage"),
      className: "numeric",
    },
    {
      value: ozonUnitProfitMarginText(profitAmount, item.margin, item.expenseStatus),
      className: `numeric ${metricToneForAmount(profitAmount)}`,
    },
    { value: ozonUnitOnecText(item), className: "text-wide" },
    {
      value: ozonUnitStatusText(item.qualityStatus),
      className: ozonUnitStatusTone(item.qualityStatus),
    },
    { value: ozonUnitProblemText(item), className: "text-wide" },
  ]);
  return row;
}

function ozonUnitOfferText(item) {
  return [item.offerId, item.sku, item.productId].filter(Boolean).join(" · ") || "-";
}

function ozonUnitRevenueText(item) {
  const revenueAmount = item.onecRevenue ?? item.revenueAmount;
  if (revenueAmount == null) {
    return "не рассчитано";
  }
  return `${optionalMoney(revenueAmount)} · ${ozonUnitRevenueBasisText(
    item.revenueBasis,
  )}`;
}

function ozonUnitRevenueTitle(basis) {
  if (basis === "onec_commissioner_sku") {
    return "Выручка по товару из 1C отчета комиссионера Ozon; без авто-распределений.";
  }
  if (basis === "ozon_realization_item_check") {
    return "Строковая сумма отчета Ozon используется только для детализации; итоговая выручка берется из 1C.";
  }
  if (basis === "ozon_buyout_period_total") {
    return "Выкуп подтвержден агрегатом Ozon за период.";
  }
  return "";
}

function ozonUnitRevenueBasisText(basis) {
  return {
    onec_commissioner_sku: "1C комиссионер",
    ozon_realization_item_check: "отчет Ozon",
    ozon_buyout_period_total: "выкуп",
    none: "нет базы",
  }[basis] || basis || "-";
}

function ozonUnitOnecText(item) {
  return [item.onecName, item.onecItemId].filter(Boolean).join(" · ") || "-";
}

function ozonUnitStatusText(status) {
  return {
    ready: "готово",
    partial_source: "частично",
    missing_mapping: "нет связи",
    ambiguous_mapping: "неоднозначно",
    missing_cost: "нет себестоимости",
    missing_1c_commissioner: "нет выручки 1C",
    buyout_period_only: "выкуп по периоду",
  }[status] || status || "-";
}

function ozonUnitStatusTone(status) {
  if (status === "ready") {
    return "is-ok";
  }
  return "is-warning";
}

function ozonUnitActionText(item) {
  if (item.actionText) {
    return item.actionText;
  }
  if (item.qualityStatus === "missing_mapping") {
    return "Добавить связь Ozon -> 1C в 1C ИС_Маркетплейс или ручном файле.";
  }
  if (item.qualityStatus === "ambiguous_mapping") {
    return "Выбрать правильную номенклатуру 1C в 1C ИС_Маркетплейс или ручном файле.";
  }
  if (item.qualityStatus === "missing_cost") {
    return "Проверить себестоимость 1C по номенклатуре.";
  }
  if (item.qualityStatus === "missing_1c_commissioner") {
    return "Закрыть или загрузить отчет комиссионера Ozon в 1C.";
  }
  if (item.qualityStatus === "buyout_period_only") {
    return "Оставить как ограничение сверки: номер отчета API не вернул.";
  }
  return "Действие не требуется.";
}

function ozonUnitProblemText(item) {
  const reason = item.problemReason || item.statusReason || "";
  const action = ozonUnitActionText(item);
  if (!reason) {
    return action;
  }
  if (!action || action === "Действие не требуется.") {
    return reason;
  }
  return `${reason} ${action}`;
}

function ozonUnitNullableMoney(value) {
  return value == null ? "не рассчитано" : optionalMoney(value);
}

function ozonUnitExpenseText(item = {}, group = "") {
  const first = group === "logisticsStorage" ? item.ozonLogistics : item.ozonCommission;
  const second = group === "logisticsStorage" ? item.ozonStorage : item.ozonServices;
  if (group === "partnerServices") {
    if (item.ozonPartnerServices == null) {
      return item.expenseStatus === "partial_source" ? "не распределено" : "-";
    }
    const suffix =
      item.expenseStatus === "allocated_period_expense" ? " · по выручке" : "";
    return `${optionalMoney(item.ozonPartnerServices)}${suffix}`;
  }
  if (first == null && second == null) {
    if (item.expenseStatus === "partial_source") {
      return "не распределено по SKU";
    }
    return "не рассчитано";
  }
  const suffix =
    item.expenseStatus === "allocated_period_expense" ? " · по выручке" : "";
  return `${optionalMoney(first ?? 0)} / ${optionalMoney(second ?? 0)}${suffix}`;
}

function ozonUnitProfitMarginText(profitAmount, margin, expenseStatus = "") {
  if (profitAmount == null) {
    if (expenseStatus === "partial_source") {
      return "не распределено по SKU";
    }
    return "не рассчитано";
  }
  return `${optionalMoney(profitAmount)} · ${percent(margin)}`;
}

function ozonUnitRowClass(item) {
  if (item.qualityStatus === "ready" && Number(item.profitAmount || 0) < 0) {
    return "is-loss";
  }
  return item.qualityStatus === "ready" ? "" : "is-review";
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function moneyPerUnit(amount, quantity) {
  const numericAmount = numberOrNull(amount);
  const numericQuantity = Number(quantity || 0);
  if (numericAmount == null || !numericQuantity) {
    return "-";
  }
  return money(numericAmount / numericQuantity);
}

function renderOzonBuyouts(payload = {}) {
  const rows = asArray(payload.rows);
  els.ozonBuyoutEmpty.hidden = rows.length > 0;
  els.ozonBuyoutEmpty.textContent =
    payload.message || "1C расходные накладные по выкупам Ozon не найдены.";
  els.ozonBuyoutRows.replaceChildren(...rows.map(ozonBuyoutRowNode));
}

function ozonBuyoutRowNode(item) {
  const row = document.createElement("tr");
  const status = normalize(item.ozonMatchStatus);
  const apiStatus =
    status === "found"
      ? "номер найден"
      : status === "matched_by_period_total"
        ? "сошлось за месяц"
      : status === "no_report_number"
        ? "нет номера"
        : "не найден";
  const apiClass =
    status === "found" || status === "matched_by_period_total"
      ? "is-ok"
      : "is-warning";
  appendTableCells(row, [
    { value: item.reportNumber || "-" },
    { value: periodRangeText(item.periodFrom, item.periodTo) },
    {
      value:
        [item.documentNumber, item.documentDate].filter(Boolean).join(" · ") || "-",
    },
    { value: number(item.quantity || 0), className: "numeric" },
    { value: optionalMoney(item.amount), className: "numeric" },
    { value: apiStatus, className: apiClass },
  ]);
  return row;
}

function periodRangeText(periodFrom, periodTo) {
  if (periodFrom && periodTo) {
    return `${shortDateText(periodFrom)} - ${shortDateText(periodTo)}`;
  }
  if (periodFrom || periodTo) {
    return shortDateText(periodFrom || periodTo);
  }
  return "-";
}

function shortDateText(value) {
  return formatDateTime(value).split(",")[0] || String(value || "");
}

function ozonPnlTone(status) {
  if (status === "provisional") {
    return "is-ok";
  }
  if (status === "not_started") {
    return "is-warning";
  }
  return "is-warning";
}

function metricToneForAmount(value) {
  const amount = Number(value || 0);
  if (amount < 0) {
    return "bad";
  }
  if (amount > 0) {
    return "ok";
  }
  return "";
}

function renderOzonIssues(issues = {}) {
  const items = asArray(issues.items);
  const blocking = Number(issues.blockingCount || 0);
  const review = Number(issues.reviewCount || 0);
  const statusTone = blocking ? "bad" : review ? "fallback" : "ok";
  const statusText = blocking
    ? `${number(blocking)} блокирует`
    : review
      ? `${number(review)} к проверке`
      : "Ошибок нет";
  els.ozonVitrineStatus.className = `status-pill ${statusTone}`;
  els.ozonVitrineStatus.textContent = statusText;

  if (!items.length) {
    els.ozonIssueList.replaceChildren();
    els.ozonIssueEmpty.hidden = false;
    return;
  }
  els.ozonIssueEmpty.hidden = true;
  els.ozonIssueList.replaceChildren(...items.map(ozonIssueCardNode));
}

function ozonIssueCardNode(item) {
  const node = document.createElement("article");
  node.className = `action-insight-card ozon-issue-card ${ozonIssueTone(
    item.tone,
  )}`.trim();
  const title = document.createElement("strong");
  title.textContent = item.title || "Проверка";
  const value = document.createElement("span");
  value.className = "action-insight-value";
  value.textContent = item.value || "";
  const detail = document.createElement("small");
  detail.textContent = item.detail || "";
  node.append(title, value, detail);
  return node;
}

function ozonIssueTone(tone) {
  if (tone === "bad") {
    return "negative";
  }
  if (tone === "ok") {
    return "calm";
  }
  return "review";
}

function ozonCollections(refresh) {
  return asArray(refresh?.collections).filter((item) =>
    normalize(item.sourceType || item.source_type).startsWith("ozon_"),
  );
}

function isOzonCashFlowSource(item) {
  return normalize(item.sourceType || item.source_type) === "ozon_finance_cash_flow";
}

function ozonPreviewRowNode(item) {
  const row = document.createElement("tr");
  const results = asArray(item.payload?.results);
  const endpoint = uniqueTexts(
    results.map((result) => result.sourceEndpoint || result.source_endpoint),
  ).join(", ");
  const reportCode = uniqueTexts(
    results.map((result) => result.reportCode || result.report_code),
  ).join(", ");
  const error = item.errorMessage || uniqueTexts(results.map((result) => result.error))[0];
  const cells = [
    item.sourceLabel || item.sourceType || "Ozon source",
    sourceStatusText(item.status),
    number(item.rowCount || 0),
    endpoint || "collector manifest",
    reportCode || "-",
    error || sourceStatusHint(item.status, item.required !== false),
  ];
  cells.forEach((value, index) => {
    const cell = document.createElement("td");
    cell.textContent = String(value || "-");
    if (index === 1) {
      cell.className = sourceStatusTone(item.status);
    }
    row.append(cell);
  });
  return row;
}

function ozonDiagnosticTone(diagnostics) {
  if (!diagnostics || diagnostics.status === "not_started") {
    return "is-warning";
  }
  if (diagnostics.status === "ready") {
    return "is-ok";
  }
  return "is-warning";
}

function ozonMappingRowNode(item) {
  const row = document.createElement("tr");
  const onecLabel = [item.onecName, item.onecArticle]
    .filter(Boolean)
    .join(" · ");
  const cells = [
    item.offerId || "-",
    item.productName || item.sku || item.productId || "-",
    item.barcode || "-",
    ozonMappingStatusText(item.status),
    ozonMappingMethodText(item.matchMethod),
    onecLabel || item.onecItemId || "-",
    ozonMappingActionText(item),
  ];
  cells.forEach((value, index) => {
    const cell = document.createElement("td");
    cell.textContent = String(value || "-");
    if (index === 3) {
      cell.className = ozonMappingStatusTone(item.status);
    }
    row.append(cell);
  });
  return row;
}

function ozonMappingActionText(item) {
  if (item.status === "ambiguous") {
    return "Выбрать правильную номенклатуру 1C в 1C ИС_Маркетплейс или ручном файле.";
  }
  if (item.status === "missing") {
    return "Добавить связь Ozon -> 1C в 1C ИС_Маркетплейс или ручном файле.";
  }
  if (item.status === "no_key") {
    return "Проверить артикул, SKU или штрихкод в каталоге Ozon.";
  }
  if (item.status === "matched") {
    return "Действие не требуется.";
  }
  return "Проверить строку сопоставления.";
}

function ozonMappingStatusText(status) {
  return {
    matched: "сопоставлено",
    missing: "нет связи",
    ambiguous: "неоднозначно",
    no_key: "нет ключа",
  }[status] || status || "-";
}

function ozonMappingStatusTone(status) {
  if (status === "matched") {
    return "is-ok";
  }
  if (status === "ambiguous" || status === "missing" || status === "no_key") {
    return "is-warning";
  }
  return "";
}

function ozonMappingMethodText(method) {
  return {
    uploaded_mapping_name: "файл сопоставления → 1C",
    offer_id: "offer_id → артикул 1C",
    offer_id_code: "offer_id → код 1C",
    barcode: "barcode → штрихкод 1C",
    sku_as_barcode: "SKU → штрихкод 1C",
  }[method] || method || "-";
}

function optionalMoney(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return money(value);
}

function uniqueTexts(values) {
  const seen = new Set();
  const result = [];
  values.forEach((value) => {
    const text = String(value || "").trim();
    if (!text || seen.has(text)) {
      return;
    }
    seen.add(text);
    result.push(text);
  });
  return result;
}

function sourceRefreshEmptyDetailsNode(refresh) {
  const node = document.createElement("div");
  node.className = "source-refresh-empty";
  const title = document.createElement("strong");
  title.textContent = "Коллекции не записаны";
  const copy = document.createElement("span");
  copy.textContent = refresh
    ? "Последний refresh есть, но деталей по источникам пока нет."
    : "После запуска здесь появятся WB, 1C и сопоставление.";
  node.append(title, copy);
  return node;
}

function sourceRefreshStatusLine(label, value) {
  const item = document.createElement("span");
  const name = document.createElement("strong");
  name.textContent = `${label}: `;
  item.append(name, document.createTextNode(value || "-"));
  return item;
}

function sourceRefreshEmptyActionNode() {
  const node = document.createElement("div");
  node.className = "source-refresh-empty";
  const title = document.createElement("strong");
  title.textContent = "Первый запуск";
  const copy = document.createElement("span");
  copy.textContent =
    "Для нового клиента сначала нужно сопоставление WB ↔ 1C, затем полное обновление.";
  node.append(title, copy);
  return node;
}

function isActiveSourceRefresh(refresh) {
  return ["queued", "running", "source_loaded", "rebuilding"].includes(
    normalize(refresh?.status),
  ) && !refresh?.finishedAt;
}

function scheduleSourceRefreshPolling(refresh) {
  window.clearTimeout(state.sourceRefreshPollTimer);
  state.sourceRefreshPollTimer = 0;
  if (!refresh || !isActiveSourceRefresh(refresh) || !state.clientId) {
    return;
  }
  const context = currentClientLoadContext();
  state.sourceRefreshPollTimer = window.setTimeout(
    () => loadSourceRefreshStatus(context),
    5000,
  );
}

function resetSourceRefreshPanel(options = {}) {
  window.clearTimeout(state.sourceRefreshPollTimer);
  state.sourceRefreshPollTimer = 0;
  state.latestSourceRefresh = null;
  state.latestOzonDiagnostics = null;
  els.sourceRefreshStatus.textContent = "Статус еще не загружен.";
  renderSourceRefreshSteps(null);
  els.sourceRefreshCollections.replaceChildren();
  renderOzonPreview(null, null);
  els.sourceRefreshMappingForm.reset();
  els.sourceRefreshMappingForm.classList.remove("has-file");
  els.sourceRefreshMappingStatus.textContent = "Файл не выбран.";
  if (options.hide) {
    els.sourceRefreshPanel.hidden = true;
  }
}

async function runClientSourceRefresh({ dryRun, mode = "full" }) {
  const context = currentClientLoadContext();
  const clientId = context.clientId;
  if (!clientId) {
    return;
  }
  setSourceRefreshButtonsBusy(true);
  els.sourceRefreshStatus.textContent = sourceRefreshStartText({ dryRun, mode });
  try {
    const payload = await api(
      `/api/clients/${encodeURIComponent(clientId)}/source-refresh`,
      {
        method: "POST",
        body: JSON.stringify({
          mode,
          dry_run: Boolean(dryRun),
          reason: sourceRefreshReason({ dryRun, mode }),
        }),
      },
    );
    if (!isCurrentClientLoad(context)) {
      return;
    }
    const refresh = payload.latest || null;
    state.latestSourceRefresh = refresh;
    renderSourceRefreshControl(refresh);
    await loadOzonDiagnostics(context);
    if (refresh?.newReportRunId) {
      els.sourceRefreshStatus.append(
        sourceRefreshStatusLine("Открываем", refresh.newReportRunId),
      );
      await loadReport(refresh.newReportRunId, context);
    }
  } catch (error) {
    if (!isCurrentClientLoad(context)) {
      return;
    }
    els.sourceRefreshStatus.textContent = integrationErrorMessage(
      error,
      dryRun
        ? "Не удалось проверить готовность обновления источников."
        : mode === "ozon-only"
          ? "Не удалось загрузить Ozon + 1C источники."
        : "Не удалось запустить полное обновление источников.",
    );
  } finally {
    setSourceRefreshButtonsBusy(false);
    if (isCurrentClientLoad(context)) {
      setSourceRefreshActiveLock(isActiveSourceRefresh(state.latestSourceRefresh));
    }
  }
}

function sourceRefreshStartText({ dryRun, mode }) {
  if (dryRun) {
    return "Проверяем готовность без внешнего чтения...";
  }
  if (mode === "ozon-only") {
    return "Загружаем Ozon + 1C без обязательного WB. Отчет не публикуется.";
  }
  return "Запускаем полное обновление. Это может занять время.";
}

function sourceRefreshReason({ dryRun, mode }) {
  if (dryRun) {
    return "Проверка готовности из виджета интеграций";
  }
  if (mode === "ozon-only") {
    return "Ручная загрузка Ozon + 1C без обязательного WB из виджета интеграций";
  }
  return "Ручное полное обновление из виджета интеграций";
}

function setSourceRefreshButtonsBusy(busy) {
  [
    els.sourceRefreshUploadSubmit,
    els.sourceRefreshDryRun,
    els.sourceRefreshFullRun,
    els.sourceRefreshOzonRun,
    els.sourceRefreshReload,
  ]
    .filter(Boolean)
    .forEach((button) => {
      button.disabled = busy;
    });
}

function setSourceRefreshActiveLock(active) {
  [
    els.sourceRefreshUploadSubmit,
    els.sourceRefreshDryRun,
    els.sourceRefreshFullRun,
    els.sourceRefreshOzonRun,
  ]
    .filter(Boolean)
    .forEach((button) => {
      button.disabled = Boolean(active);
    });
  if (els.sourceRefreshReload) {
    els.sourceRefreshReload.disabled = false;
  }
}

function renderCabinetManager() {
  const fragment = document.createDocumentFragment();
  const client = selectedClient();
  if (!client || !isStaffUser()) {
    return fragment;
  }
  const section = document.createElement("section");
  section.className = "integration-cabinet-manager";
  const copy = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = "Новая карточка подключения";
  const helper = document.createElement("p");
  helper.className = "muted";
  helper.textContent =
    "Выберите тип интеграции. Для WB сохраняется кабинет, для 1С и Ozon откроется карточка настройки.";
  copy.append(title, helper);

  const form = document.createElement("form");
  form.className = "cabinet-manager-form integration-card-creator-form";
  const providerLabel = document.createElement("label");
  providerLabel.className = "integration-type-field";
  providerLabel.textContent = "Тип подключения";
  const providerSelect = document.createElement("select");
  providerSelect.name = "provider_base";
  integrationProviderChoices().forEach((provider) => {
    const option = document.createElement("option");
    option.value = provider.providerBase;
    option.textContent = provider.label || provider.providerBase;
    providerSelect.append(option);
  });
  if (
    state.integrationProviderFilter &&
    Array.from(providerSelect.options).some(
      (option) => option.value === state.integrationProviderFilter,
    )
  ) {
    providerSelect.value = state.integrationProviderFilter;
  }
  providerLabel.append(providerSelect);

  const selectLabel = document.createElement("label");
  selectLabel.className = "integration-cabinet-field";
  selectLabel.dataset.cabinetField = "true";
  selectLabel.textContent = "Кабинет";
  const cabinetSelect = document.createElement("select");
  cabinetSelect.name = "cabinet_id";
  const newOption = document.createElement("option");
  newOption.value = "";
  newOption.textContent = "Новый кабинет";
  cabinetSelect.append(newOption);
  activeClientCabinets().forEach((cabinet) => {
    const option = document.createElement("option");
    option.value = cabinet.id;
    option.textContent = cabinet.label || cabinet.id;
    cabinetSelect.append(option);
  });
  selectLabel.append(cabinetSelect);

  const nameLabel = document.createElement("label");
  nameLabel.textContent = "Название";
  const nameInput = document.createElement("input");
  nameInput.name = "label";
  nameInput.type = "text";
  nameInput.placeholder = "Например: ИП Галустов";
  nameLabel.append(nameInput);

  const organizationLabel = document.createElement("label");
  organizationLabel.textContent = "Организация 1С";
  const organizationInput = document.createElement("input");
  organizationInput.name = "organization_name";
  organizationInput.type = "text";
  organizationInput.placeholder = "Например: Галустов";
  organizationLabel.append(organizationInput);

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "Сохранить кабинет";
  const status = document.createElement("p");
  status.className = "cabinet-manager-status muted";
  form.append(providerLabel, selectLabel, nameLabel, organizationLabel, submit, status);
  providerSelect.addEventListener("change", () => syncIntegrationCreatorForm(form));
  cabinetSelect.addEventListener("change", () => fillCabinetManagerForm(form));
  form.addEventListener("submit", onCabinetManagerSubmit);
  syncIntegrationCreatorForm(form);
  fillCabinetManagerForm(form);
  section.append(copy, form);
  fragment.append(section);
  return fragment;
}

function integrationProviderChoices() {
  const choices = state.integrationProviders.length
    ? state.integrationProviders
    : [
        { providerBase: "wb_api", label: "Wildberries API" },
        { providerBase: "onec_readonly", label: "1С read-only" },
        { providerBase: "ozon_api", label: "Ozon Seller API" },
      ];
  return choices.filter((item) => item.supportsMultiple !== false);
}

function syncIntegrationCreatorForm(form) {
  const providerBase = form.querySelector('[name="provider_base"]').value || "wb_api";
  const isWb = providerBase === "wb_api";
  const cabinetField = form.querySelector("[data-cabinet-field]");
  const cabinetSelect = form.querySelector('[name="cabinet_id"]');
  const nameInput = form.querySelector('[name="label"]');
  const organizationInput = form.querySelector('[name="organization_name"]');
  const submit = form.querySelector('button[type="submit"]');
  const status = form.querySelector(".cabinet-manager-status");
  cabinetField.hidden = !isWb;
  cabinetSelect.disabled = !isWb;
  nameInput.placeholder = creatorNamePlaceholder(providerBase);
  organizationInput.placeholder = creatorOrganizationPlaceholder(providerBase);
  submit.textContent = isWb ? "Сохранить кабинет" : "Создать карточку";
  status.textContent = isWb
    ? "WB-кабинет появится отдельной строкой подключения."
    : "После создания карточка откроется ниже для ввода read-only доступа.";
  if (isWb) {
    fillCabinetManagerForm(form);
  }
}

function creatorNamePlaceholder(providerBase) {
  if (providerBase === "onec_readonly") {
    return "Например: 1С УНФ основная";
  }
  if (providerBase === "ozon_api") {
    return "Например: Ozon ИП Галустов";
  }
  return "Например: ИП Галустов";
}

function creatorOrganizationPlaceholder(providerBase) {
  if (providerBase === "ozon_api") {
    return "Например: ИП Галустов";
  }
  if (providerBase === "onec_readonly") {
    return "Например: Галустов";
  }
  return "Например: Галустов";
}

function renderIntegrationRow(item) {
  const key = integrationRowKey(item);
  const isEditing = state.editingIntegrationKey === key;
  const row = document.createElement("article");
  row.className = `integration-card integration-card--${integrationStatusClass(item)}`;
  if (isEditing) {
    row.classList.add("integration-card--editing");
  }
  if (isOnecIntegrationProvider(item.providerBase || item.provider)) {
    row.classList.add("integration-card--onec-provider");
  }
  row.dataset.provider = item.provider;

  const identity = document.createElement("div");
  identity.className = "integration-identity";
  const title = document.createElement("h3");
  title.textContent = integrationTargetLabel(item);
  const label = document.createElement("p");
  label.className = "muted";
  label.textContent = [
    integrationLabel(item.providerBase || item.provider),
    integrationTargetMeta(item),
  ].filter(Boolean).join(" · ");
  identity.append(title, label);

  if (!isEditing) {
    row.append(identity, renderIntegrationReadSummary(item, key));
    return row;
  }

  row.append(identity, renderIntegrationEditForm(item, key));
  return row;
}

function renderIntegrationReadSummary(item, key) {
  const summary = document.createElement("div");
  summary.className = "integration-compact-row";

  const role = document.createElement("span");
  role.className = "integration-read-badge integration-role-badge";
  role.textContent = integrationRoleLabel(item);

  const access = document.createElement("span");
  access.className = `integration-read-badge ${integrationAccessClass(item)}`;
  access.textContent = integrationAccessText(item);

  const status = document.createElement("div");
  status.className = "integration-compact-status-cell";
  const statusPill = document.createElement("span");
  statusPill.className = "integration-status-pill";
  statusPill.textContent = integrationCompactStatusText(item);
  status.append(statusPill);
  const details = renderIntegrationMoreDetails(item);
  if (details) {
    status.append(details);
  }

  const actions = document.createElement("div");
  actions.className = "integration-actions integration-actions--read";
  if (item.status !== "disabled" && (item.configured || item.secretHint)) {
    const checkButton = document.createElement("button");
    checkButton.type = "button";
    checkButton.className = "secondary-button";
    checkButton.textContent = "Проверить";
    checkButton.dataset.integrationCheck = "true";
    checkButton.addEventListener("click", () => onIntegrationCheck(item, null));
    actions.append(checkButton);
  }
  const editButton = document.createElement("button");
  editButton.type = "button";
  const hasSavedAccess = item.configured || item.secretHint;
  editButton.className = hasSavedAccess ? "secondary-button" : "";
  editButton.textContent =
    hasSavedAccess && item.status !== "disabled" ? "Изменить" : "Настроить";
  editButton.addEventListener("click", () => {
    if (!item.isDraft) {
      state.draftIntegration = null;
    }
    state.editingIntegrationKey = key;
    renderIntegrationsWithFallback(state.integrationItems);
  });
  actions.append(editButton);

  summary.append(role, access, status, actions);
  return summary;
}

function renderIntegrationEditForm(item, key) {
  const roleField = document.createElement("label");
  roleField.className = "integration-compact-field";
  roleField.dataset.label = "Роль";
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

  const secretControls = renderIntegrationSecretControls(item);

  const statusCell = document.createElement("div");
  statusCell.className = "integration-row-status";
  const meta = document.createElement("span");
  meta.className = "integration-status-pill";
  meta.textContent = integrationStatusText(item);
  const providerBase = item.providerBase || item.provider;
  const optionalMeta =
    providerBase === "ozon_api" && !item.configured && !item.secretHint
      ? document.createElement("span")
      : null;
  if (optionalMeta) {
    optionalMeta.className = "integration-optional-pill";
    optionalMeta.textContent = "Опционально";
  }
  const details = document.createElement("dl");
  details.className = "integration-details";
  details.append(
    detailItem("Хранение", storageModeText(item.storageMode)),
    detailItem(
      "Проверка",
      item.lastCheckedAt ? formatDateTime(item.lastCheckedAt) : "Еще не проверяли",
    ),
  );
  if (item.lastCheck && item.lastCheck.message) {
    details.append(detailItem("Результат", item.lastCheck.message));
  }
  const notice = integrationNoticeForItem(item);
  const feedback = document.createElement("p");
  feedback.className = `integration-feedback integration-feedback--${notice.type}`;
  feedback.textContent = notice.text;
  statusCell.append(...[meta, optionalMeta, details, feedback].filter(Boolean));

  const form = document.createElement("form");
  form.className = "integration-edit-form";
  if (isOnecIntegrationProvider(providerBase)) {
    form.classList.add("integration-form--onec");
  } else if (providerBase === "ozon_api") {
    form.classList.add("integration-form--ozon");
  }
  form.dataset.provider = item.provider;
  form.dataset.providerBase = item.providerBase || item.provider;
  form.dataset.saveMode = item.isVirtual || item.isDraft ? "create" : "update";
  form.dataset.label = item.label || integrationDefaultLabel(item);
  form.dataset.cabinetName = item.cabinetName || "";
  form.dataset.organizationName = item.organizationName || "";
  form.dataset.noticeKey = integrationNoticeKey(item);

  const actions = document.createElement("div");
  actions.className = "integration-actions";
  const saveButton = document.createElement("button");
  saveButton.type = "submit";
  saveButton.textContent = "Сохранить";
  saveButton.dataset.integrationSave = "true";
  const cancelButton = document.createElement("button");
  cancelButton.type = "button";
  cancelButton.className = "secondary-button";
  cancelButton.textContent = "Отмена";
  cancelButton.addEventListener("click", () => {
    if (item.isDraft) {
      state.draftIntegration = null;
    }
    state.editingIntegrationKey = "";
    renderIntegrationsWithFallback(state.integrationItems);
  });
  const disableButton = document.createElement("button");
  disableButton.type = "button";
  disableButton.className = "secondary-button integration-subtle-action";
  disableButton.textContent = "Отключить";
  disableButton.setAttribute("aria-label", `Отключить ${integrationTargetLabel(item)}`);
  disableButton.dataset.integrationDisable = "true";
  disableButton.disabled = item.isVirtual || (!item.configured && !item.secretHint);
  actions.append(saveButton, cancelButton, disableButton);

  form.append(roleField, secretControls, statusCell, actions);
  integrationDraftInputs(form).forEach((input) => {
    const listener = () => {
      if (integrationSecretChanged(form)) {
        setIntegrationFeedback(form, integrationDraftMessage(form), "warning");
      } else {
        setIntegrationFeedback(form, notice.text, notice.type);
      }
    };
    input.addEventListener("input", listener);
    input.addEventListener("change", listener);
  });
  form.addEventListener("submit", onIntegrationSave);
  disableButton.addEventListener("click", () =>
    onIntegrationAction(item.provider, "disable", form),
  );
  return form;
}

function renderIntegrationSecretControls(item) {
  const providerBase = item.providerBase || item.provider;
  if (isOnecIntegrationProvider(providerBase)) {
    return renderOnecSecretControls(item);
  }
  if (providerBase === "ozon_api") {
    return renderOzonSecretControls(item);
  }
  const secretField = document.createElement("label");
  secretField.className = "integration-compact-field";
  secretField.dataset.label = item.secretHint ? `Сохранен ${item.secretHint}` : "Новый ключ";
  const secretInput = document.createElement("input");
  secretInput.name = "secret";
  secretInput.type = "password";
  secretInput.autocomplete = "off";
  secretInput.placeholder =
    (item.providerBase || item.provider) === "ozon_api" && !item.secretHint
      ? "clientId=...; apiKey=..."
      : item.secretHint
        ? "Заменить ключ"
        : "Вставить ключ";
  secretInput.dataset.integrationSecretInput = "true";
  secretField.append(secretInput);
  return secretField;
}

function renderOzonSecretControls(item) {
  const controls = document.createElement("div");
  controls.className = "ozon-secret-fields";
  controls.dataset.label = item.secretHint
    ? "Ozon доступ сохранен"
    : "Подключение Ozon";
  controls.append(
    integrationSecretField({
      name: "ozon_client_id",
      label: "Client ID",
      type: "text",
      placeholder: "Ozon Client ID",
      autocomplete: "off",
    }),
    integrationSecretField({
      name: "ozon_api_key",
      label: "API Key",
      type: "password",
      placeholder: item.secretHint ? "Новый API Key" : "Ozon API Key",
      autocomplete: "new-password",
    }),
  );
  return controls;
}

function renderOnecSecretControls(item) {
  const controls = document.createElement("div");
  controls.className = "onec-secret-fields";
  controls.dataset.label = item.secretHint
    ? "1С доступ сохранен"
    : "Подключение 1С";
  controls.append(
    integrationSecretField({
      name: "onec_base_url",
      label: "URL 1С/OData",
      type: "url",
      placeholder: "https://server/base/odata/standard.odata",
      autocomplete: "url",
    }),
    integrationSecretField({
      name: "onec_username",
      label: "Пользователь",
      type: "text",
      placeholder: "odata.user",
      autocomplete: "username",
    }),
    integrationSecretField({
      name: "onec_password",
      label: "Пароль",
      type: "password",
      placeholder: item.secretHint ? "Новый пароль 1С" : "Пароль 1С",
      autocomplete: "new-password",
    }),
    onecVerifySslField(),
  );
  return controls;
}

function integrationSecretField({ name, label, type, placeholder, autocomplete }) {
  const field = document.createElement("label");
  field.className = "integration-compact-field";
  field.dataset.label = label;
  const input = document.createElement("input");
  input.name = name;
  input.type = type;
  input.autocomplete = autocomplete || "off";
  input.placeholder = placeholder;
  input.dataset.integrationSecretInput = "true";
  field.append(input);
  return field;
}

function onecVerifySslField() {
  const field = document.createElement("label");
  field.className = "integration-toggle-field";
  const input = document.createElement("input");
  input.name = "onec_verify_ssl";
  input.type = "checkbox";
  input.checked = true;
  input.defaultChecked = true;
  input.dataset.integrationSecretInput = "true";
  const text = document.createElement("span");
  text.textContent = "Проверять SSL";
  field.append(input, text);
  return field;
}

function integrationDraftInputs(form) {
  return Array.from(form.querySelectorAll("[data-integration-secret-input]"));
}

function integrationSecretChanged(form) {
  return integrationDraftInputs(form).some((input) => {
    if (input.type === "checkbox") {
      return input.checked !== input.defaultChecked;
    }
    return input.value.trim();
  });
}

function integrationDraftMessage(form) {
  if (isOnecIntegrationProvider(form.dataset.providerBase)) {
    return "Поля 1С заполнены, но еще не сохранены. Сначала сохраните, затем проверяйте.";
  }
  if (form.dataset.providerBase === "ozon_api") {
    return "Поля Ozon заполнены, но еще не сохранены. Сначала сохраните, затем проверяйте.";
  }
  return "Новый ключ введен в строке этого кабинета, но еще не сохранен.";
}

function integrationSecretPayload(form, data) {
  if (form.dataset.providerBase === "ozon_api") {
    const clientId = String(data.get("ozon_client_id") || "").trim();
    const apiKey = String(data.get("ozon_api_key") || "").trim();
    const missing = [];
    if (!clientId) {
      missing.push("Client ID");
    }
    if (!apiKey) {
      missing.push("API Key");
    }
    if (missing.length) {
      return {
        secret: "",
        message: `Заполните ${missing.join(", ")} и нажмите «Сохранить».`,
      };
    }
    return {
      secret: JSON.stringify({ clientId, apiKey }),
      message: "",
    };
  }
  if (!isOnecIntegrationProvider(form.dataset.providerBase)) {
    const secret = String(data.get("secret") || "").trim();
    return {
      secret,
      message: secret
        ? ""
        : "Вставьте ключ или строку подключения, затем нажмите «Сохранить».",
    };
  }
  const baseUrl = String(data.get("onec_base_url") || "").trim();
  const username = String(data.get("onec_username") || "").trim();
  const password = String(data.get("onec_password") || "").trim();
  const missing = [];
  if (!baseUrl) {
    missing.push("URL 1С/OData");
  }
  if (!username) {
    missing.push("пользователя");
  }
  if (!password) {
    missing.push("пароль");
  }
  if (missing.length) {
    return {
      secret: "",
      message: `Заполните ${missing.join(", ")} и нажмите «Сохранить».`,
    };
  }
  if (!/^https?:\/\//i.test(baseUrl)) {
    return {
      secret: "",
      message: "URL 1С/OData должен начинаться с http:// или https://.",
    };
  }
  return {
    secret: JSON.stringify({
      baseUrl,
      username,
      password,
      verifySsl: data.get("onec_verify_ssl") === "on",
    }),
    message: "",
  };
}

function isOnecIntegrationProvider(provider) {
  return String(provider || "").split(":")[0] === "onec_readonly";
}

function fillCabinetManagerForm(form) {
  if (form.querySelector('[name="provider_base"]')?.value !== "wb_api") {
    return;
  }
  const cabinetId = form.querySelector('[name="cabinet_id"]').value;
  const cabinet = activeClientCabinets().find((item) => item.id === cabinetId);
  form.querySelector('[name="label"]').value = cabinet?.label || "";
  form.querySelector('[name="organization_name"]').value = cabinet
    ? cabinetCompanyName(cabinet)
    : "";
}

async function onCabinetManagerSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const context = currentClientLoadContext();
  const clientId = context.clientId;
  const providerBase = form.querySelector('[name="provider_base"]').value || "wb_api";
  if (providerBase !== "wb_api") {
    createDraftIntegrationCard(form, providerBase);
    return;
  }
  if (!clientId) {
    return;
  }
  const cabinetId = form.querySelector('[name="cabinet_id"]').value;
  const label = form.querySelector('[name="label"]').value.trim();
  const organizationName = form.querySelector('[name="organization_name"]').value.trim();
  const status = form.querySelector(".cabinet-manager-status");
  if (!label) {
    status.textContent = "Введите название WB-кабинета.";
    return;
  }
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  submit.textContent = "Сохраняем...";
  status.textContent = cabinetId ? "Обновляем кабинет..." : "Добавляем кабинет...";
  try {
    const url = cabinetId
      ? `/api/clients/${encodeURIComponent(clientId)}/cabinets/${encodeURIComponent(cabinetId)}`
      : `/api/clients/${encodeURIComponent(clientId)}/cabinets`;
    const payload = await api(url, {
      method: cabinetId ? "PATCH" : "POST",
      body: JSON.stringify({
        label,
        organization_name: organizationName,
        status: "active",
      }),
    });
    if (!isCurrentClientLoad(context)) {
      return;
    }
    if (payload.client) {
      state.clients = upsertClientOption(state.clients, payload.client);
      renderClientSelect();
      renderFilters(clientScopedFilterOptions());
    }
    const savedCabinet = asArray(payload.client?.cabinets).find((item) =>
      cabinetId ? item.id === cabinetId : item.label === label,
    );
    state.editingIntegrationKey = savedCabinet
      ? `wb:${savedCabinet.id || savedCabinet.label}`
      : "";
    await loadIntegrations(context);
    els.integrationsStatus.textContent = cabinetId
      ? "Кабинет обновлен."
      : "Кабинет добавлен.";
  } catch (error) {
    status.textContent = integrationErrorMessage(error, "Не удалось сохранить кабинет.");
  } finally {
    submit.disabled = false;
    submit.textContent = "Сохранить кабинет";
  }
}

function createDraftIntegrationCard(form, providerBase) {
  const name = form.querySelector('[name="label"]').value.trim();
  const organizationName = form.querySelector('[name="organization_name"]').value.trim();
  const title = draftIntegrationTitle(providerBase, name, organizationName);
  const draft = {
    tenantId: selectedClient()?.tenantId || "",
    provider: `${providerBase}:draft`,
    providerBase,
    connectionKey: "draft",
    connectionRole: defaultProviderRole(providerBase),
    cabinetName: providerBase === "onec_readonly" ? "" : title,
    organizationName:
      providerBase === "onec_readonly" ? (organizationName || title) : organizationName,
    clientId: state.clientId,
    clientCompanyId: "",
    wbCabinetId: "",
    isPrimary: false,
    label: `${integrationLabel(providerBase)} · ${title}`,
    status: "not_configured",
    configured: false,
    secretHint: "",
    lastCheckedAt: null,
    disabledAt: null,
    readOnly: true,
    storageMode: "none",
    lastCheck: null,
    isVirtual: true,
    isDraft: true,
    rowId: `draft:${providerBase}`,
  };
  state.draftIntegration = draft;
  state.editingIntegrationKey = draft.rowId;
  renderIntegrationsWithFallback(state.integrationItems);
  els.integrationsStatus.textContent = "Карточка создана. Заполните доступ и сохраните.";
}

function draftIntegrationTitle(providerBase, name, organizationName) {
  if (name) {
    return name;
  }
  if (providerBase === "onec_readonly") {
    return organizationName || "1С подключение";
  }
  if (providerBase === "ozon_api") {
    return "Ozon кабинет";
  }
  return "WB кабинет";
}

function cabinetCompanyName(cabinet) {
  const company = activeClientCompanies().find(
    (item) => item.id === cabinet.clientCompanyId,
  );
  return company?.label || "";
}

function buildIntegrationRows(items) {
  const sourceItems = asArray(items);
  const wbItems = sourceItems.filter((item) => item.providerBase === "wb_api");
  const otherItems = sourceItems.filter((item) => item.providerBase !== "wb_api");
  const cabinets = activeClientCabinets();
  if (!cabinets.length) {
    return sourceItems;
  }

  const client = selectedClient();
  const companyById = new Map(
    asArray(client?.companies).map((item) => [item.id, item.label || item.id]),
  );
  const usedProviders = new Set();
  const primary = wbItems.find((item) => item.provider === "wb_api") || {
    provider: "wb_api",
    providerBase: "wb_api",
    connectionRole: defaultProviderRole("wb_api"),
    label: "Wildberries API",
    status: "not_configured",
    configured: false,
    secretHint: "",
    storageMode: "none",
    lastCheck: null,
    lastCheckedAt: null,
  };

  const rows = cabinets.map((cabinet) => {
    const existing = findIntegrationForCabinet(wbItems, cabinet);
    if (existing) {
      usedProviders.add(existing.provider);
      return {
        ...existing,
        cabinetName: existing.cabinetName || cabinet.label || "",
        organizationName:
          existing.organizationName || companyById.get(cabinet.clientCompanyId) || "",
        wbCabinetId: existing.wbCabinetId || cabinet.id || "",
        clientCompanyId: existing.clientCompanyId || cabinet.clientCompanyId || "",
        rowId: `wb:${cabinet.id || cabinet.label}`,
      };
    }
    return {
      ...primary,
      provider: "wb_api",
      providerBase: "wb_api",
      connectionKey: "primary",
      connectionRole: primary.connectionRole || defaultProviderRole("wb_api"),
      cabinetName: cabinet.label || "",
      organizationName: companyById.get(cabinet.clientCompanyId) || "",
      wbCabinetId: cabinet.id || "",
      clientCompanyId: cabinet.clientCompanyId || "",
      label: `Wildberries API · ${cabinet.label || "кабинет"}`,
      status: "not_configured",
      configured: false,
      secretHint: "",
      lastCheckedAt: null,
      disabledAt: null,
      storageMode: "none",
      lastCheck: null,
      isVirtual: true,
      rowId: `wb:${cabinet.id || cabinet.label}`,
    };
  });

  const orphanWbItems = wbItems
    .filter((item) =>
      !usedProviders.has(item.provider) &&
      (item.provider !== "wb_api" || item.configured || item.secretHint),
    )
    .map((item) => ({
      ...item,
      cabinetName: item.cabinetName || "Не привязан к кабинету",
      rowId: `wb-orphan:${item.provider}`,
    }));
  return [...rows, ...orphanWbItems, ...otherItems];
}

function findIntegrationForCabinet(items, cabinet) {
  const cabinetId = String(cabinet.id || "");
  const cabinetLabel = normalize(cabinet.label);
  const cabinetProvider = String(cabinet.provider || "");
  return items.find((item) => {
    if (item.wbCabinetId && item.wbCabinetId === cabinetId) {
      return true;
    }
    if (cabinetProvider && item.provider === cabinetProvider) {
      return true;
    }
    return normalize(item.cabinetName) === cabinetLabel && cabinetLabel;
  });
}

function integrationNoticeKey(item) {
  return item.provider || item.rowId || "";
}

function integrationRowKey(item) {
  return item.rowId || item.provider || integrationNoticeKey(item);
}

function isOptionalIntegration(item) {
  return (
    (item.providerBase || item.provider) === "ozon_api" &&
    !item.configured &&
    !item.secretHint
  );
}

function integrationAccessText(item) {
  if (item.status === "disabled") {
    return "Отключено";
  }
  if (item.secretHint) {
    return isOnecIntegrationProvider(item.providerBase || item.provider)
      ? `Доступ сохранен ${item.secretHint}`.trim()
      : `Ключ сохранен ${item.secretHint}`.trim();
  }
  if (item.configured) {
    return isOnecIntegrationProvider(item.providerBase || item.provider)
      ? "Доступ сохранен"
      : "Ключ сохранен";
  }
  return "Нужно настроить";
}

function integrationAccessClass(item) {
  if (item.status === "disabled") {
    return "integration-access-muted";
  }
  if (item.configured || item.secretHint) {
    return "integration-access-ok";
  }
  return isOptionalIntegration(item)
    ? "integration-access-optional"
    : "integration-access-warning";
}

function integrationCompactStatusText(item) {
  if (isOptionalIntegration(item)) {
    return "Опционально";
  }
  if (item.status === "disabled") {
    return "Отключено";
  }
  if (item.status === "check_failed") {
    return "Нужна проверка";
  }
  if (item.lastCheckedAt) {
    return `Проверено ${formatShortDateTime(item.lastCheckedAt)}`;
  }
  if (item.status === "check_ok") {
    return "Проверено";
  }
  return "Не проверяли";
}

function renderIntegrationMoreDetails(item) {
  if (!item.storageMode && !item.lastCheck?.message && !item.lastCheckedAt) {
    return null;
  }
  const details = document.createElement("details");
  details.className = "integration-more";
  const summary = document.createElement("summary");
  summary.textContent = "Подробнее";
  const list = document.createElement("dl");
  list.className = "integration-details";
  list.append(
    detailItem("Хранение", storageModeText(item.storageMode)),
    detailItem(
      "Проверка",
      item.lastCheckedAt ? formatDateTime(item.lastCheckedAt) : "Еще не проверяли",
    ),
  );
  if (item.lastCheck?.message) {
    list.append(detailItem("Результат", item.lastCheck.message));
  }
  details.append(summary, list);
  return details;
}

function integrationDefaultLabel(item) {
  const base = integrationLabel(item.providerBase || item.provider);
  const target = integrationTargetLabel(item);
  return target && target !== "Все подключения" ? `${base} · ${target}` : base;
}

function integrationTargetLabel(item) {
  if (item.providerBase === "wb_api") {
    return item.cabinetName || "WB кабинет не указан";
  }
  if (item.providerBase === "onec_readonly") {
    return item.organizationName || "Все организации 1С";
  }
  if (item.providerBase === "ozon_api") {
    return item.cabinetName || "Ozon кабинет";
  }
  return item.organizationName || "Все подключения";
}

function integrationTargetMeta(item) {
  const parts = [];
  if (item.providerBase === "wb_api") {
    if (item.organizationName) {
      parts.push(`1С: ${item.organizationName}`);
    }
    parts.push(item.wbCabinetId ? `ID кабинета: ${item.wbCabinetId}` : "WB-кабинет клиента");
  } else if (item.providerBase === "onec_readonly") {
    parts.push(item.clientCompanyId ? `ID организации: ${item.clientCompanyId}` : "1С контур");
  } else if (item.providerBase === "ozon_api") {
    parts.push("Ozon Seller read-only");
  } else {
    parts.push(item.clientCompanyId ? `ID подключения: ${item.clientCompanyId}` : "Контур");
  }
  return parts.join(" · ");
}

function renderIntegrationsEmpty(title, message) {
  els.integrationsStatus.textContent = title;
  els.integrationList.replaceChildren(integrationEmptyNode(title, message));
}

function integrationEmptyNode(title, message) {
  const empty = document.createElement("div");
  empty.className = "integration-empty";
  const heading = document.createElement("h3");
  heading.textContent = title;
  const copy = document.createElement("p");
  copy.className = "muted";
  copy.textContent = message;
  empty.append(heading, copy);
  return empty;
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
  const context = currentClientLoadContext();
  const clientId = context.clientId;
  const provider = form.dataset.provider;
  const data = new FormData(form);
  if (!clientId) {
    return;
  }
  const { secret, message: secretMessage } = integrationSecretPayload(form, data);
  if (!secret) {
    els.integrationsStatus.textContent = secretMessage;
    setIntegrationFeedback(form, secretMessage, "warning");
    return;
  }
  setIntegrationBusy(form, "save", true);
  setIntegrationFeedback(
    form,
    isOnecIntegrationProvider(form.dataset.providerBase)
      ? "Сохраняем доступ 1С. После сохранения поля очистятся."
      : "Сохраняем ключ. После сохранения поле очистится.",
    "info",
  );
  try {
    const requestPayload = {
      label: form.dataset.label || "",
      connection_role: String(data.get("connection_role") || ""),
      client_id: clientId,
      cabinet_name: form.dataset.cabinetName || "",
      organization_name: form.dataset.organizationName || "",
      secret,
    };
    const isCreate = form.dataset.saveMode === "create";
    const payload = await api(
      isCreate ? "/api/integrations" : `/api/integrations/${encodeURIComponent(provider)}`,
      {
        method: isCreate ? "POST" : "PUT",
        body: JSON.stringify(
          isCreate
            ? { provider: form.dataset.providerBase || provider, ...requestPayload }
            : requestPayload,
        ),
      },
    );
    if (!isCurrentClientLoad(context)) {
      return;
    }
    const notice = integrationSaveNotice(payload);
    state.integrationNotices[payload.provider || provider] = notice;
    state.integrationNotices[form.dataset.noticeKey || provider] = notice;
    state.draftIntegration = null;
    state.editingIntegrationKey = "";
    form.reset();
    await loadIntegrations(context);
    els.integrationsStatus.textContent = notice.text;
  } catch (error) {
    const message = integrationErrorMessage(error, "Не удалось сохранить подключение.");
    els.integrationsStatus.textContent = message;
    setIntegrationFeedback(form, message, "danger");
  } finally {
    setIntegrationBusy(form, "save", false);
  }
}

async function onIntegrationCheck(item, form) {
  if (form && integrationSecretChanged(form)) {
    const message =
      "Вы ввели новые данные доступа, но они еще не сохранены. Сохраните ключ, затем проверьте подключение.";
    els.integrationsStatus.textContent = message;
    setIntegrationFeedback(form, message, "warning");
    return;
  }
  if (!item.configured && !item.secretHint) {
    const message = isOnecIntegrationProvider(item.providerBase || item.provider)
      ? "Сначала заполните поля 1С и сохраните подключение."
      : "Сохраните ключ, затем проверьте подключение.";
    els.integrationsStatus.textContent = message;
    setIntegrationFeedback(form, message, "warning");
    return;
  }
  await onIntegrationAction(item.provider, "check", form);
}

async function onIntegrationAction(provider, action, form = null) {
  const context = currentClientLoadContext();
  const clientId = context.clientId;
  if (!clientId) {
    return;
  }
  setIntegrationBusy(form, action, true);
  if (form && action === "check") {
    setIntegrationFeedback(form, "Проверяем сохраненное read-only подключение...", "info");
  }
  try {
    const payload = await api(`/api/integrations/${encodeURIComponent(provider)}/${action}`, {
      method: "POST",
      body: JSON.stringify({ client_id: clientId }),
    });
    if (!isCurrentClientLoad(context)) {
      return;
    }
    state.integrationNotices[provider] = integrationActionNotice(payload, action);
    if (action === "disable") {
      state.editingIntegrationKey = "";
    }
    await loadIntegrations(context);
    els.integrationsStatus.textContent = state.integrationNotices[provider].text;
  } catch (error) {
    const message = integrationErrorMessage(error, "Не удалось выполнить действие.");
    els.integrationsStatus.textContent = message;
    setIntegrationFeedback(form, message, "danger");
  } finally {
    setIntegrationBusy(form, action, false);
  }
}

function integrationNoticeForItem(item) {
  if (state.integrationNotices[item.provider]) {
    return state.integrationNotices[item.provider];
  }
  if (state.integrationNotices[item.rowId]) {
    return state.integrationNotices[item.rowId];
  }
  if (item.status === "disabled") {
    const disabledText = isOnecIntegrationProvider(item.providerBase || item.provider)
      ? "Подключение отключено. Чтобы снова использовать строку, заполните поля 1С и сохраните."
      : "Подключение отключено. Чтобы снова использовать строку, вставьте новый ключ и сохраните.";
    return {
      type: "warning",
      text: disabledText,
    };
  }
  if (item.status === "check_ok") {
    return {
      type: "success",
      text: item.lastCheck?.message
        ? `Проверка прошла: ${item.lastCheck.message}`
        : "Проверка прошла. Подключение можно использовать.",
    };
  }
  if (item.status === "check_failed") {
    return {
      type: "danger",
      text: item.lastCheck?.message
        ? `Проверка не прошла: ${item.lastCheck.message}`
        : "Проверка не прошла. Проверьте ключ и права доступа.",
    };
  }
  if (item.storageMode === "hash_only") {
    return {
      type: "warning",
      text:
        "Ключ сохранен только как контрольная метка. Для автоматической проверки нужен режим encrypted.",
    };
  }
  if (item.configured || item.secretHint) {
    const accessName = isOnecIntegrationProvider(item.providerBase || item.provider)
      ? "Доступ"
      : "Ключ";
    return {
      type: "success",
      text: `${accessName} сохранен. Теперь нажмите «Проверить», чтобы убедиться в read-only доступе.`,
    };
  }
  return {
    type: "info",
    text:
      isOnecIntegrationProvider(item.providerBase || item.provider)
        ? "Заполните URL 1С/OData, пользователя и пароль, затем нажмите «Сохранить»."
        : "Сохраните ключ, затем проверьте подключение.",
  };
}

function integrationSaveNotice(item) {
  if (item.storageMode === "encrypted") {
    return {
      type: "success",
      text: "Сохранено. Секрет скрыт, теперь можно нажать «Проверить».",
    };
  }
  if (item.storageMode === "hash_only") {
    return {
      type: "warning",
      text:
        "Сохранено как hash-only. Секрет не показывается, но live-проверка требует encrypted-хранение.",
    };
  }
  return {
    type: "success",
    text: "Подключение сохранено. Теперь можно проверить доступ.",
  };
}

function integrationActionNotice(item, action) {
  if (action === "disable") {
    return { type: "warning", text: "Подключение отключено." };
  }
  if (item.status === "check_ok") {
    return {
      type: "success",
      text: item.lastCheck?.message
        ? `Проверка прошла: ${item.lastCheck.message}`
        : "Проверка прошла. Read-only доступ подтвержден.",
    };
  }
  if (item.lastCheck?.message) {
    return { type: "danger", text: `Проверка не прошла: ${item.lastCheck.message}` };
  }
  return { type: "danger", text: "Проверка не прошла. Проверьте ключ и права доступа." };
}

function setIntegrationFeedback(form, text, type = "info") {
  const feedback = form?.querySelector(".integration-feedback");
  if (!feedback) {
    return;
  }
  feedback.className = `integration-feedback integration-feedback--${type}`;
  feedback.textContent = text;
}

function setIntegrationBusy(form, action, busy) {
  if (!form) {
    return;
  }
  const saveButton = form.querySelector("[data-integration-save]");
  const checkButton = form.querySelector("[data-integration-check]");
  const disableButton = form.querySelector("[data-integration-disable]");
  [saveButton, checkButton, disableButton].forEach((button) => {
    if (button) {
      button.disabled = busy;
    }
  });
  if (saveButton) {
    saveButton.textContent = busy && action === "save" ? "Сохраняем..." : "Сохранить";
  }
  if (checkButton) {
    checkButton.textContent = busy && action === "check" ? "Проверяем..." : "Проверить";
  }
  if (disableButton) {
    disableButton.textContent = busy && action === "disable" ? "Отключаем..." : "Отключить";
  }
}

function integrationErrorMessage(error, fallback) {
  const message = String(error?.message || "");
  if (error?.status === 401) {
    return "Сессия истекла. Войдите снова и повторите действие.";
  }
  if (error?.status === 403) {
    return "Нет прав на изменение интеграций у этого клиента.";
  }
  return message && !message.startsWith("HTTP ") ? message : fallback;
}

function integrationStatusText(item) {
  const hint = isOnecIntegrationProvider(item.providerBase || item.provider)
    ? ""
    : item.secretHint || "";
  if (
    (item.providerBase || item.provider) === "ozon_api" &&
    item.status === "not_configured"
  ) {
    return "Не настроено";
  }
  const labels = {
    not_configured: "Не настроено",
    configured: `Сохранено ${hint}`.trim(),
    check_ok: `Проверка пройдена ${hint}`.trim(),
    check_failed: "Нужна проверка",
    disabled: "Отключено",
  };
  return labels[item.status] || item.status || "Не настроено";
}

function integrationStatusClass(item) {
  if (item.status === "check_ok") {
    return "ok";
  }
  if (item.status === "check_failed") {
    return "danger";
  }
  if (item.status === "disabled") {
    return "disabled";
  }
  if (item.storageMode === "hash_only") {
    return "warning";
  }
  if (item.status === "configured" || item.configured || item.secretHint) {
    return "saved";
  }
  return "empty";
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
  els.overviewTitle.textContent = readinessHeadline(readiness.status);
  els.readinessLabel.textContent = readiness.label || "Статус не рассчитан";
  els.readinessAction.textContent = readiness.nextAction || "Проверить отчет.";
  els.readinessScore.textContent = String(readiness.score ?? 0);
  els.readinessCard.className = "decision-strip";
  if (readiness.status === "ready") {
    els.readinessCard.classList.add("readiness-ready");
  } else if (["failed", "blocked"].includes(readiness.status)) {
    els.readinessCard.classList.add("readiness-blocked");
  } else {
    els.readinessCard.classList.add("readiness-review");
  }
}

function readinessHeadline(status) {
  if (status === "ready") {
    return "Отчет готов к отправке";
  }
  if (["failed", "blocked"].includes(status)) {
    return "Нельзя отправлять клиенту";
  }
  return "Нужна проверка перед отправкой";
}

function renderNextAction({ readiness, quality, sourceLoads, refresh }) {
  const action = nextAction({ readiness, quality, sourceLoads, refresh });
  els.overviewTitle.textContent = decisionHeadline(readiness, action);
  els.nextActionTitle.textContent = action.title;
  els.nextActionCopy.textContent = action.copy;
  els.nextActionButton.textContent = action.button;
  els.nextActionButton.dataset.action = action.action;
  els.nextActionMeta.textContent = action.meta || "";
  const showMappingUpload = action.action === "mappingUpload" && isStaffUser();
  els.nextActionButton.hidden = showMappingUpload;
  els.nextActionUploadForm.hidden = !showMappingUpload;
  if (!showMappingUpload && action.action === "mappingUpload") {
    els.nextActionButton.textContent = "Показать причины";
    els.nextActionButton.dataset.action = "reasons";
  }
}

function decisionHeadline(readiness, action) {
  if (readiness.status === "ready") {
    return "Отчет готов к отправке";
  }
  if (["failed", "blocked"].includes(readiness.status)) {
    return `Нельзя отправлять: ${action.title}`;
  }
  return `Нужна проверка: ${action.title}`;
}

function nextAction({ readiness, quality, sourceLoads, refresh }) {
  const sourceProblems = nonOkSourceCount(sourceLoads, refresh);
  const mappingProblems =
    Number(quality.mappingRows || 0) > 0 ||
    refreshHasCollectionStatus(refresh, "stale", ["mapping", "sku_mapping", "сопостав"]);
  const missingCost = Number(quality.missingCostRows || 0) > 0;
  const periodNotice = preliminaryPeriodNotice(readiness, quality);
  if (["failed", "blocked"].includes(readiness.status)) {
    return {
      title: "Разобрать блокер отчета",
      copy: readiness.nextAction || "Сначала нужно снять блокер подготовки отчета.",
      button: "Показать причины",
      action: "reasons",
      meta: "Отправка клиенту сейчас рискованна.",
    };
  }
  if (mappingProblems) {
    return {
      title: "Обновить сопоставление WB ↔ 1C",
      copy: periodNotice
        ? "Обновите файл сопоставления из 1С. Период пока предварительный."
        : "Выберите файл сопоставления из 1С прямо здесь и обновите источник.",
      button: "Вставить файл",
      action: "mappingUpload",
      meta: "Кабинет сам запустит пересборку после загрузки. TXT, TSV или CSV; содержимое файла не показывается клиенту.",
    };
  }
  if (missingCost) {
    return {
      title: "Закрыть себестоимость 1С",
      copy: "Есть строки без себестоимости. Их нужно разобрать до отправки клиенту.",
      button: "Показать строки",
      action: "missingCost",
      meta: `${number(quality.missingCostRows || 0)} строк требуют проверки.`,
    };
  }
  if (sourceProblems) {
    return {
      title: readiness.status === "partial_source"
        ? "Проверить неполный источник"
        : "Проверить свежесть источников",
      copy: periodNotice
        ? "Не все источники прошли проверку. Если отчет нужен сейчас, укажите клиенту предварительный период и ограничения источников."
        : "Не все источники прошли проверку. Смотрите чеклист и проблемные строки ниже.",
      button: "Показать чеклист",
      action: "reasons",
      meta: [
        `${sourceProblems} источников требуют внимания.`,
        periodNotice,
      ]
        .filter(Boolean)
        .join(" "),
    };
  }
  if (readinessHasCode(readiness, "client_draft_missing")) {
    return {
      title: "Собрать клиентский вывод",
      copy: "Данные готовы к работе, но клиентский текст еще не подготовлен.",
      button: "Открыть вывод",
      action: "clientOutput",
      meta: "AI может собрать черновик по рассчитанным фактам.",
    };
  }
  if (readiness.status === "ready") {
    return {
      title: "Отправить пакет клиенту",
      copy: "Проверьте финальный вывод и приложите Excel к коммуникации.",
      button: "Открыть клиентский вывод",
      action: "clientOutput",
      meta: "Отчет выглядит готовым к передаче.",
    };
  }
  return {
    title: "Проверить причины",
    copy: readiness.nextAction || "Откройте список причин и проблемные строки.",
    button: "Показать причины",
    action: "reasons",
    meta: "Система не нашла более точного действия.",
  };
}

function preliminaryPeriodNotice(readiness, quality) {
  if (quality.partialPeriod || readinessHasCode(readiness, "partial_period")) {
    return "Период предварительный: укажите это клиенту или дождитесь полного периода.";
  }
  return "";
}

function onNextAction() {
  const action = els.nextActionButton.dataset.action || "reasons";
  if (action === "missingCost") {
    openDrilldownWidget("missingCost");
    return;
  }
  if (action === "clientOutput") {
    openClientOutputWidget();
    return;
  }
  document
    .querySelector(".decision-support-grid")
    .scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderCommandChecklist({ readiness, quality, sourceLoads, refresh }) {
  const readinessStatus = readiness.status || "";
  const sourceProblems = nonOkSourceCount(sourceLoads, refresh);
  const mappingProblems =
    Number(quality.mappingRows || 0) > 0 ||
    refreshHasCollectionStatus(refresh, "stale", ["mapping", "sku_mapping", "сопостав"]);
  const missingCost = Number(quality.missingCostRows || 0) > 0;
  const clientDraftReady = !readinessHasCode(readiness, "client_draft_missing");
  const excelReady = Boolean(state.reportId);
  const checklist = [
    {
      label: "Решение по отправке",
      value: readiness.label || "Статус не рассчитан",
      state:
        readinessStatus === "ready"
          ? "ok"
          : ["failed", "blocked"].includes(readinessStatus)
            ? "bad"
            : "warn",
    },
    {
      label: "WB и 1C источники",
      value: sourceProblems ? `${sourceProblems} требуют проверки` : "Покрытие принято",
      state: sourceProblems ? "warn" : "ok",
    },
    {
      label: "Сопоставление WB ↔ 1C",
      value: mappingProblems ? "Нужно обновить или проверить" : "Без явных блокеров",
      state: mappingProblems ? "warn" : "ok",
    },
    {
      label: "Себестоимость 1С",
      value: missingCost ? "Есть строки без себестоимости" : "Проверка пройдена",
      state: missingCost ? "warn" : "ok",
    },
    {
      label: "Excel и клиентский вывод",
      value: clientDraftReady ? "Артефакты готовы к работе" : "Нужен клиентский вывод",
      state: excelReady && clientDraftReady ? "ok" : "warn",
    },
  ];
  const badCount = checklist.filter((item) => item.state === "bad").length;
  const warnCount = checklist.filter((item) => item.state === "warn").length;
  els.commandStatus.className = "status-pill";
  if (badCount) {
    els.commandStatus.classList.add("bad");
    els.commandStatus.textContent = "Блокер";
  } else if (warnCount) {
    els.commandStatus.classList.add("fallback");
    els.commandStatus.textContent = `${warnCount} к проверке`;
  } else {
    els.commandStatus.classList.add("ok");
    els.commandStatus.textContent = "Готово";
  }
  if (!els.commandChecklist) {
    return;
  }
  els.commandChecklist.replaceChildren(
    ...checklist.map((item) => {
      const node = document.createElement("li");
      node.className = `command-check ${item.state}`;
      const marker = document.createElement("span");
      marker.className = "command-check-marker";
      marker.textContent = item.state === "ok" ? "OK" : "!";
      const content = document.createElement("div");
      const label = document.createElement("strong");
      label.textContent = item.label;
      const value = document.createElement("small");
      value.textContent = item.value;
      content.append(label, value);
      node.append(marker, content);
      return node;
    }),
  );
}

function mappingUploadControls(kind = "next") {
  if (kind === "sourceRefresh") {
    return {
      form: els.sourceRefreshMappingForm,
      fileInput: els.sourceRefreshMappingFile,
      status: els.sourceRefreshMappingStatus,
      submit: els.sourceRefreshUploadSubmit,
    };
  }
  return {
    form: els.nextActionUploadForm,
    fileInput: els.nextActionUploadFile,
    status: els.nextActionUploadStatus,
    submit: els.nextActionUploadSubmit,
  };
}

function onMappingFileSelected(kind = "next") {
  const controls = mappingUploadControls(kind);
  const file = controls.fileInput.files?.[0];
  controls.form.classList.toggle("has-file", Boolean(file));
  controls.status.textContent = file
    ? `Выбран файл: ${file.name}. Теперь нажмите «Загрузить».`
    : "TXT/TSV/CSV из списка «Сопоставление товаров» в 1С.";
  if (kind === "sourceRefresh") {
    renderSourceRefreshSteps(state.latestSourceRefresh);
  }
}

async function onMappingUpload(event, kind = "next") {
  event.preventDefault();
  const context = currentClientLoadContext();
  const clientId = context.clientId;
  const reportId = state.reportId;
  if (kind === "next" && !reportId) {
    return;
  }
  if (kind === "sourceRefresh" && !clientId) {
    return;
  }
  const controls = mappingUploadControls(kind);
  const file = controls.fileInput.files?.[0];
  if (!file) {
    controls.status.textContent = "Сначала вставьте файл сопоставления.";
    return;
  }
  const data = new FormData();
  data.append("file", file);
  controls.submit.disabled = true;
  controls.status.textContent =
    kind === "sourceRefresh"
      ? "Загружаем сопоставление в контур клиента..."
      : "Отправляем файл и запускаем пересборку...";
  try {
    const url =
      kind === "sourceRefresh"
        ? `/api/clients/${encodeURIComponent(clientId)}/mapping-file`
        : `/api/reports/${encodeURIComponent(reportId)}/mapping-file`;
    const payload = await api(url, {
      method: "POST",
      body: data,
    });
    if (
      !isCurrentClientLoad(context) ||
      (kind === "next" && reportId !== state.reportId)
    ) {
      return;
    }
    controls.form.reset();
    controls.form.classList.remove("has-file");
    if (kind === "sourceRefresh") {
      controls.status.textContent =
        `${payload.fileName} принят. Теперь можно проверить готовность и запустить полное обновление.`;
      await loadSourceRefreshStatus(context);
      return;
    }
    const refresh = payload.autoRefresh || {};
    const newReportId = refresh.newReportRunId || refresh.new_report_run_id || "";
    if (newReportId) {
      controls.status.textContent =
        `${payload.fileName} принят. Отчет пересобран, открываем новую витрину.`;
      await loadReport(newReportId, context);
      return;
    }
    controls.status.textContent = mappingUploadRefreshStatus(payload);
  } catch (error) {
    if (
      !isCurrentClientLoad(context) ||
      (kind === "next" && reportId !== state.reportId)
    ) {
      return;
    }
    controls.status.textContent =
      "Не удалось обновить сопоставление. Проверьте файл и попробуйте еще раз.";
  } finally {
    controls.submit.disabled = false;
  }
}

function mappingUploadRefreshStatus(payload) {
  const refresh = payload.autoRefresh || {};
  if (refresh.status === "disabled") {
    return `${payload.fileName} принят. Автоматическая пересборка сейчас отключена администратором.`;
  }
  if (refresh.status === "busy" || refresh.status === "blocked_active_refresh") {
    return `${payload.fileName} принят. Пересборка уже идет, новая витрина появится после завершения.`;
  }
  if (refresh.status === "failed") {
    return `${payload.fileName} принят, но пересборка не завершилась. Проверьте статус источников.`;
  }
  if (refresh.status) {
    return `${payload.fileName} принят. Пересборка запущена: ${sourceStatusText(refresh.status)}.`;
  }
  return `${payload.fileName} принят. Автоматическая пересборка запрошена.`;
}

function nonOkSourceCount(sourceLoads, refresh) {
  const loads = asArray(sourceLoads);
  const collections = asArray(refresh?.collections);
  const items = loads.length ? loads : collections;
  return items.filter(
    (item) =>
      !["loaded", "ok", "ready", "completed", "empty_expected"].includes(
        normalize(item.status),
      ),
  ).length;
}

function refreshHasCollectionStatus(refresh, status, markers) {
  const safeMarkers = asArray(markers).map(normalize);
  return asArray(refresh?.collections).some((item) => {
    const collectionText = normalize(
      [item.sourceLabel, item.sourceType, item.collection, item.name].filter(Boolean).join(" "),
    );
    return (
      normalize(item.status) === status &&
      safeMarkers.some((marker) => collectionText.includes(marker))
    );
  });
}

function renderQuality(quality, sourceLoads, readiness) {
  const total = Number(quality.rowCount || 0);
  const okRows = Number(quality.okRows || 0);
  const missingCost = Number(quality.missingCostRows || 0);
  const mapping = Number(quality.mappingRows || 0);
  const onecIssues = Number(quality.documentReconciliationIssues || 0);
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
  const okRatio = total ? Math.max(0, Math.min(1, okRows / total)) : 0;
  const okPercent = Math.round(okRatio * 100);
  const okShare = `${okPercent}%`;
  const summaryIssues = [];
  if (missingCost) {
    summaryIssues.push(`${number(missingCost)} без себестоимости`);
  }
  if (mapping) {
    summaryIssues.push(`${number(mapping)} по сопоставлению`);
  }
  if (onecIssues) {
    summaryIssues.push(`${number(onecIssues)} по сверке 1С`);
  }
  if (partialPeriod === "Да") {
    summaryIssues.push("период неполный");
  }
  const incomplete = Number(quality.incompleteSources ?? incompleteSources);
  if (incomplete) {
    summaryIssues.push(`${number(incomplete)} источник требует проверки`);
  }
  els.qualityProgressFill.style.width = `${okPercent}%`;
  els.qualitySummaryText.textContent = total
    ? `${number(okRows)} из ${number(total)} строк OK (${okShare}). ${
        summaryIssues.length
          ? `Сначала: ${summaryIssues.slice(0, 3).join(", ")}.`
          : "Качество данных выглядит готовым."
      }`
    : "Строки качества еще не загружены.";
  renderMetrics(els.qualityGrid, [
    ["Строк ОК", `${okRows} из ${total}`],
    ["Без себестоимости", missingCost],
    ["Маппинг / сопоставление", mapping],
    ["Сверка WB ↔ 1С", onecIssues],
    ["Неполный период", partialPeriod],
    ["Неполные источники", incomplete],
  ]);
}

function renderKpis(kpis) {
  if (shouldRenderOzonAnalytics()) {
    renderOzonKpis(state.latestOzonDiagnostics);
    return;
  }
  setKpiHeading();
  const revenue = Number(kpis.revenue || 0);
  const profit = Number(kpis.profit || 0);
  const returns = Number(kpis.returns || 0);
  const sales = Number(kpis.sales || 0);
  const lossRows = Number(kpis.lossRows || 0);
  const lostSalesRevenue = Number(kpis.lostSalesRevenue || 0);
  const netSales = sales - returns;
  const returnRate = sales ? `${Math.round((returns / sales) * 1000) / 10}%` : "-";
  const revenuePerSale = sales ? revenue / sales : 0;
  const margin =
    kpis.margin === null || kpis.margin === undefined
      ? "-"
      : `${Math.round(Number(kpis.margin || 0) * 1000) / 10}%`;
  renderMetrics(els.kpiGrid, [
    ["Выручка после СПП", money(revenue)],
    ["Прибыль после налогов", money(profit)],
    ["Маржа", margin],
    ["Упущенные продажи", money(lostSalesRevenue)],
    ["Продажи, шт", number(sales)],
    ["Чистые продажи, шт", number(netSales)],
    ["Возвраты, шт", number(returns)],
    ["Возвратность", returnRate],
    ["Выручка / продажа", money(revenuePerSale)],
    ["Убыточных строк", lossRows],
  ]);
}

function renderOzonKpis(diagnostics = state.latestOzonDiagnostics) {
  const payload = diagnostics || {};
  setKpiHeading({
    eyebrow: "Расчетная витрина Ozon",
    title: "Показатели",
  });
  renderMetrics(
    els.kpiGrid,
    ozonPnlMetricItems(
      payload.pnl || {},
      payload.reconciliation || {},
      payload.expenseReconciliation || {},
    ),
  );
}

function setKpiHeading({ eyebrow = "", title = "Показатели" } = {}) {
  if (els.kpiTitle) {
    els.kpiTitle.textContent = title;
  }
  if (!els.kpiEyebrow) {
    return;
  }
  els.kpiEyebrow.textContent = eyebrow;
  els.kpiEyebrow.hidden = !eyebrow;
}

function ozonMartStatusLabel(status) {
  const value = normalize(status);
  if (!value) {
    return "Загрузка";
  }
  if (value === "ready") {
    return "Готова";
  }
  if (value === "needs_review") {
    return "Нужна проверка";
  }
  if (value === "partial_source") {
    return "Частично рассчитана";
  }
  if (value === "missing_1c_commissioner") {
    return "Нет закрытия 1C";
  }
  if (value === "not_started") {
    return "Не запускалась";
  }
  if (value.includes("error") || value.includes("fail")) {
    return "Ошибка";
  }
  return sourceStatusLabel(status);
}

function ozonMartMessageText(message) {
  return String(message || "")
    .replaceAll("Ozon mart v1", "Расчетная витрина Ozon")
    .replaceAll("Ozon mart", "Расчетная витрина Ozon")
    .replaceAll("mapping", "сопоставления")
    .replaceAll("SKU-level", "товарные")
    .replaceAll("SKU-прибыли", "прибыли по товарам");
}

function renderAnalytics(summary) {
  if (shouldRenderOzonAnalytics()) {
    renderOzonAnalytics(state.latestOzonDiagnostics);
    return;
  }
  setAnalyticsTitles("wb");
  renderActionInsights(els.actionInsightsList, summary);
  renderMoneyTrendChart(els.moneyTrendChart, asArray(summary.monthly));
  renderUnitProfitAndLossTable(
    els.unitPlTable,
    summary.kpis || {},
    asArray(summary.expenses),
  );
  renderLossDriversChart(
    els.lossDriversChart,
    asArray(summary.liquidityRows),
    asArray(summary.lostSales),
  );
  renderReturnsChart(els.returnsChart, asArray(summary.monthly), summary.kpis || {});
}

function shouldRenderOzonAnalytics() {
  const selectedCabinetId = selectedMarketplaceCabinetId();
  if (selectedCabinetId) {
    const selectedCabinet = selectedMarketplaceCabinet();
    return selectedCabinet
      ? isOzonMarketplaceCabinet(selectedCabinet)
      : hasOzonMarketplaceContext(state.latestOzonDiagnostics);
  }
  return !state.reportId && hasOzonMarketplaceContext(state.latestOzonDiagnostics);
}

function renderOzonAnalytics(diagnostics = state.latestOzonDiagnostics) {
  setAnalyticsTitles("ozon");
  const payload = diagnostics || {};
  const mart = payload.ozonMart || payload.unitRows || {};
  const rows = asArray(mart.rows);
  const totals = mart.totals || {};
  const summary = mart.summary || {};
  renderOzonActionInsights(els.actionInsightsList, payload, mart);
  renderOzonMartKpis(els.moneyTrendChart, mart);
  renderOzonProfitAndLoss(els.unitPlTable, totals, mart);
  renderOzonProblems(els.lossDriversChart, summary);
  renderOzonReconciliationAnalytics(els.returnsChart, payload);
  if (!rows.length && normalize(payload.status) === "error") {
    renderAnalyticsEmpty(
      els.moneyTrendChart,
      ozonMartMessageText(payload.message || "Расчетная витрина Ozon не загрузилась."),
    );
  }
}

function setAnalyticsTitles(mode) {
  const ozonMode = mode === "ozon";
  els.moneyTrendTitle.textContent = ozonMode ? "Расчетная витрина Ozon" : "Динамика денег";
  els.moneyTrendCopy.textContent = ozonMode
    ? "Итоги экономики по товарам за выбранный период."
    : "Выручка, прибыль и маржа по месяцам.";
  els.unitPlTitle.textContent = ozonMode
    ? "Прибыль и расходы Ozon"
    : "P&L юнит-экономики";
  els.unitPlCopy.textContent = ozonMode
    ? "Выручка из 1C, себестоимость и расходы Ozon по товарным строкам."
    : "Выручка, расходы и прибыль в управленческом виде.";
  els.lossDriversTitle.textContent = ozonMode
    ? "Что мешает расчету"
    : "Топ потерь";
  els.lossDriversCopy.textContent = ozonMode
    ? "Сопоставление, себестоимость, закрытие 1C и неполные расходы."
    : "Где больше всего отрицательной или упущенной прибыли.";
  els.returnsChartTitle.textContent = ozonMode ? "Сверка Ozon ↔ 1C" : "Возвраты";
  els.returnsChartCopy.textContent = ozonMode
    ? "Комиссионер, выкупы и расходы по статьям."
    : "Возвратность и объем возвратов по месяцам.";
}

function renderOzonActionInsights(target, diagnostics = {}, mart = {}) {
  const issueItems = asArray(diagnostics.issues?.items).length
    ? asArray(diagnostics.issues?.items)
    : asArray(mart.issues);
  if (!issueItems.length) {
    const empty = document.createElement("div");
    empty.className = "action-insight-card calm";
    const title = document.createElement("strong");
    title.textContent = "Расчет Ozon готов";
    const copy = document.createElement("span");
    copy.textContent = "Критичных задач по Ozon сейчас нет.";
    empty.append(title, copy);
    target.replaceChildren(empty);
    return;
  }
  target.replaceChildren(
    ...issueItems.slice(0, 5).map((item) =>
      actionInsightCard({
        title: item.title || "Ozon",
        value: item.value || "",
        copy: item.detail || "",
        action: { name: "ozonMart" },
        tone: item.tone === "bad" ? "negative" : "review",
      }),
    ),
  );
}

function renderOzonMartKpis(target, mart = {}) {
  const totals = mart.totals || {};
  const summary = mart.summary || {};
  const rowCount = Number(mart.rowCount || 0);
  if (!rowCount) {
    renderAnalyticsEmpty(target, "Расчет Ozon пока без строк для выбранного периода.");
    return;
  }
  renderMetrics(target, [
    ["Строк в расчете", number(rowCount), `показано ${number(mart.previewRowCount || 0)}`],
    ["Выручка 1C", optionalMoney(totals.onecRevenue), "из отчета комиссионера"],
    ["Себестоимость 1C", optionalMoney(totals.cogs), "по данным 1C"],
    [
      "Прямые расходы Ozon по товарам",
      optionalMoney(totals.ozonExpenses),
      totals.expenseAllocationBasis === "onec_revenue_share"
        ? "распределено по 1C-выручке"
        : totals.expenseBasis === "ozon_cash_flow_statement"
        ? "денежный контроль, без SKU-распределения"
        : Number(summary.partialExpenses || 0)
          ? "частичные расходы: нужна сверка"
          : "по товарным строкам",
    ],
    [
      "Прибыль до налогов",
      totals.profit == null ? "не рассчитано" : optionalMoney(totals.profit),
      totals.margin == null ? "маржа не рассчитана" : `маржа ${percent(totals.margin)}`,
      metricToneForAmount(totals.profit),
    ],
    [
      "Готовые",
      `${number(summary.ready || 0)} / ${number(rowCount)}`,
      "строк можно читать",
      Number(summary.ready || 0) ? "ok" : "warning",
    ],
  ]);
}

function renderOzonProfitAndLoss(target, totals = {}, mart = {}) {
  const articleRows = ozonMartArticlePlRows(mart);
  if (articleRows.length) {
    const revenue = Number(totals.onecRevenue || 0);
    const nodes = [profitAndLossTable(articleRows, revenue)];
    const detail = ozonArticleDrilldownNode(mart);
    if (detail) {
      nodes.push(detail);
    }
    target.replaceChildren(...nodes);
    return;
  }
  const revenue = Number(totals.onecRevenue || 0);
  const cogs = Number(totals.cogs || 0);
  const hasOzonExpenses = totals.ozonExpenses !== null && totals.ozonExpenses !== undefined;
  const ozonExpenses = hasOzonExpenses ? Number(totals.ozonExpenses || 0) : null;
  const profit = totals.profit == null ? null : Number(totals.profit || 0);
  if (!revenue && !cogs && !hasOzonExpenses && profit == null) {
    renderAnalyticsEmpty(target, "P&L Ozon не рассчитан: нужна 1C-выручка и расходы.");
    return;
  }
  target.replaceChildren(
    profitAndLossTable(
      [
        { label: "1C выручка Ozon SKU", amount: revenue, tone: "revenue" },
        { label: "Себестоимость 1C", amount: -cogs, tone: "expense" },
        {
          label: "Прямые расходы Ozon по товарам",
          amount: ozonExpenses == null ? null : -ozonExpenses,
          display: ozonExpenses == null ? "не рассчитано" : null,
          tone: "expense",
        },
        {
          label: "Прибыль до налогов",
          amount: profit,
          display: profit == null ? "не рассчитано" : null,
          tone: profit == null || profit < 0 ? "negative result" : "profit result",
          action: { name: "ozonMart" },
        },
      ],
      revenue,
    ),
  );
}

function ozonMartArticlePlRows(mart = {}) {
  return asArray(mart.articleRows)
    .filter((item) => item && item.effectAmount !== null && item.effectAmount !== undefined)
    .map((item) => {
      const group = normalize(item.group);
      const effect = Number(item.effectAmount || 0);
      const isResult = group === "result" || item.articleId === "profit";
      const isRevenue = group === "revenue";
      return {
        label: item.label || item.articleId || "Статья Ozon",
        amount: effect,
        tone: isResult
          ? effect < 0
            ? "negative result"
            : "profit result"
          : isRevenue
            ? "revenue"
            : "expense",
        action: group === "result" ? { name: "ozonMart" } : null,
      };
    });
}

function ozonArticleDrilldownNode(mart = {}) {
  const rows = asArray(mart.articleDrilldown).filter(
    (item) => item && item.kind === "sku_allocation",
  );
  if (!rows.length) {
    return null;
  }
  const wrapper = document.createElement("div");
  wrapper.className = "analytics-detail ozon-article-drilldown";

  const heading = document.createElement("div");
  heading.className = "analytics-detail-heading";
  const title = document.createElement("strong");
  title.textContent = "Статьи экономики Ozon";
  const copy = document.createElement("span");
  copy.textContent = "Распределение статей по SKU; контроль 1C/Ozon вынесен в сверку.";
  heading.append(title, copy);

  const table = document.createElement("div");
  table.className = "analytics-detail-table";
  table.setAttribute("role", "table");
  const header = document.createElement("div");
  header.className = "analytics-detail-row header";
  header.setAttribute("role", "row");
  ["Статья", "Источник / SKU", "Сумма", "Статус"].forEach((label) => {
    const cell = document.createElement("span");
    cell.setAttribute("role", "columnheader");
    cell.textContent = label;
    header.append(cell);
  });
  table.append(header);

  rows.slice(0, 10).forEach((item) => {
    const row = document.createElement("div");
    row.className = `analytics-detail-row ${
      item.status === "ready" ? "matched" : "warning"
    }`.trim();
    row.setAttribute("role", "row");

    const label = document.createElement("strong");
    label.setAttribute("role", "cell");
    label.textContent = item.label || item.articleId || "Статья Ozon";
    if (item.sourceLabel) {
      const source = document.createElement("small");
      source.textContent = item.sourceLabel;
      label.append(source);
    }

    const source = document.createElement("span");
    source.setAttribute("role", "cell");
    source.textContent = [item.offerId, item.sku, item.productName]
      .filter(Boolean)
      .join(" · ") || "-";

    const amount = document.createElement("span");
    amount.className = "analytics-detail-value";
    amount.setAttribute("role", "cell");
    amount.textContent = optionalMoney(item.amount);

    const status = document.createElement("span");
    status.className = "analytics-detail-note";
    status.setAttribute("role", "cell");
    status.textContent = item.note || ozonUnitStatusText(item.status);

    row.append(label, source, amount, status);
    table.append(row);
  });

  wrapper.append(heading, table);
  return wrapper;
}

function renderOzonProblems(target, summary = {}) {
  const rows = [
    ["Нет сопоставления", summary.missingMapping],
    ["Неоднозначное сопоставление", summary.ambiguousMapping],
    ["Нет себестоимости", summary.missingCost],
    ["Нет выручки 1C", summary.missing1cCommissioner],
    ["Частичные расходы Ozon", summary.partialExpenses],
    ["Выкуп без номера отчета", summary.buyoutPeriodOnly],
  ]
    .map(([label, value]) => ({
      label,
      value: Number(value || 0),
      meta: "строк / задач",
      tone: "review",
      action: { name: "ozonMart" },
    }))
    .filter((item) => item.value);
  if (!rows.length) {
    renderAnalyticsEmpty(target, "Критичных проблем по расчету Ozon нет.");
    return;
  }
  renderCountRows(target, rows);
}

function renderOzonReconciliationAnalytics(target, diagnostics = {}) {
  const reconciliation = diagnostics.reconciliation || {};
  const expenseReconciliation = diagnostics.expenseReconciliation || {};
  const buyouts = diagnostics.ozonBuyouts?.summary || {};
  const pnl = diagnostics.pnl || {};
  const expenseStatus = normalize(expenseReconciliation.status);
  renderMetrics(target, [
    [
      "Статус сверки",
      reconciliation.status || pnl.status || "-",
      reconciliation.message || pnl.message || "",
      reconciliation.status === "matched" ? "ok" : "warning",
    ],
    [
      "Комиссионер 1C",
      optionalMoney(reconciliation.commissionerAmount),
      "база SKU-выручки",
    ],
    [
      "Выкупы",
      optionalMoney(reconciliation.buyoutAmount ?? buyouts.amount),
      `${number(reconciliation.buyoutQuantity ?? buyouts.quantity ?? 0)} шт`,
    ],
    [
      "Дельта",
      reconciliation.deltaAmount == null
        ? "не рассчитано"
        : signedMoney(reconciliation.deltaAmount),
      "после выкупов",
      Math.abs(Number(reconciliation.deltaAmount || 0)) > 1 ? "warning" : "ok",
    ],
    [
      "Прямые расходы Ozon по товарам",
      optionalMoney(expenseReconciliation.ozonExpenseAmount),
      ozonExpenseSourceCaption(expenseReconciliation.ozon || {}, pnl.totals || {}),
      expenseReconciliation.ozonExpenseAmount == null ? "warning" : "ok",
    ],
    [
      "1C контроль расходов",
      ozonExpenseOnecValue(expenseReconciliation),
      ozonExpenseOnecCaption(expenseReconciliation),
      expenseStatus === "matched" ? "ok" : "warning",
    ],
    [
      "Дельта расходов",
      expenseReconciliation.deltaAmount == null
        ? "не рассчитано"
        : signedMoney(expenseReconciliation.deltaAmount),
      "1C минус Ozon API",
      expenseStatus === "matched" ? "ok" : "warning",
    ],
  ]);
  const detailNode = ozonExpenseDetailNode(expenseReconciliation);
  if (detailNode) {
    target.append(detailNode);
  }
}

function ozonExpenseDetailNode(expenseReconciliation = {}) {
  const articleRows = asArray(expenseReconciliation.articleRows);
  const rows = articleRows.length
    ? articleRows
    : asArray(expenseReconciliation.detailRows);
  if (!rows.length) {
    return null;
  }
  const wrapper = document.createElement("div");
  wrapper.className = "analytics-detail";

  const heading = document.createElement("div");
  heading.className = "analytics-detail-heading";
  const title = document.createElement("strong");
  title.textContent = articleRows.length
    ? "Из чего состоит дельта расходов"
    : "Расходы по статьям";
  const copy = document.createElement("span");
  copy.textContent = articleRows.length
    ? "Строки без пары показывают, какая статья или документ создает расхождение."
    : "Ozon API показывает расходы периода, 1C показывает, что уже разнесено в документах.";
  heading.append(title, copy);

  const table = document.createElement("div");
  table.className = "analytics-detail-table";
  table.setAttribute("role", "table");
  const header = document.createElement("div");
  header.className = "analytics-detail-row header";
  header.setAttribute("role", "row");
  ["Статья", "Ozon API", "1C контроль", "Дельта / пояснение"].forEach((label) => {
    const cell = document.createElement("span");
    cell.setAttribute("role", "columnheader");
    cell.textContent = label;
    header.append(cell);
  });
  table.append(header);

  rows.slice(0, 18).forEach((item) => {
    const row = document.createElement("div");
    row.className = `analytics-detail-row ${ozonExpenseDetailTone(item)}`.trim();
    row.setAttribute("role", "row");

    const label = document.createElement("strong");
    label.setAttribute("role", "cell");
    label.textContent = item.label || "-";
    if (item.parentLabel) {
      const parent = document.createElement("small");
      parent.textContent = item.parentLabel;
      label.append(parent);
    }

    const ozon = document.createElement("span");
    ozon.className = "analytics-detail-value";
    ozon.setAttribute("role", "cell");
    ozon.textContent = ozonExpenseOzonText(item);

    const onec = document.createElement("span");
    onec.className = "analytics-detail-value";
    onec.setAttribute("role", "cell");
    onec.textContent = item.onecAmount == null ? "-" : optionalMoney(item.onecAmount);

    const note = document.createElement("span");
    note.className = "analytics-detail-note";
    note.setAttribute("role", "cell");
    note.textContent =
      item.deltaAmount == null
        ? item.note || "-"
        : `${signedMoney(item.deltaAmount)} · ${item.note || "1C минус Ozon API"}`;

    row.append(label, ozon, onec, note);
    table.append(row);
  });

  wrapper.append(heading, table);
  return wrapper;
}

function ozonExpenseDetailTone(item = {}) {
  if (item.kind === "total") {
    return "result";
  }
  if (item.kind === "onec_unmatched" || item.kind === "ozon_unmatched") {
    return "warning";
  }
  if (item.kind === "article_matched") {
    return "matched";
  }
  if (item.includedInExpense === false) {
    return "muted";
  }
  if (item.kind === "ozon_item") {
    return "subitem";
  }
  return "";
}

function ozonExpenseOzonText(item = {}) {
  if (item.ozonAmount != null) {
    return signedMoney(item.ozonAmount);
  }
  if (item.ozonSignedAmount != null) {
    return signedMoney(item.ozonSignedAmount);
  }
  return "-";
}

function renderActionInsights(target, summary = {}) {
  const items = actionInsightItems(summary).slice(0, 5);
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "action-insight-card calm";
    const title = document.createElement("strong");
    title.textContent = "Критичных разборов нет";
    const copy = document.createElement("span");
    copy.textContent = "Можно читать аналитику ниже и готовить вывод клиенту.";
    empty.append(title, copy);
    target.replaceChildren(empty);
    return;
  }
  target.replaceChildren(...items.map(actionInsightCard));
}

function actionInsightItems(summary = {}) {
  const quality = summary.quality || {};
  const kpis = summary.kpis || {};
  const liquidityRows = asArray(summary.liquidityRows);
  const lostSales = asArray(summary.lostSales);
  const items = [];
  const missingCost = Number(quality.missingCostRows || 0);
  const mapping = Number(quality.mappingRows || 0);
  const onecIssues = Number(quality.documentReconciliationIssues || 0);
  const missingOnec = Number(quality.documentReconciliationMissingOnec || 0);
  const lossRows = Number(kpis.lossRows || 0);
  const lossAmount = liquidityRows
    .filter((row) => Number(row.profit || 0) < 0)
    .reduce((total, row) => total + Math.abs(Number(row.profit || 0)), 0);
  const lostSalesRevenue = Number(kpis.lostSalesRevenue || 0);
  const lostSalesUnits = Number(kpis.lostSalesUnits || 0);
  const returns = Number(kpis.returns || 0);
  const sales = Number(kpis.sales || 0);

  if (missingCost) {
    items.push({
      title: "Себестоимость 1С",
      value: `${number(missingCost)} строк`,
      copy: "Нет подтвержденной себестоимости.",
      action: { name: "missingCost" },
      tone: "review",
    });
  }
  if (mapping) {
    items.push({
      title: "Сопоставление WB ↔ 1C",
      value: `${number(mapping)} строк`,
      copy: "Есть товары без надежного сопоставления.",
      action: { name: "missingMapping" },
      tone: "review",
    });
  }
  if (onecIssues || missingOnec) {
    items.push({
      title: "Сверка WB ↔ 1С",
      value: onecIssues ? `${number(onecIssues)} к проверке` : `${number(missingOnec)} без 1С`,
      copy: "Проверьте дельты, выплаты и документы.",
      action: { name: "onecReconciliationDelta" },
      tone: "review",
    });
  }
  if (lossRows) {
    items.push({
      title: "Убыточные строки",
      value: lossAmount ? signedMoney(-lossAmount) : `${number(lossRows)} строк`,
      copy: "Разобрать товары с отрицательной прибылью.",
      action: { name: "rowsPreset", preset: "losses" },
      tone: "negative",
    });
  }
  if (lostSalesRevenue || lostSalesUnits || lostSales.length) {
    items.push({
      title: "Упущенные продажи",
      value: lostSalesRevenue ? money(lostSalesRevenue) : `${number(lostSalesUnits)} шт`,
      copy: "Посмотреть товары, где был спрос без WB-остатка.",
      action: { name: "lostSales" },
      tone: "missed",
    });
  }
  if (returns) {
    items.push({
      title: "Возвраты",
      value: `${number(returns)} шт`,
      copy: `Возвратность ${percent(sales ? returns / sales : null)}.`,
      action: { name: "rowsPreset", preset: "returns" },
      tone: "returns",
    });
  }
  return items;
}

function actionInsightCard(item) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `action-insight-card ${item.tone || ""}`.trim();
  applyAnalyticsActionAttributes(button, item.action);

  const title = document.createElement("strong");
  title.textContent = item.title;
  const value = document.createElement("span");
  value.className = "action-insight-value";
  value.textContent = item.value || "";
  const copy = document.createElement("small");
  copy.textContent = item.copy || "";
  button.append(title, value, copy);
  return button;
}

function applyAnalyticsActionAttributes(node, action) {
  if (!action || !action.name) {
    return;
  }
  node.dataset.analyticsAction = action.name;
  if (action.preset !== undefined) {
    node.dataset.rowPreset = action.preset;
  }
  if (action.month) {
    node.dataset.analyticsMonth = action.month;
  }
  node.classList.add("analytics-action");
  if (node.tagName !== "BUTTON") {
    node.tabIndex = 0;
    if (!node.hasAttribute("role")) {
      node.setAttribute("role", "button");
    }
  }
}

function onAnalyticsAction(event) {
  if (event.type === "keydown" && !["Enter", " "].includes(event.key)) {
    return;
  }
  const target = event.target instanceof Element ? event.target : null;
  const trigger = target ? target.closest("[data-analytics-action]") : null;
  if (!trigger) {
    return;
  }
  event.preventDefault();
  runAnalyticsAction(trigger.dataset.analyticsAction, trigger.dataset);
}

function runAnalyticsAction(action, data = {}) {
  if (action === "missingCost") {
    openDrilldownWidget("missingCost");
    return;
  }
  if (action === "missingMapping") {
    openDrilldownWidget("missingMapping");
    return;
  }
  if (action === "onecReconciliationDelta") {
    els.onecFilterDeltaOnly.checked = true;
    selectDetailTab("onecReconciliation");
    if (state.onecReconciliationLoaded) {
      loadOnecReconciliation(currentClientLoadContext());
    }
    scrollToDetailPanel("onecReconciliation");
    return;
  }
  if (action === "rowsPreset") {
    openProductsPreset(data.rowPreset || "");
    return;
  }
  if (action === "lostSales") {
    selectDetailTab("lostSales");
    scrollToDetailPanel("lostSales");
    return;
  }
  if (action === "month") {
    openProductsMonth(data.analyticsMonth || "");
    return;
  }
  if (action === "ozonMart") {
    selectDetailTab("products");
    if (shouldRenderOzonMartInReportRows()) {
      renderOzonMartReportRows();
    }
    scrollToDetailPanel("products");
  }
}

function openProductsPreset(preset) {
  selectDetailTab("products");
  selectRowsPreset(preset, { load: false });
  applyRowsFilters();
  scrollToDetailPanel("products");
}

function openProductsMonth(month) {
  selectDetailTab("products");
  selectRowsPreset("", { load: false });
  setSelectValue(els.filterMonth, month);
  els.filterPeriodStart.value = "";
  els.filterPeriodEnd.value = "";
  applyRowsFilters();
  scrollToDetailPanel("products");
}

function scrollToDetailPanel(tab) {
  const panel = document.querySelector(`[data-detail-panel="${tab}"]`);
  if (panel) {
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function setSelectValue(control, value) {
  const nextValue = String(value || "");
  const exists = Array.from(control.options).some((option) => option.value === nextValue);
  control.value = exists ? nextValue : "";
}

function renderMoneyTrendChart(target, monthly) {
  const rows = asArray(monthly).filter(
    (row) => Number(row.revenue || 0) || Number(row.profit || 0),
  );
  if (!rows.length) {
    renderAnalyticsEmpty(target, "Нет месячных данных для динамики.");
    return;
  }
  renderColumnChart(
    target,
    rows.map((row) => ({
      label: row.month || "-",
      meta: `Маржа ${percent(row.margin)}`,
      action: { name: "month", month: row.month || "" },
      series: [
        {
          label: "Выручка",
          value: Number(row.revenue || 0),
          tone: "revenue",
          display: money(row.revenue || 0),
        },
        {
          label: "Прибыль",
          value: Number(row.profit || 0),
          tone: Number(row.profit || 0) < 0 ? "negative" : "profit",
          display: signedMoney(row.profit || 0),
        },
      ],
    })),
    {
      legend: [
        ["revenue", "Выручка"],
        ["profit", "Прибыль"],
      ],
    },
  );
}

function renderUnitProfitAndLossTable(target, kpis, expenses) {
  const revenue = Number(kpis.revenue || 0);
  const profit = Number(kpis.profit || 0);
  const expenseRows = asArray(expenses)
    .map((row) => ({
      label: row.expense || "Расход",
      amount: Math.abs(Number(row.amount || 0)),
    }))
    .filter((row) => row.amount > 0);
  if (!revenue && !profit && !expenseRows.length) {
    renderAnalyticsEmpty(target, "Нет данных для P&L юнит-экономики.");
    return;
  }
  const expenseTotal = expenseRows.reduce((total, row) => total + row.amount, 0);
  const unallocated = Math.max(0, revenue - profit - expenseTotal);
  const rows = [
    { label: "Выручка после СПП", amount: revenue, tone: "revenue" },
    ...expenseRows.map((row) => ({
      label: row.label,
      amount: -row.amount,
      tone: "expense",
    })),
    ...(unallocated > 1
      ? [
          {
            label: "Прочие расходы / округления",
            amount: -unallocated,
            tone: "expense",
          },
        ]
      : []),
    {
      label: "Прибыль после налогов",
      amount: profit,
      tone: profit < 0 ? "negative result" : "profit result",
      action: profit < 0 ? { name: "rowsPreset", preset: "losses" } : null,
    },
  ];
  target.replaceChildren(profitAndLossTable(rows, revenue));
}

function renderLossDriversChart(target, liquidityRows, lostSales) {
  const losses = asArray(liquidityRows)
    .filter((row) => Number(row.profit || 0) < 0)
    .map((row) => ({
      label: row.product || row.liquidityDriver || "Убыточная группа",
      value: Math.abs(Number(row.profit || 0)),
      meta: row.liquidityDriver || row.liquidityStatus || "Отрицательная прибыль",
      tone: "negative",
      action: { name: "rowsPreset", preset: "losses" },
    }));
  const missed = asArray(lostSales)
    .filter((row) => Number(row.lostProfit || 0) > 0)
    .map((row) => ({
      label: row.product || row.article1c || "Упущенная продажа",
      value: Number(row.lostProfit || 0),
      meta: "Упущенная прибыль",
      tone: "missed",
      action: { name: "lostSales" },
    }));
  const rows = [...losses, ...missed]
    .sort((left, right) => right.value - left.value)
    .slice(0, 6);
  renderBarRows(target, rows, {
    emptyText: "Нет убыточных строк и упущенной прибыли для рейтинга.",
  });
}

function renderReturnsChart(target, monthly, kpis) {
  const rows = asArray(monthly)
    .map((row) => {
      const sales = Number(row.sales || 0);
      const returns = Number(row.returns || 0);
      const rateValue = row.return_rate ?? row.returnRate;
      const rate = rateValue === null || rateValue === undefined
        ? sales
          ? returns / sales
          : 0
        : Number(rateValue || 0);
      return {
        label: row.month || "-",
        meta: `Возвратность ${percent(rate)}`,
        action: { name: "month", month: row.month || "" },
        series: [
          {
            label: "Возвраты",
            value: returns,
            tone: "returns",
            display: `${number(returns)} шт`,
          },
        ],
      };
    })
    .filter((row) => Number(row.series[0].value || 0));
  const sales = Number(kpis.sales || 0);
  const returns = Number(kpis.returns || 0);
  if (!rows.length && !returns) {
    renderAnalyticsEmpty(target, "Нет возвратов в текущей витрине.");
    return;
  }
  const total = document.createElement("p");
  total.className = "analytics-summary-line";
  total.textContent = `Итого: ${number(returns)} шт, возвратность ${percent(
    sales ? returns / sales : null,
  )}`;
  const chart = columnChartNode(rows, { compact: true });
  target.replaceChildren(total, chart);
}

function renderColumnChart(target, groups, options = {}) {
  const safeGroups = asArray(groups).filter((group) =>
    asArray(group.series).some((item) => Number(item.value || 0)),
  );
  if (!safeGroups.length) {
    renderAnalyticsEmpty(target, options.emptyText || "Нет данных для диаграммы.");
    return;
  }
  const nodes = [];
  if (options.legend) {
    nodes.push(analyticsLegend(options.legend));
  }
  nodes.push(columnChartNode(safeGroups, options));
  target.replaceChildren(...nodes);
}

function columnChartNode(groups, options = {}) {
  const maxValue = maxAbsValue(
    groups.flatMap((group) => asArray(group.series).map((item) => item.value)),
  );
  const chart = document.createElement("div");
  chart.className = options.compact
    ? "analytics-column-chart compact"
    : "analytics-column-chart";
  groups.forEach((group) => {
    const item = document.createElement("div");
    item.className = "analytics-column-group";
    applyAnalyticsActionAttributes(item, group.action);

    const columns = document.createElement("div");
    columns.className = "analytics-columns";
    asArray(group.series).forEach((series) => {
      columns.append(analyticsColumn(series, maxValue));
    });

    const label = document.createElement("strong");
    label.className = "analytics-column-label";
    label.textContent = group.label || "-";

    item.append(columns, label);
    if (group.meta) {
      const meta = document.createElement("span");
      meta.className = "analytics-column-meta";
      meta.textContent = group.meta;
      item.append(meta);
    }
    chart.append(item);
  });
  return chart;
}

function analyticsColumn(series, maxValue) {
  const wrapper = document.createElement("div");
  wrapper.className = `analytics-column-wrapper ${series.tone || ""}`.trim();

  const value = document.createElement("span");
  value.className = "analytics-column-value";
  value.textContent = series.display || signedMoney(series.value);

  const track = document.createElement("div");
  track.className = "analytics-column-track";
  const bar = document.createElement("div");
  bar.className = Number(series.value || 0) < 0
    ? "analytics-column negative"
    : "analytics-column";
  bar.style.height = `${barWidth(series.value, maxValue)}%`;
  track.append(bar);

  const label = document.createElement("small");
  label.textContent = series.label || "";
  wrapper.append(value, track, label);
  return wrapper;
}

function profitAndLossTable(rows, revenue) {
  const table = document.createElement("div");
  table.className = "analytics-pl-table";
  table.setAttribute("role", "table");

  const header = document.createElement("div");
  header.className = "analytics-pl-row header";
  header.setAttribute("role", "row");
  ["Статья", "Сумма", "% выручки"].forEach((label) => {
    const cell = document.createElement("span");
    cell.setAttribute("role", "columnheader");
    cell.textContent = label;
    header.append(cell);
  });
  table.append(header);

  asArray(rows)
    .filter(
      (row) =>
        row.amount == null
          ? Boolean(row.display) || String(row.tone || "").includes("result")
          : Number(row.amount || 0) || String(row.tone || "").includes("result"),
    )
    .forEach((row) => {
      const item = document.createElement("div");
      item.className = `analytics-pl-row ${row.tone || ""}`.trim();
      item.setAttribute("role", "row");
      applyAnalyticsActionAttributes(item, row.action);

      const label = document.createElement("strong");
      label.setAttribute("role", "cell");
      label.textContent = row.label || "-";

      const amount = document.createElement("span");
      amount.className = "analytics-pl-value";
      amount.setAttribute("role", "cell");
      amount.textContent = row.amount == null ? row.display || "-" : signedMoney(row.amount);

      const share = document.createElement("span");
      share.className = "analytics-pl-share";
      share.setAttribute("role", "cell");
      share.textContent = revenue && row.amount != null ? percent(Number(row.amount) / revenue) : "-";

      item.append(label, amount, share);
      table.append(item);
    });

  return table;
}

function renderBarRows(target, rows, options = {}) {
  const safeRows = asArray(rows).filter((row) => Number(row.value || 0));
  if (!safeRows.length) {
    renderAnalyticsEmpty(target, options.emptyText || "Нет данных для графика.");
    return;
  }
  const maxValue = maxAbsValue(safeRows.map((row) => row.value));
  const list = document.createElement("div");
  list.className = "analytics-bar-list";
  safeRows.forEach((row) => list.append(analyticsBarRow(row, maxValue, options)));
  target.replaceChildren(list);
}

function renderCountRows(target, rows) {
  const safeRows = asArray(rows).filter((row) => Number(row.value || 0));
  if (!safeRows.length) {
    renderAnalyticsEmpty(target, "Нет задач для отображения.");
    return;
  }
  const maxValue = maxAbsValue(safeRows.map((row) => row.value));
  const list = document.createElement("div");
  list.className = "analytics-bar-list";
  safeRows.forEach((row) => {
    const item = document.createElement("div");
    item.className = `analytics-bar-row ${row.tone || ""}`.trim();
    applyAnalyticsActionAttributes(item, row.action);

    const header = document.createElement("div");
    header.className = "analytics-bar-header";
    const label = document.createElement("span");
    label.textContent = row.label || "-";
    const value = document.createElement("strong");
    value.textContent = `${number(row.value)} строк`;
    header.append(label, value);

    const track = document.createElement("div");
    track.className = "analytics-track";
    const bar = document.createElement("div");
    bar.className = "analytics-bar";
    bar.style.width = `${barWidth(row.value, maxValue)}%`;
    track.append(bar);

    const meta = document.createElement("small");
    meta.textContent = row.meta || "";
    item.append(header, track);
    if (meta.textContent) {
      item.append(meta);
    }
    list.append(item);
  });
  target.replaceChildren(list);
}

function analyticsBar(label, value, maxValue, tone) {
  const item = document.createElement("div");
  item.className = `analytics-pair-bar ${tone}`;

  const name = document.createElement("span");
  name.textContent = label;

  const track = document.createElement("div");
  track.className = "analytics-track";
  const bar = document.createElement("div");
  bar.className = value < 0 ? "analytics-bar negative" : "analytics-bar";
  bar.style.width = `${barWidth(value, maxValue)}%`;
  track.append(bar);

  const valueNode = document.createElement("strong");
  valueNode.textContent = money(value);
  item.append(name, track, valueNode);
  return item;
}

function analyticsBarRow(row, maxValue, options = {}) {
  const item = document.createElement("div");
  item.className = `analytics-bar-row ${row.tone || ""}`.trim();
  applyAnalyticsActionAttributes(item, row.action);

  const header = document.createElement("div");
  header.className = "analytics-bar-header";
  const label = document.createElement("span");
  label.textContent = row.label || "-";
  const value = document.createElement("strong");
  value.textContent = options.percent ? percent(row.value) : signedMoney(row.value);
  header.append(label, value);

  const track = document.createElement("div");
  track.className = "analytics-track";
  const bar = document.createElement("div");
  bar.className = row.value < 0 ? "analytics-bar negative" : "analytics-bar";
  bar.style.width = `${barWidth(row.value, maxValue)}%`;
  track.append(bar);

  const meta = document.createElement("small");
  meta.textContent = row.meta || "";
  item.append(header, track);
  if (meta.textContent) {
    item.append(meta);
  }
  return item;
}

function analyticsLegend(items) {
  const legend = document.createElement("div");
  legend.className = "analytics-legend";
  items.forEach(([tone, label]) => {
    const item = document.createElement("span");
    const marker = document.createElement("i");
    marker.className = tone;
    item.append(marker, document.createTextNode(label));
    legend.append(item);
  });
  return legend;
}

function renderAnalyticsEmpty(target, text) {
  const empty = document.createElement("div");
  empty.className = "analytics-empty";
  empty.textContent = text;
  target.replaceChildren(empty);
}

function maxAbsValue(values) {
  return Math.max(1, ...asArray(values).map((value) => Math.abs(Number(value || 0))));
}

function barWidth(value, maxValue) {
  return Math.max(3, Math.min(100, (Math.abs(Number(value || 0)) / maxValue) * 100));
}

function percent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return `${Math.round(Number(value || 0) * 1000) / 10}%`;
}

function signedMoney(value) {
  const numericValue = Number(value || 0);
  return numericValue < 0 ? `−${money(Math.abs(numericValue))}` : money(numericValue);
}

function signedNumber(value) {
  const numericValue = Number(value || 0);
  const formatted = number(Math.abs(numericValue));
  if (numericValue < 0) {
    return `−${formatted}`;
  }
  return numericValue > 0 ? `+${formatted}` : formatted;
}

function renderLiquidity(rows) {
  const safeRows = asArray(rows);
  els.liquidityCount.textContent = safeRows.length
    ? `${safeRows.length} групп`
    : "Нет групп";
  const lossRows = safeRows.filter((row) => Number(row.profit || 0) < 0);
  const reviewRows = safeRows.filter((row) => !["ok", "ок"].includes(normalize(row.status)));
  const bestRows = safeRows.filter((row) => Number(row.profit || 0) > 0);
  const lossAmount = lossRows.reduce(
    (total, row) => total + Math.abs(Number(row.profit || 0)),
    0,
  );
  const revenueAtRisk = lossRows.reduce(
    (total, row) => total + Math.max(0, Number(row.revenue || 0)),
    0,
  );
  const mainDriver = liquidityMainDriver(lossRows.length ? lossRows : safeRows);
  renderLiquiditySummary({
    totalRows: safeRows.length,
    lossRows: lossRows.length,
    reviewRows: reviewRows.length,
    lossAmount,
    mainDriver,
  });
  renderMetrics(els.liquidityGrid, [
    [
      "Показано",
      number(safeRows.length),
      "Худшие группы и контрольные плюсовые позиции из витрины.",
      "info",
    ],
    [
      "Красная зона",
      `${number(lossRows.length)} · ${percent(safeRows.length ? lossRows.length / safeRows.length : 0)}`,
      "Группы с отрицательным МД после налогов.",
      lossRows.length ? "bad" : "ok",
    ],
    [
      "Потери в выборке",
      lossAmount ? signedMoney(-lossAmount) : "0 ₽",
      `Отрицательный МД; выручка в этих строках ${money(revenueAtRisk)}.`,
      lossAmount ? "bad" : "ok",
    ],
    [
      "Статус не ОК",
      `${number(reviewRows.length)} · ${percent(safeRows.length ? reviewRows.length / safeRows.length : 0)}`,
      "Нужна проверка себестоимости, сопоставления или источника.",
      reviewRows.length ? "warning" : "ok",
    ],
    [
      "Драйвер №1",
      mainDriver.label,
      mainDriver.count
        ? `${number(mainDriver.count)} групп · ${signedMoney(-mainDriver.loss)}`
        : "Недостаточно данных для группировки.",
      mainDriver.loss ? "warning" : "info",
    ],
    [
      "Плюсовых групп",
      number(bestRows.length),
      bestRows.length ? "Есть позиции с МД выше нуля." : "В показанной выборке плюсовых групп нет.",
      bestRows.length ? "ok" : "warning",
    ],
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
    cell.colSpan = 19;
    cell.textContent = "Нет данных для витрины ликвидности.";
    row.append(cell);
    els.liquidityRows.replaceChildren(row);
    return;
  }
  els.liquidityRows.replaceChildren(
    ...visible.map((item) => {
      const row = document.createElement("tr");
      row.className = tableRowClass(item);
      appendTableCells(row, [
        { value: item.month || "-", className: "text-nowrap" },
        {
          value: item.liquidityStatus || "-",
          badge: true,
          tone: liquidityTone(item.liquidityStatus, item.profit),
        },
        { value: item.liquidityDriver || "-", className: "text-wide" },
        { value: item.product || "-", className: "text-wide text-strong" },
        { value: item.articleWb || "-", className: "text-code" },
        { value: item.article1c || "-", className: "text-code" },
        { value: number(item.sales || 0), className: "numeric" },
        { value: money(item.revenue || 0), className: "numeric" },
        { value: money(item.cost || 0), className: "numeric muted" },
        {
          value: signedMoney(item.md1Markup || 0),
          className: `numeric ${valueTone(item.md1Markup)}`,
          title: "МД1: выручка после СПП минус себестоимость 1С.",
        },
        {
          value: signedMoney(item.md2AfterCommission || 0),
          className: `numeric ${valueTone(item.md2AfterCommission)}`,
          title: "МД2: МД1 минус комиссия WB.",
        },
        {
          value: signedMoney(item.md3AfterStorage || 0),
          className: `numeric ${valueTone(item.md3AfterStorage)}`,
          title: "МД3: МД2 минус хранение WB.",
        },
        {
          value: signedMoney(item.md4AfterLogisticsAcceptance || 0),
          className: `numeric ${valueTone(item.md4AfterLogisticsAcceptance)}`,
          title: "МД4: МД3 минус логистика и приемка WB.",
        },
        {
          value: signedMoney(item.md5AfterPromotion || 0),
          className: `numeric ${valueTone(item.md5AfterPromotion)}`,
          title: "МД5: МД4 минус продвижение WB.",
        },
        {
          value: signedMoney(item.md6BeforeTax || 0),
          className: `numeric ${valueTone(item.md6BeforeTax)}`,
          title: "МД6: МД5 минус штрафы/доплаты и эквайринг, до налогов.",
        },
        {
          value: signedMoney(item.profit || 0),
          className: `numeric ${valueTone(item.profit)}`,
          title: "Финальный МД после НДС и налога с выручки.",
        },
        {
          value: item.margin || item.margin === 0 ? percent(item.margin) : "-",
          className: `numeric ${valueTone(item.margin)}`,
        },
        {
          value:
            item.unitProfit || item.unitProfit === 0
              ? signedMoney(item.unitProfit)
              : "-",
          className: `numeric ${valueTone(item.unitProfit)}`,
        },
        {
          value: statusLabel(item.status),
          badge: true,
          tone: statusTone(item.status, item.statusReason || item.lossDriver),
          title: statusExplanation(item.status, item.statusReason),
        },
      ]);
      return row;
    }),
  );
}

function renderLiquiditySummary(summary) {
  if (!summary.totalRows) {
    els.liquiditySummary.textContent =
      "Нет строк для оценки ликвидности: проверьте выбранный период и кабинет.";
    return;
  }
  const parts = [
    `Показано ${number(summary.totalRows)} групп`,
    `${number(summary.lossRows)} в минусе`,
    `${number(summary.reviewRows)} со статусом не ОК`,
  ];
  if (summary.lossAmount) {
    parts.push(`потери ${signedMoney(-summary.lossAmount)}`);
  }
  if (summary.mainDriver.count) {
    parts.push(`главный драйвер: ${summary.mainDriver.label}`);
  }
  els.liquiditySummary.textContent = `${parts.join("; ")}. Таблица ниже отсортирована от самых убыточных к контрольным плюсовым позициям.`;
}

function liquidityMainDriver(rows) {
  const groups = new Map();
  asArray(rows).forEach((row) => {
    const label =
      row.liquidityDriver ||
      row.lossDriver ||
      row.statusReason ||
      row.liquidityStatus ||
      row.status ||
      "Драйвер не указан";
    const current = groups.get(label) || { label, count: 0, loss: 0 };
    current.count += 1;
    current.loss += Math.abs(Math.min(0, Number(row.profit || 0)));
    groups.set(label, current);
  });
  return (
    [...groups.values()].sort(
      (left, right) =>
        right.loss - left.loss ||
        right.count - left.count ||
        left.label.localeCompare(right.label, "ru"),
    )[0] || { label: "Нет данных", count: 0, loss: 0 }
  );
}

function renderMetrics(target, items) {
  target.replaceChildren(
    ...items.map(([label, value, caption = "", tone = ""]) => {
      const item = document.createElement("div");
      item.className = `metric ${tone ? `metric-${tone}` : ""}`.trim();
      const labelNode = document.createElement("span");
      labelNode.textContent = label;
      const valueNode = document.createElement("strong");
      valueNode.textContent = String(value);
      item.append(labelNode, valueNode);
      if (caption) {
        const captionNode = document.createElement("small");
        captionNode.textContent = String(caption);
        item.append(captionNode);
      }
      return item;
    }),
  );
}

function renderReasons(target, reasons, emptyText = "Нет задач", tone = "review") {
  const safeReasons = asArray(reasons);
  if (!safeReasons.length) {
    const item = document.createElement("li");
    item.className = "reason-item task-card is-empty";
    item.textContent = emptyText;
    target.replaceChildren(item);
    return;
  }
  target.replaceChildren(
    ...safeReasons.map((reason, index) => {
      const item = document.createElement("li");
      item.className = `reason-item task-card ${
        tone === "blocker" ? "is-blocker" : "is-review"
      }`;
      const guide = reasonGuide(reason);
      const marker = document.createElement("span");
      marker.className = "reason-marker";
      marker.textContent = String(index + 1);
      const content = document.createElement("div");
      const message = document.createElement("strong");
      message.textContent = reason.message || "Проверить пункт";
      content.append(message);
      if (reason.count || reason.count === 0) {
        const count = document.createElement("small");
        count.textContent = `${number(reason.count)} строк`;
        content.append(count);
      }
      const hint = document.createElement("small");
      hint.className = "reason-hint";
      hint.textContent = guide.hint;
      const action = document.createElement("button");
      action.type = "button";
      action.className = "reason-action-link";
      action.textContent = guide.label;
      action.addEventListener("click", () => runReasonAction(guide.action));
      const markDone = document.createElement("button");
      markDone.type = "button";
      markDone.className = "reason-action-link task-done-link";
      markDone.textContent = "Проверено";
      markDone.addEventListener("click", () => setTaskReviewed(reason, true));
      const actions = document.createElement("div");
      actions.className = "task-card-actions";
      actions.append(action, markDone);
      content.append(hint, actions);
      item.append(marker, content);
      return item;
    }),
  );
}

function renderDoneTasks(readiness, openReasons = []) {
  const tasks = [];
  const blockers = asArray(readiness.blockingReasons);
  const reviews = asArray(readiness.reviewReasons);
  asArray(openReasons)
    .filter((reason) => isTaskReviewed(reason))
    .forEach((reason) => {
      tasks.push({
        title: `Проверено: ${reason.message || "задача по отчету"}`,
        detail: "Отмечено аналитиком. Расчетный статус изменится после пересборки отчета.",
        reason,
      });
    });
  if (state.reportId) {
    tasks.push({
      title: "Excel собран",
      detail: "Расчетный артефакт доступен в верхней панели.",
    });
  }
  if (!blockers.length) {
    tasks.push({
      title: "Блокеры отправки сняты",
      detail: "Критических стоп-факторов в readiness нет.",
    });
  }
  if (!reviews.length) {
    tasks.push({
      title: "Проверки данных закрыты",
      detail: "Открытых задач по корректности строк нет.",
    });
  }
  if (readiness.status === "ready") {
    tasks.push({
      title: "Пакет готов клиенту",
      detail: "Можно открыть клиентский вывод и приложить Excel.",
    });
  }
  if (!tasks.length) {
    const item = document.createElement("li");
    item.className = "reason-item task-card is-empty";
    item.textContent = "Готовые задачи появятся после исправления данных.";
    els.doneReasons.replaceChildren(item);
    return;
  }
  els.doneReasons.replaceChildren(
    ...tasks.map((task) => {
      const item = document.createElement("li");
      item.className = "reason-item task-card is-done";
      const marker = document.createElement("span");
      marker.className = "reason-marker";
      marker.textContent = "OK";
      const content = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = task.title;
      const detail = document.createElement("small");
      detail.textContent = task.detail;
      content.append(title, detail);
      if (task.reason) {
        const reopen = document.createElement("button");
        reopen.type = "button";
        reopen.className = "reason-action-link task-reopen-link";
        reopen.textContent = "Вернуть в работу";
        reopen.addEventListener("click", () => setTaskReviewed(task.reason, false));
        content.append(reopen);
      }
      item.append(marker, content);
      return item;
    }),
  );
}

function taskStatusStorageKey() {
  return `shumeyko.task-board.${state.reportId || "no-report"}`;
}

function taskKey(reason) {
  return normalize([reason?.code, reason?.message].filter(Boolean).join(":"));
}

function taskStatusMap() {
  try {
    return JSON.parse(window.localStorage.getItem(taskStatusStorageKey()) || "{}") || {};
  } catch (_error) {
    return {};
  }
}

function isTaskReviewed(reason) {
  return Boolean(taskStatusMap()[taskKey(reason)]);
}

function setTaskReviewed(reason, reviewed) {
  const key = taskKey(reason);
  if (!key) {
    return;
  }
  const statuses = taskStatusMap();
  if (reviewed) {
    statuses[key] = {
      code: reason?.code || "",
      message: reason?.message || "",
      checkedAt: new Date().toISOString(),
    };
  } else {
    delete statuses[key];
  }
  try {
    window.localStorage.setItem(taskStatusStorageKey(), JSON.stringify(statuses));
  } catch (_error) {
    return;
  }
  renderReport();
}

function reasonGuide(reason) {
  const code = normalize(reason.code);
  const guides = {
    missing_cost: {
      hint: "Расшифровка откроет строки, где не подтянулась подтвержденная себестоимость из 1С.",
      label: "Показать строки без себестоимости",
      action: "missingCost",
    },
    mapping_review: {
      hint: "Расшифровка откроет товары без сопоставления WB-1С или с неоднозначной связью.",
      label: "Показать строки сопоставления",
      action: "missingMapping",
    },
    onec_reconciliation_review: {
      hint: "Откройте сверку документов WB ↔ 1С и проверьте дельты, выплаты и наличие документов 1С.",
      label: "Открыть сверку 1С",
      action: "onecReconciliation",
    },
    data_quality_review: {
      hint: "Расшифровка откроет все строки со статусом, отличным от OK.",
      label: "Показать строки к проверке",
      action: "reviewRows",
    },
    too_many_data_quality_issues: {
      hint: "Сначала разберите строки не OK, затем пересчитайте отчет.",
      label: "Показать строки к проверке",
      action: "reviewRows",
    },
    partial_source: {
      hint: "Проверьте строки с неполным источником. Если источник не закрыт, укажите ограничение клиенту или дождитесь полной выгрузки.",
      label: "Показать строки к проверке",
      action: "reviewRows",
    },
    source_load_incomplete: {
      hint: "Это проблема загрузки: расшифровка покажет статус последнего refresh и источники.",
      label: "Показать источники",
      action: "sources",
    },
    source_load_failed: {
      hint: "Источник не загрузился: расшифровка покажет последний refresh и проблемные коллекции.",
      label: "Показать источники",
      action: "sources",
    },
    source_loads_missing: {
      hint: "Нет lineage загрузок: проверьте последнюю выгрузку источников и пересоберите отчет.",
      label: "Показать источники",
      action: "sources",
    },
    source_coverage_gap: {
      hint: "Проверьте даты периода сверху: покрытие источников не совпадает с периодом отчета.",
      label: "Проверить даты",
      action: "period",
    },
    partial_period: {
      hint: "Проверьте даты сверху и решите: указываем клиенту предварительный период или ждем полного периода.",
      label: "Проверить даты",
      action: "period",
    },
    client_draft_missing: {
      hint: "Откройте клиентский вывод и подготовьте текст для отправки вместе с Excel.",
      label: "Открыть клиентский вывод",
      action: "clientOutput",
    },
    client_draft_not_ready: {
      hint: "Откройте клиентский вывод, проверьте черновик и доведите его до готового состояния.",
      label: "Открыть клиентский вывод",
      action: "clientOutput",
    },
  };
  return (
    guides[code] || {
      hint: "Откройте строки к проверке и разберите статусы в таблице товаров.",
      label: "Показать строки к проверке",
      action: "reviewRows",
    }
  );
}

function runReasonAction(action) {
  if (action === "missingCost") {
    openDrilldownWidget("missingCost");
    return;
  }
  if (action === "missingMapping") {
    openDrilldownWidget("missingMapping");
    return;
  }
  if (action === "reviewRows") {
    openDrilldownWidget("review");
    return;
  }
  if (action === "sources") {
    openDrilldownWidget("sources");
    return;
  }
  if (action === "onecReconciliation") {
    selectDetailTab("onecReconciliation");
    document
      .querySelector("#detail-panel-onec-reconciliation")
      .scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  if (action === "integrations") {
    openIntegrationsWidget();
    return;
  }
  if (action === "clientOutput") {
    openClientOutputWidget();
    return;
  }
  if (action === "period") {
    document.querySelector(".topbar").scrollIntoView({ behavior: "smooth", block: "start" });
    window.setTimeout(() => els.topbarPeriodStart.focus(), 180);
  }
}

function renderReviewRows(rows, total) {
  if (shouldRenderOzonMartInReportRows()) {
    renderOzonMartReportRows();
    return;
  }
  renderReportRowsHeader("wb");
  renderReportRowsControls("wb");
  const safeRows = asArray(rows);
  els.rowsCount.textContent = total ? `${total} строк` : "Нет строк";
  renderReportRowsTable(els.reviewRows, safeRows);
}

function shouldRenderOzonMartInReportRows() {
  return shouldUseOzonWorkingView();
}

function shouldUseOzonWorkingView() {
  const selectedCabinetId = selectedMarketplaceCabinetId();
  if (!selectedCabinetId) {
    return false;
  }
  const selectedCabinet = selectedMarketplaceCabinet();
  if (selectedCabinet) {
    return isOzonMarketplaceCabinet(selectedCabinet);
  }
  return hasOzonMarketplaceContext(state.latestOzonDiagnostics);
}

function renderOzonWorkingView() {
  if (!state.latestOzonDiagnostics) {
    renderReportRowsHeader("ozon");
    renderReportRowsControls("ozon");
    els.rowsTitle.textContent = "Ozon: детализация по товарам";
    els.rowsCount.textContent = "Загрузка";
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 12;
    cell.textContent = "Загружаем расчет Ozon.";
    row.append(cell);
    els.reviewRows.replaceChildren(row);
    return;
  }
  renderOzonKpis(state.latestOzonDiagnostics);
  renderOzonAnalytics(state.latestOzonDiagnostics);
  renderOzonMartReportRows();
}

function renderOzonMartReportRows() {
  const mart =
    state.latestOzonDiagnostics?.ozonMart ||
    state.latestOzonDiagnostics?.unitRows ||
    {};
  const rows = asArray(mart.rows);
  const rowCount = Number(mart.rowCount || rows.length || 0);
  renderReportRowsHeader("ozon");
  renderReportRowsControls("ozon");
  els.rowsTitle.textContent = "Ozon: детализация по товарам";
  els.rowsCount.textContent = rowCount ? `${number(rowCount)} строк` : "Нет строк";
  if (!rows.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 12;
    cell.textContent = state.latestOzonDiagnostics
      ? "Строки расчета Ozon не найдены для выбранного периода."
      : "Загружаем расчет Ozon.";
    row.append(cell);
    els.reviewRows.replaceChildren(row);
    return;
  }
  els.reviewRows.replaceChildren(...rows.map(ozonMartReportRowNode));
}

function renderReportRowsControls(mode) {
  const ozonMode = mode === "ozon";
  const presetBar = document.querySelector(".row-preset-bar");
  if (presetBar) {
    presetBar.hidden = ozonMode;
  }
  if (els.rowsFilterForm) {
    els.rowsFilterForm.hidden = ozonMode;
  }
}

function renderReportRowsHeader(mode) {
  if (!els.reviewRowsHead) {
    return;
  }
  els.rowsTitle.textContent =
    mode === "ozon" ? "Ozon: детализация по товарам" : "Юнит-экономика";
  const headers =
    mode === "ozon"
      ? [
          "Offer / SKU",
          "Товар",
          "Количество",
          "Выручка 1C",
          "Себестоимость",
          "Комиссии / услуги",
          "Партнерские услуги",
          "Логистика / хранение",
          "Прибыль до налогов / маржа",
          "Номенклатура 1C",
          "Статус",
          "Причина / действие",
        ]
      : [
          "Месяц 1С",
          "Документ-отчет",
          "Отчет WB",
          "Дата отчета",
          "Кабинет",
          "Товар",
          "Артикул WB",
          "Артикул 1С",
          "Баркод",
          "Схема",
          "Статус",
          "Продажи",
          "Возвраты",
          "Выручка",
          "Прибыль",
          "Маржа",
          "На шт",
        ];
  const row = document.createElement("tr");
  headers.forEach((label) => {
    const cell = document.createElement("th");
    cell.textContent = label;
    row.append(cell);
  });
  els.reviewRowsHead.replaceChildren(row);
}

function ozonMartReportRowNode(item) {
  const row = document.createElement("tr");
  row.className = ozonUnitRowClass(item);
  const cogsAmount = item.cogsAmount ?? item.cogs;
  const profitAmount = item.profitAmount ?? item.profit;
  appendTableCells(row, [
    { value: ozonUnitOfferText(item), className: "text-code" },
    { value: item.productName || "-", className: "text-wide text-strong" },
    {
      value: item.quantity == null ? "-" : number(item.quantity),
      className: "numeric",
    },
    { value: ozonUnitRevenueText(item), className: "numeric" },
    { value: ozonUnitNullableMoney(cogsAmount), className: "numeric" },
    {
      value: ozonUnitExpenseText(
        item,
        "commissionServices",
      ),
      className: "numeric",
    },
    {
      value: ozonUnitExpenseText(item, "partnerServices"),
      className: "numeric",
    },
    {
      value: ozonUnitExpenseText(
        item,
        "logisticsStorage",
      ),
      className: "numeric",
    },
    {
      value: ozonUnitProfitMarginText(profitAmount, item.margin, item.expenseStatus),
      className: `numeric ${metricToneForAmount(profitAmount)}`,
    },
    { value: ozonUnitOnecText(item), className: "text-wide" },
    {
      value: ozonUnitStatusText(item.qualityStatus),
      badge: true,
      tone: item.qualityStatus === "ready" ? "ok" : "warning",
    },
    { value: ozonUnitProblemText(item), className: "text-wide" },
  ]);
  return row;
}

function renderOnecReconciliation(rows, total, kpis = {}) {
  const safeRows = asArray(rows);
  const documentCount = Number(
    kpis.documentCount ?? kpis.documentReconciliationRows ?? total ?? 0,
  );
  const okRows = Number(kpis.okRows || 0);
  const issueRows = Number(
    kpis.issueRows ?? kpis.documentReconciliationIssues ?? 0,
  );
  const quantityDelta = Number(kpis.quantityDelta || 0);
  const amountDelta = Number(
    kpis.amountDelta ?? kpis.documentReconciliationDeltaAmount ?? 0,
  );
  const missingOnecRows = Number(
    kpis.missingOnecRows ?? kpis.documentReconciliationMissingOnec ?? 0,
  );
  els.onecReconciliationCount.textContent = documentCount
    ? `${number(documentCount)} документов`
    : "Нет документов";
  renderMetrics(els.onecReconciliationGrid, [
    ["Документов", number(documentCount)],
    ["ОК", number(okRows)],
    ["К проверке", number(issueRows)],
    ["Дельта количества", number(quantityDelta)],
    ["Дельта суммы", money(amountDelta)],
    ["Нет факта 1С", number(missingOnecRows)],
  ]);
  renderOnecReconciliationRowsTable(els.onecReconciliationRows, safeRows, total);
}

function renderOnecReconciliationRowsTable(target, rows, total) {
  if (!rows.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 15;
    if (!total && els.onecFilterDeltaOnly.checked) {
      cell.textContent = "Расхождений WB ↔ 1С не найдено.";
    } else if (!total && !hasActiveOnecReconciliationFilters()) {
      cell.textContent = "Сверка с 1С не загружена в текущий report run.";
    } else {
      cell.textContent = "Строки сверки не найдены. Измените фильтры.";
    }
    row.append(cell);
    target.replaceChildren(row);
    return;
  }
  target.replaceChildren(...rows.map(onecReconciliationRowNode));
}

function onecReconciliationRowNode(item) {
  const row = document.createElement("tr");
  row.className = onecReconciliationRowClass(item);
  appendTableCells(row, [
    { value: item.salesPeriod || "-", className: "text-nowrap" },
    { value: item.cabinet || "-", className: "text-wide" },
    { value: item.organization || "-", className: "text-wide" },
    { value: item.documentType || "-", badge: true, tone: "neutral" },
    { value: item.expectedDocumentDate || "-", className: "text-nowrap" },
    { value: item.onecDocuments || "-", className: "text-wide text-code" },
    { value: number(item.wbQuantity || 0), className: "numeric" },
    {
      value:
        item.onecQuantity || item.onecQuantity === 0
          ? number(item.onecQuantity)
          : "-",
      className: "numeric",
    },
    {
      value:
        item.quantityDelta || item.quantityDelta === 0
          ? signedNumber(item.quantityDelta)
          : "-",
      className: `numeric delta ${valueTone(item.quantityDelta, { zero: "muted" })}`,
    },
    {
      value: item.wbAmount || item.wbAmount === 0 ? money(item.wbAmount) : "-",
      className: "numeric",
    },
    {
      value: item.onecAmount || item.onecAmount === 0 ? money(item.onecAmount) : "-",
      className: "numeric",
    },
    {
      value:
        item.amountDelta || item.amountDelta === 0
          ? signedMoney(item.amountDelta)
          : "-",
      className: `numeric delta ${valueTone(item.amountDelta, { zero: "muted" })}`,
    },
    {
      value: item.status || "-",
      badge: true,
      tone: reconciliationStatusTone(item.status),
    },
    {
      value: item.payoutStatus || "-",
      badge: true,
      tone: statusTone(item.payoutStatus),
    },
    { value: item.comment || "-", className: "text-wide" },
  ]);
  return row;
}

function renderDrilldownRows(rows, total) {
  const safeRows = asArray(rows);
  els.drilldownCount.textContent = total ? `${total} строк` : "Нет строк";
  renderReportRowsTable(els.drilldownRows, safeRows);
}

function renderSourceDrilldown() {
  const freshness = state.freshness || {};
  const summary = state.summary || {};
  const latestRefresh = summary.latestSourceRefresh || freshness.latestSourceRefresh || null;
  const sourceLoads = asArray(freshness.sourceLoads);
  const collections = asArray(latestRefresh?.collections);
  const sourceItems = collections.length ? collections : sourceLoads;
  const nodes = [];

  if (latestRefresh) {
    nodes.push(sourceRefreshNode(latestRefresh));
  }
  if (sourceItems.length) {
    nodes.push(...sourceItems.map(sourceLoadNode));
  } else {
    nodes.push(sourceEmptyNode(latestRefresh));
  }

  els.drilldownCount.textContent = sourceDrilldownCount(latestRefresh, sourceItems);
  els.drilldownSources.replaceChildren(...nodes);
}

function sourceRefreshNode(refresh) {
  const card = sourceCard("Последний refresh источников", refresh.status);
  const message = document.createElement("p");
  message.className = "source-load-message";
  message.textContent = refresh.safeMessage || sourceStatusHint(refresh.status);
  const meta = sourceMetaList([
    ["Статус", sourceStatusText(refresh.status)],
    ["Режим", refresh.mode || "-"],
    ["Период", sourcePeriodText(refresh)],
    ["Создан", formatDateTime(refresh.createdAt)],
    ["Завершен", formatDateTime(refresh.finishedAt) || "Не завершался"],
    ["Новый отчет", refresh.newReportRunId || "Не создан"],
  ]);
  const advice = document.createElement("p");
  advice.className = "source-load-advice";
  advice.textContent = sourceRefreshAdvice(refresh.status);
  card.append(message, meta, advice);
  return card;
}

function sourceLoadNode(item) {
  const title = item.sourceLabel || item.sourceType || "Источник";
  const card = sourceCard(title, item.status);
  const message = document.createElement("p");
  message.className = "source-load-message";
  message.textContent = sourceStatusHint(item.status, item.required);
  const meta = sourceMetaList([
    ["Тип", item.sourceType || "-"],
    ["Обязательный", item.required === false ? "Нет" : "Да"],
    ["Строк", number(item.rowCount || 0)],
    ["Кабинет", item.wbCabinetId || "Все"],
    ["Загружен", formatDateTime(item.loadedAt) || "-"],
  ]);
  card.append(message, meta);
  return card;
}

function sourceCard(title, status) {
  const card = document.createElement("section");
  card.className = `source-load-card ${sourceStatusTone(status)}`;
  const header = document.createElement("div");
  header.className = "source-load-card-header";
  const titleNode = document.createElement("h3");
  titleNode.textContent = title;
  const statusNode = document.createElement("span");
  statusNode.className = "source-load-status";
  statusNode.textContent = sourceStatusText(status);
  header.append(titleNode, statusNode);
  card.append(header);
  return card;
}

function sourceMetaList(items) {
  const list = document.createElement("dl");
  list.className = "source-load-meta";
  items
    .filter(([, value]) => value !== "" && value !== null && value !== undefined)
    .forEach(([label, value]) => {
      const term = document.createElement("dt");
      term.textContent = label;
      const detail = document.createElement("dd");
      detail.textContent = String(value);
      list.append(term, detail);
    });
  return list;
}

function sourceEmptyNode(refresh) {
  const card = sourceCard("Деталей по источникам нет", refresh?.status || "");
  const message = document.createElement("p");
  message.className = "source-load-message";
  message.textContent = refresh
    ? "Последний refresh есть, но коллекции источников не записаны."
    : "По текущему отчету нет lineage загрузок источников.";
  const advice = document.createElement("p");
  advice.className = "source-load-advice";
  advice.textContent =
    "После следующей загрузки здесь появятся WB/1C-коллекции, статусы и количество строк.";
  card.append(message, advice);
  return card;
}

function sourceDrilldownCount(refresh, items) {
  if (normalize(refresh?.status) === "blocked_low_disk") {
    return "Мало места";
  }
  if (items.length) {
    return `${items.length} источников`;
  }
  return "Нет деталей";
}

function sourcePeriodText(item) {
  const start = item.periodStart ? formatDateTime(item.periodStart).split(",")[0] : "";
  const end = item.periodEnd ? formatDateTime(item.periodEnd).split(",")[0] : "";
  return [start, end].filter(Boolean).join(" - ") || "-";
}

function sourceStatusText(status) {
  const value = normalize(status);
  if (value === "report_created") {
    return "Отчет создан";
  }
  if (
    ["ok", "loaded", "success", "ready", "completed", "empty_expected"].includes(
      value,
    )
  ) {
    return "Загружен";
  }
  if (value === "auth_failed") {
    return "Нет доступа";
  }
  if (value === "rate_limited") {
    return "Лимит API";
  }
  if (value === "queued") {
    return "В очереди";
  }
  if (value === "running") {
    return "Читает источники";
  }
  if (value === "source_loaded") {
    return "Источники загружены";
  }
  if (value === "rebuilding") {
    return "Собирает отчет";
  }
  if (value === "blocked_low_disk") {
    return "Мало места";
  }
  if (value === "blocked_active_refresh") {
    return "Уже идет refresh";
  }
  if (value === "needs_configuration") {
    return "Нужна настройка";
  }
  if (value === "needs_review") {
    return "Требует проверки";
  }
  if (value === "dry_run_ready") {
    return "Проверка прошла";
  }
  if (value.includes("fail") || value.includes("error")) {
    return "Ошибка";
  }
  return status || "Неизвестно";
}

function sourceStatusTone(status) {
  const value = normalize(status);
  if (
    [
      "ok",
      "loaded",
      "success",
      "ready",
      "completed",
      "empty_expected",
      "dry_run_ready",
      "report_created",
    ].includes(value)
  ) {
    return "is-ok";
  }
  if (
    value.includes("fail") ||
    value.includes("error") ||
    value.startsWith("blocked") ||
    value === "auth_failed"
  ) {
    return "is-blocked";
  }
  return "is-warning";
}

function sourceStatusHint(status, required = true) {
  const value = normalize(status);
  if (value === "report_created") {
    return "Полное обновление завершено, новый отчет создан.";
  }
  if (value === "queued") {
    return "Задача поставлена в очередь. Можно закрыть окно, статус продолжит обновляться.";
  }
  if (value === "running") {
    return "Идет read-only чтение WB, 1С и сопоставления. Страница остается доступной.";
  }
  if (value === "source_loaded") {
    return "Источники загружены, идет подготовка отчета или сохранение результата.";
  }
  if (value === "rebuilding") {
    return "Данные получены, собирается новый отчет.";
  }
  if (["ok", "loaded", "success", "ready", "completed"].includes(value)) {
    return "Источник загружен и участвует в текущем отчете.";
  }
  if (value === "empty_expected") {
    return "Источник проверен: за период нет строк, это допустимо.";
  }
  if (value === "auth_failed") {
    return "Источник не принял read-only ключ. Нужно проверить роли доступа.";
  }
  if (value === "rate_limited") {
    return "Провайдер ограничил частоту запросов. Повторите позже.";
  }
  if (value === "blocked_low_disk") {
    return "Refresh не стартовал: на диске меньше свободного места, чем требует лимит для снапшота.";
  }
  if (value === "needs_configuration") {
    return "Нужно заново проверить настройку read-only подключения.";
  }
  if (value === "needs_review") {
    return "Источник загрузился не полностью или требует ручной проверки.";
  }
  if (value === "dry_run_ready") {
    return "Готово к полному обновлению. Отчет еще не создан.";
  }
  if (value.includes("fail") || value.includes("error")) {
    return required === false
      ? "Опциональный источник не загрузился; отчет можно проверить с ограничением."
      : "Обязательный источник не загрузился, отчет нельзя отправлять без проверки.";
  }
  return "Проверьте последнюю загрузку и при необходимости повторите refresh.";
}

function sourceRefreshAdvice(status) {
  const value = normalize(status);
  if (value === "blocked_low_disk") {
    return "Что сделать: очистить старые source snapshots или расширить диск, затем повторить обновление источников.";
  }
  if (value === "needs_configuration") {
    return "Что сделать: открыть интеграции, проверить read-only доступы WB/1С и повторить проверку.";
  }
  if (value === "needs_review") {
    return "Что сделать: посмотреть коллекции ниже, исправить источник или принять ограничение периода.";
  }
  if (value.includes("fail") || value.includes("error")) {
    return "Что сделать: проверить обязательный источник и повторить refresh после исправления.";
  }
  if (value === "report_created") {
    return "Новый отчет готов. Старый опубликованный отчет не менялся до успешной сборки.";
  }
  if (value === "dry_run_ready") {
    return "Следующий шаг: запустить полное обновление. Старый опубликованный отчет останется текущим до успешной сборки.";
  }
  if (["queued", "running", "source_loaded", "rebuilding"].includes(value)) {
    return "Можно не держать окно открытым: статус обновится автоматически, старый отчет останется текущим до успешной сборки.";
  }
  return "Если данные выглядят актуальными, можно вернуться к проверке строк отчета.";
}

function appendTableCells(row, cells) {
  cells.forEach((cell) => {
    const node = document.createElement("td");
    node.className = String(cell.className || "").trim();
    if (cell.title) {
      node.title = cell.title;
    }
    if (cell.badge) {
      const badge = document.createElement("span");
      badge.className = `table-badge ${cell.tone || "neutral"}`.trim();
      badge.textContent = String(cell.value || "-");
      node.append(badge);
    } else {
      node.textContent = String(cell.value || "-");
    }
    row.append(node);
  });
}

function tableRowClass(item) {
  const statusText = normalize(item.status);
  const quality = qualityText(item);
  const classes = [];
  if (Number(item.profit || 0) < 0) {
    classes.push("is-loss");
  }
  if (Number(item.returns || 0) > 0) {
    classes.push("has-returns");
  }
  if (statusText && !["ok", "ок"].includes(statusText)) {
    classes.push("is-review");
  }
  if (quality.includes("себестоим") || quality.includes("missing_cost")) {
    classes.push("is-missing-cost");
  }
  if (quality.includes("mapping") || quality.includes("мапп")) {
    classes.push("is-missing-mapping");
  }
  if (quality.includes("partial") || quality.includes("неполн")) {
    classes.push("is-partial-source");
  }
  return classes.join(" ");
}

function onecReconciliationRowClass(item) {
  const classes = [];
  const hasDelta = [
    item.quantityDelta,
    item.amountDelta,
    item.settlementDelta,
    item.salesQuantityDelta,
    item.returnQuantityDelta,
    item.netQuantityDelta,
  ].some((value) => Math.abs(Number(value || 0)) > 0.0001);
  const statusText = normalize(item.status);
  const documentText = normalize(item.onecDocuments);
  if (hasDelta) {
    classes.push("has-delta");
  }
  if (statusText && !["ok", "ок"].includes(statusText)) {
    classes.push("is-review");
  }
  if (!documentText || documentText === "-" || documentText.includes("нет")) {
    classes.push("is-missing-onec");
  }
  return classes.join(" ");
}

function statusTone(status, context = "") {
  const statusValue = normalize(status);
  const value = normalize([status, context].filter(Boolean).join(" "));
  if (!statusValue && !value) {
    return "neutral";
  }
  if (["ok", "ок", "готов", "загружен"].includes(statusValue)) {
    return "status-ok";
  }
  if (
    value.includes("нет себестоим") ||
    value.includes("missing_cost") ||
    value.includes("ошиб") ||
    value.includes("error") ||
    value.includes("excluded")
  ) {
    return "status-blocked";
  }
  if (
    value.includes("провер") ||
    value.includes("эврист") ||
    value.includes("mapping") ||
    value.includes("мапп") ||
    value.includes("ambiguous") ||
    value.includes("partial") ||
    value.includes("неполн") ||
    value.includes("источник")
  ) {
    return "status-warning";
  }
  return "neutral";
}

function statusLabel(status) {
  const value = normalize(status);
  if (!value) {
    return "-";
  }
  if (value.includes("эврист")) {
    return "Проверить тип документа WB";
  }
  return status || "-";
}

function statusExplanation(status, reason = "") {
  const value = normalize([status, reason].filter(Boolean).join(" "));
  if (value.includes("эврист")) {
    return "WB не подтвердил тип документа через sales-reports/list; расчет определил его резервным правилом по отчету. Для отправки клиенту лучше сверить отчет WB с документом 1С.";
  }
  return reason || status || "";
}

function reconciliationStatusTone(status) {
  const value = normalize(status);
  if (["ok", "ок"].includes(value)) {
    return "status-ok";
  }
  return statusTone(status);
}

function liquidityTone(status, profit) {
  const value = normalize(status);
  if (Number(profit || 0) < 0 || value.includes("убыт")) {
    return "status-blocked";
  }
  if (value.includes("провер") || value.includes("медлен") || value.includes("риск")) {
    return "status-warning";
  }
  if (value.includes("ок") || value.includes("здоров") || Number(profit || 0) > 0) {
    return "status-ok";
  }
  return "neutral";
}

function valueTone(value, options = {}) {
  if (value === null || value === undefined || value === "") {
    return "muted";
  }
  const numericValue = Number(value || 0);
  if (numericValue < 0) {
    return "negative";
  }
  if (numericValue > 0) {
    return "positive";
  }
  return options.zero || "muted";
}

function renderReportRowsTable(target, rows) {
  if (!rows.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 17;
    cell.textContent = "Строки не найдены. Переключите вкладку или измените фильтры периода/кабинета.";
    row.append(cell);
    target.replaceChildren(row);
    return;
  }
  target.replaceChildren(...rows.map(reportRowNode));
}

function reportRowNode(item) {
  const row = document.createElement("tr");
  row.className = tableRowClass(item);
  appendTableCells(row, [
    { value: item.month || "-", className: "text-nowrap" },
    { value: item.documentReport || "-", className: "text-wide" },
    { value: item.wbReportId || "-", className: "text-code" },
    { value: item.wbReportDate || "-", className: "text-nowrap" },
    { value: item.cabinet || "-", className: "text-wide" },
    { value: item.product || "-", className: "text-wide text-strong" },
    { value: item.articleWb || "-", className: "text-code" },
    { value: item.article1c || "-", className: "text-code" },
    { value: item.barcode || "-", className: "text-code" },
    { value: item.scheme || "-", badge: true, tone: "neutral" },
    {
      value: statusLabel(item.status),
      badge: true,
      tone: statusTone(item.status, item.statusReason || item.lossDriver),
      title: statusExplanation(item.status, item.statusReason),
    },
    { value: number(item.sales || 0), className: "numeric" },
    {
      value: number(item.returns || 0),
      className: `numeric ${Number(item.returns || 0) > 0 ? "warning" : ""}`.trim(),
    },
    { value: money(item.revenue || 0), className: "numeric" },
    {
      value: signedMoney(item.profit || 0),
      className: `numeric ${valueTone(item.profit)}`,
    },
    {
      value:
        item.margin || item.margin === 0
          ? `${Math.round(Number(item.margin || 0) * 1000) / 10}%`
          : "-",
      className: `numeric ${valueTone(item.margin)}`,
    },
    {
      value:
        item.unitProfit || item.unitProfit === 0
          ? signedMoney(item.unitProfit)
          : "-",
      className: `numeric ${valueTone(item.unitProfit)}`,
    },
  ]);
  return row;
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
      row.className = Number(item.lostProfit || 0) > 0 ? "is-opportunity" : "";
      appendTableCells(row, [
        { value: item.cabinet || "-", className: "text-wide" },
        { value: item.product || "-", className: "text-wide text-strong" },
        { value: item.article1c || "-", className: "text-code" },
        { value: item.barcode || "-", className: "text-code" },
        { value: number(item.zeroStockDays || 0), className: "numeric warning" },
        { value: number(item.onecStock || 0), className: "numeric" },
        { value: item.onecWarehouses || "-", className: "text-wide" },
        { value: number(item.lostUnits || 0), className: "numeric warning" },
        { value: money(item.lostProfit || 0), className: "numeric warning" },
        { value: item.note || "-", badge: true, tone: "warning" },
      ]);
      return row;
    }),
  );
}

function onecReconciliationFilterParams() {
  const params = new URLSearchParams();
  params.set("limit", "50");
  const values = {
    query: els.onecFilterQuery.value.trim(),
    status: els.onecFilterStatus.value,
    period_start: els.onecFilterPeriodStart.value,
    period_end: els.onecFilterPeriodEnd.value,
    wb_cabinet_id: els.onecFilterCabinet.value,
    client_company_id: els.onecFilterOrganization.value,
    document_type: els.onecFilterDocumentType.value,
    delta_only: els.onecFilterDeltaOnly.checked ? "true" : "",
  };
  Object.entries(values).forEach(([key, value]) => {
    if (value) {
      params.set(key, value);
    }
  });
  return params.toString();
}

function hasActiveOnecReconciliationFilters() {
  return Boolean(
    els.onecFilterQuery.value.trim() ||
      els.onecFilterStatus.value ||
      els.onecFilterPeriodStart.value ||
      els.onecFilterPeriodEnd.value ||
      els.onecFilterCabinet.value ||
      els.onecFilterOrganization.value ||
      els.onecFilterDocumentType.value ||
      els.onecFilterDeltaOnly.checked,
  );
}

function rowsFilterParams(preset = state.rowPreset) {
  const params = new URLSearchParams();
  params.set("limit", "50");
  const values = {
    query: els.filterQuery.value.trim(),
    status_filter: els.filterStatus.value,
    period_start: els.filterPeriodStart.value,
    period_end: els.filterPeriodEnd.value,
    month: els.filterMonth.value,
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
  state.clientLoadToken += 1;
  if (!options.keepClient) {
    state.clientId = null;
  }
  state.reports = [];
  state.reportId = null;
  state.summary = null;
  state.freshness = null;
  state.integrationProviders = [];
  state.integrationItems = [];
  state.editingIntegrationKey = "";
  state.latestSourceRefresh = null;
  state.latestOzonDiagnostics = null;
  state.ozonDiagnosticsParams = "";
  state.aiThreadId = null;
  state.onecReconciliationLoaded = false;
  state.rowPreset = "";
  els.topbarCabinetSelect.replaceChildren();
  els.topbarPeriodStart.value = "";
  els.topbarPeriodEnd.value = "";
  els.rowsFilterForm.reset();
  els.onecReconciliationFilterForm.reset();
  syncRowsPresetButtons();
  resetAiPanel();
  resetSourceRefreshPanel({ hide: true });
  els.integrationsPanel.hidden = true;
  syncIntegrationsEntryPoint();
  els.draftPanel.hidden = true;
  renderMetrics(els.kpiGrid, []);
  renderMetrics(els.qualityGrid, []);
  renderReviewRows([], 0);
  renderAnalytics({});
  renderLostSales([]);
  renderLiquidity([]);
  renderOzonPreview(null, null);
}

function syncIntegrationsEntryPoint() {
  els.integrationsOpenButton.hidden = !(state.clientId && isStaffUser());
}

function setEmptyCabinet(title = "Нет доступных отчетов", subtitle = "После импорта отчета здесь появится расчетная витрина.") {
  els.reportTitle.textContent = title;
  els.reportSubtitle.textContent = subtitle;
  renderMetrics(els.kpiGrid, []);
  renderMetrics(els.qualityGrid, []);
  renderAnalytics({});
  renderOzonPreview(state.latestSourceRefresh, state.latestOzonDiagnostics);
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

function canCreateClient() {
  return (state.user?.tenants || []).some((tenant) =>
    ["admin", "consultant"].includes(tenant.role),
  ) || state.clients.some((client) =>
    ["admin", "consultant"].includes(client.role),
  );
}

function selectedClient() {
  return state.clients.find((client) => (client.clientId || client.id) === state.clientId);
}

function activeClientCabinets() {
  return asArray(selectedClient()?.cabinets).filter(
    (item) => item.status !== "disabled" && isWbClientCabinet(item),
  );
}

function activeMarketplaceCabinets() {
  return asArray(selectedClient()?.cabinets).filter(
    (item) => item.status !== "disabled" && isMarketplaceCabinet(item),
  );
}

function isWbClientCabinet(cabinet) {
  return cabinetProviderBase(cabinet) === "wb_api" && !isOzonCabinetLabel(cabinet);
}

function isMarketplaceCabinet(cabinet) {
  return ["wb_api", "ozon_api"].includes(cabinetProviderBase(cabinet));
}

function isOzonMarketplaceCabinet(cabinet) {
  return cabinetProviderBase(cabinet) === "ozon_api" || isOzonCabinetLabel(cabinet);
}

function selectedMarketplaceCabinet() {
  const cabinetId = selectedMarketplaceCabinetId();
  if (!cabinetId) {
    return null;
  }
  return activeMarketplaceCabinets().find((item) => item.id === cabinetId) || null;
}

function selectedMarketplaceCabinetId() {
  return els.topbarCabinetSelect?.value || els.filterCabinet?.value || "";
}

function shouldShowOzonPreview(diagnostics = state.latestOzonDiagnostics) {
  if (!isStaffUser() || !state.clientId) {
    return false;
  }
  const selectedCabinetId = selectedMarketplaceCabinetId();
  const selectedCabinet = selectedMarketplaceCabinet();
  if (selectedCabinetId) {
    return selectedCabinet
      ? isOzonMarketplaceCabinet(selectedCabinet)
      : hasOzonMarketplaceContext(diagnostics);
  }
  return hasOzonMarketplaceContext(diagnostics);
}

function hasOzonMarketplaceContext(diagnostics = state.latestOzonDiagnostics) {
  if (activeMarketplaceCabinets().some(isOzonMarketplaceCabinet)) {
    return true;
  }
  return Boolean(diagnostics?.latestRun || normalize(diagnostics?.status) === "ready");
}

function cabinetProviderBase(cabinet) {
  return String(cabinet?.provider || "wb_api").split(":")[0] || "wb_api";
}

function isOzonCabinetLabel(cabinet) {
  const label = normalize(cabinet?.label || cabinet?.displayName || "");
  return label === "ozon" || label.startsWith("ozon ") || label.includes("ozon seller");
}

function activeClientCompanies() {
  return asArray(selectedClient()?.companies).filter((item) => item.status !== "disabled");
}

function clientScopedFilterOptions() {
  return {
    cabinets: activeMarketplaceCabinets().map((item) => ({
      id: item.id,
      label: marketplaceCabinetLabel(item),
    })),
    organizations: activeClientCompanies().map((item) => ({
      id: item.id,
      label: item.label || item.id,
    })),
  };
}

function marketplaceCabinetLabel(item) {
  const label = item.label || item.id;
  if (isOzonMarketplaceCabinet(item)) {
    return normalize(label).includes("ozon") ? label : `Ozon: ${label}`;
  }
  return normalize(label).startsWith("wb") ? label : `WB: ${label}`;
}

function mergedCabinetOptions(primary = [], fallback = []) {
  const byId = new Map();
  [...asArray(fallback), ...asArray(primary)].forEach((item) => {
    const id = optionValue(item);
    if (id && !byId.has(id)) {
      byId.set(id, item);
    }
  });
  return [...byId.values()];
}

async function api(url, options = {}) {
  const isFormData = options.body instanceof FormData;
  const headers = isFormData
    ? { ...(options.headers || {}) }
    : {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      };
  const response = await fetch(url, {
    credentials: "same-origin",
    headers,
    ...options,
  });
  if (!response.ok) {
    const detail = await readApiErrorDetail(response);
    const error = new Error(detail || `HTTP ${response.status}`);
    error.status = response.status;
    error.detail = detail;
    throw error;
  }
  return response.json();
}

async function readApiErrorDetail(response) {
  try {
    const payload = await response.json();
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
    if (Array.isArray(payload.detail)) {
      return payload.detail
        .map((item) => item?.msg || item?.type || "")
        .filter(Boolean)
        .join("; ");
    }
  } catch (error) {
    return "";
  }
  return "";
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

function formatShortDateTime(value) {
  return formatDateTime(value).replace(/(\d{2}\.\d{2})\.\d{4}/, "$1");
}
