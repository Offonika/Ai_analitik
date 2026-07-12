const state = {
  user: null,
  clients: [],
  clientId: null,
  reports: [],
  reportId: null,
  clientLoadToken: 0,
  rowsRequestKey: "",
  drilldownRequestKey: "",
  drilldownPreset: "review",
  buyoutReconciliationRequestKey: "",
  cogsReconciliationRequestKey: "",
  marketplaceExpenseReconciliationRequestKey: "",
  onecReconciliationRequestKey: "",
  mappingItemsRequestKey: "",
  activeWidgetOverlay: null,
  widgetReturnFocus: null,
  summary: null,
  freshness: null,
  integrationProviders: [],
  integrationItems: [],
  integrationNotices: {},
  editingIntegrationKey: "",
  integrationProviderFilter: "",
  draftIntegration: null,
  latestSourceRefresh: null,
  latestSourceRefreshAttempt: null,
  activeSourceRefresh: null,
  latestOzonDiagnostics: null,
  ozonDiagnosticsParams: "",
  ozonUnitStatusFilter: "",
  mappingItems: [],
  mappingSelectedItemId: "",
  mappingCandidates: [],
  mappingHistory: [],
  sourceRefreshPollTimer: 0,
  aiThreadId: null,
  aiBusy: false,
  onecReconciliationLoaded: false,
  rowPreset: "",
  taxInputPage: 0,
  taxInputCabinet: "",
};

const FOCUSABLE_WIDGET_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

const EXCEL_REBUILD_SOURCE_REFRESH_STATUSES = new Set([
  "needs_review",
  "source_loaded",
  "report_created",
  "ok",
  "loaded",
  "success",
  "ready",
  "completed",
]);

const els = {
  loginView: document.querySelector("#login-view"),
  cabinetView: document.querySelector("#cabinet-view"),
  brandLockup: document.querySelector(".brand-lockup"),
  loginForm: document.querySelector("#login-form"),
  loginError: document.querySelector("#login-error"),
  reportTitle: document.querySelector("#report-title"),
  reportSubtitle: document.querySelector("#report-subtitle"),
  reportLoadRetryButton: document.querySelector("#report-load-retry-button"),
  clientSelect: document.querySelector("#client-select"),
  topbarCabinetSelect: document.querySelector("#topbar-cabinet-select"),
  topbarPeriodStart: document.querySelector("#topbar-period-start"),
  topbarPeriodEnd: document.querySelector("#topbar-period-end"),
  logoutButton: document.querySelector("#logout-button"),
  clientOutputButton: document.querySelector("#client-output-button"),
  reportBuildButton: document.querySelector("#report-build-button"),
  reportWizardOverlay: document.querySelector("#report-wizard-overlay"),
  reportWizardClose: document.querySelector("#report-wizard-close"),
  reportWizardForm: document.querySelector("#report-wizard-form"),
  reportWizardClient: document.querySelector("#report-wizard-client"),
  reportWizardScope: document.querySelector("#report-wizard-scope"),
  reportWizardMode: document.querySelector("#report-wizard-mode"),
  reportWizardModeHint: document.querySelector("#report-wizard-mode-hint"),
  reportWizardPeriodMode: document.querySelector("#report-wizard-period-mode"),
  reportWizardPeriodFields: document.querySelector("#report-wizard-period-fields"),
  reportWizardPeriodStart: document.querySelector("#report-wizard-period-start"),
  reportWizardPeriodEnd: document.querySelector("#report-wizard-period-end"),
  reportWizardDryRun: document.querySelector("#report-wizard-dry-run"),
  reportWizardStatus: document.querySelector("#report-wizard-status"),
  reportWizardDownload: document.querySelector("#report-wizard-download"),
  reportWizardSubmit: document.querySelector("#report-wizard-submit"),
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
  mappingWidgetOverlay: document.querySelector("#mapping-widget-overlay"),
  mappingWidgetClose: document.querySelector("#mapping-widget-close"),
  drilldownWidgetOverlay: document.querySelector("#drilldown-widget-overlay"),
  drilldownWidgetClose: document.querySelector("#drilldown-widget-close"),
  drilldownTitle: document.querySelector("#drilldown-title"),
  drilldownSubtitle: document.querySelector("#drilldown-subtitle"),
  drilldownCount: document.querySelector("#drilldown-count"),
  drilldownTabs: document.querySelectorAll("[data-drilldown-preset]"),
  drilldownSources: document.querySelector("#drilldown-sources"),
  drilldownGuidance: document.querySelector("#drilldown-guidance"),
  drilldownTableWrap: document.querySelector("#drilldown-table-wrap"),
  drilldownRowsHead: document.querySelector("#drilldown-rows-head"),
  drilldownRows: document.querySelector("#drilldown-rows"),
  buyoutReconciliationOverlay: document.querySelector(
    "#buyout-reconciliation-overlay",
  ),
  buyoutReconciliationClose: document.querySelector(
    "#buyout-reconciliation-close",
  ),
  buyoutReconciliationCount: document.querySelector(
    "#buyout-reconciliation-count",
  ),
  buyoutReconciliationGrid: document.querySelector(
    "#buyout-reconciliation-grid",
  ),
  buyoutReconciliationStatus: document.querySelector(
    "#buyout-reconciliation-status",
  ),
  buyoutReconciliationRows: document.querySelector(
    "#buyout-reconciliation-rows",
  ),
  cogsReconciliationOverlay: document.querySelector(
    "#cogs-reconciliation-overlay",
  ),
  cogsReconciliationClose: document.querySelector(
    "#cogs-reconciliation-close",
  ),
  cogsReconciliationCount: document.querySelector(
    "#cogs-reconciliation-count",
  ),
  cogsReconciliationGrid: document.querySelector(
    "#cogs-reconciliation-grid",
  ),
  cogsReconciliationStatus: document.querySelector(
    "#cogs-reconciliation-status",
  ),
  cogsReconciliationRows: document.querySelector(
    "#cogs-reconciliation-rows",
  ),
  cogsCostIssueRows: document.querySelector("#cogs-cost-issue-rows"),
  marketplaceExpenseReconciliationOverlay: document.querySelector(
    "#marketplace-expense-reconciliation-overlay",
  ),
  marketplaceExpenseReconciliationClose: document.querySelector(
    "#marketplace-expense-reconciliation-close",
  ),
  marketplaceExpenseReconciliationCount: document.querySelector(
    "#marketplace-expense-reconciliation-count",
  ),
  marketplaceExpenseReconciliationGrid: document.querySelector(
    "#marketplace-expense-reconciliation-grid",
  ),
  marketplaceExpenseReconciliationStatus: document.querySelector(
    "#marketplace-expense-reconciliation-status",
  ),
  marketplaceExpenseReconciliationGroups: document.querySelector(
    "#marketplace-expense-reconciliation-groups",
  ),
  marketplaceExpenseReconciliationRows: document.querySelector(
    "#marketplace-expense-reconciliation-rows",
  ),
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
  onecKpiSection: document.querySelector("#onec-kpi-section"),
  onecKpiGrid: document.querySelector("#onec-kpi-grid"),
  actionInsightsList: document.querySelector("#action-insights-list"),
  dataTrustStrip: document.querySelector("#data-trust-strip"),
  dataTrustBadge: document.querySelector("#data-trust-badge"),
  dataTrustGrid: document.querySelector("#data-trust-grid"),
  moneyTrendTitle: document.querySelector("#money-trend-title"),
  moneyTrendCopy: document.querySelector("#money-trend-title")?.nextElementSibling,
  moneyTrendChart: document.querySelector("#money-trend-chart"),
  unitPlTitle: document.querySelector("#unit-pl-title"),
  unitPlCopy: document.querySelector("#unit-pl-title")?.nextElementSibling,
  unitPlTable: document.querySelector("#unit-pl-table"),
  lossDriversTitle: document.querySelector("#loss-drivers-title"),
  lossDriversCopy: document.querySelector("#loss-drivers-title")?.nextElementSibling,
  lossDriversChart: document.querySelector("#loss-drivers-chart"),
  lostMarginChart: document.querySelector("#lost-margin-chart"),
  returnsChartTitle: document.querySelector("#returns-chart-title"),
  returnsChartCopy: document.querySelector("#returns-chart-title")?.nextElementSibling,
  returnsChart: document.querySelector("#returns-chart"),
  taxInputTitle: document.querySelector("#tax-input-title"),
  taxInputCopy: document.querySelector("#tax-input-title")?.nextElementSibling,
  taxInputChart: document.querySelector("#tax-input-chart"),
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
  mappingServicePanel: document.querySelector("#mapping-service-panel"),
  mappingServiceTitle: document.querySelector("#mapping-service-title"),
  mappingServiceStatus: document.querySelector("#mapping-service-status"),
  mappingRebuildButton: document.querySelector("#mapping-rebuild-button"),
  mappingExportButton: document.querySelector("#mapping-export-button"),
  mappingFilterForm: document.querySelector("#mapping-filter-form"),
  mappingMarketplaceFilter: document.querySelector("#mapping-marketplace-filter"),
  mappingStatusFilter: document.querySelector("#mapping-status-filter"),
  mappingSearch: document.querySelector("#mapping-search"),
  mappingItemRows: document.querySelector("#mapping-item-rows"),
  mappingSelectedCard: document.querySelector("#mapping-selected-card"),
  mappingOnecSearch: document.querySelector("#mapping-onec-search"),
  mappingOnecResults: document.querySelector("#mapping-onec-results"),
  mappingCandidateList: document.querySelector("#mapping-candidate-list"),
  mappingHistoryList: document.querySelector("#mapping-history-list"),
  reviewRowsButton: document.querySelector("#review-rows-button"),
  detailTabs: document.querySelectorAll("[data-detail-tab]"),
  detailPanels: document.querySelectorAll("[data-detail-panel]"),
  onecReconciliationCount: document.querySelector("#onec-reconciliation-count"),
  onecReconciliationTechnicalCount: document.querySelector(
    "#onec-reconciliation-technical-count",
  ),
  onecReconciliationGrid: document.querySelector("#onec-reconciliation-grid"),
  onecReconciliationRows: document.querySelector("#onec-reconciliation-rows"),
  financialReconciliationGrid: document.querySelector(
    "#financial-reconciliation-grid",
  ),
  financialReconciliationSource: document.querySelector(
    "#financial-reconciliation-source",
  ),
  financialReconciliationRows: document.querySelector(
    "#financial-reconciliation-rows",
  ),
  onecReconciliationFilterForm: document.querySelector(
    "#onec-reconciliation-filter-form",
  ),
  onecResetFiltersButton: document.querySelector("#onec-reset-filters-button"),
  onecFilterQuery: document.querySelector("#onec-filter-query"),
  onecFilterStatus: document.querySelector("#onec-filter-status"),
  onecFilterControlType: document.querySelector("#onec-filter-control-type"),
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
  { id: "ambiguous_mapping", label: "Несколько вариантов 1С" },
  { id: "missing_cost", label: "Нет себестоимости" },
  { id: "missing_1c_organization", label: "Не выбрана организация 1С" },
  { id: "missing_1c_commissioner", label: "Нет выручки 1C" },
  { id: "buyout_period_only", label: "Выкуп по периоду" },
];

const MAPPING_REVIEW_STATUSES = ["needs_review", "ambiguous", "missing"];

const ROW_PRESET_LABELS = {
  wb: {
    "": "Все",
    losses: "Убыточные продажи",
    penaltyOnly: "Штрафы без продаж",
    missingCost: "Без себестоимости",
    missingMapping: "Сопоставление",
    returns: "Возвраты",
    review: "К проверке",
  },
  ozon: {
    "": "Все",
    losses: "Убыточные",
    missingCost: "Без себестоимости",
    missingMapping: "Без связи",
    returns: "Выкупы",
    review: "К проверке",
  },
};

const FILTER_STATE_STORAGE_KEY = "wb-unit-economics:cabinet-filters:v1";

document.addEventListener("DOMContentLoaded", init);

function init() {
  configurePageMode();
  els.loginForm.addEventListener("submit", onLogin);
  els.logoutButton.addEventListener("click", onLogout);
  els.clientSelect.addEventListener("change", () => selectClient(els.clientSelect.value));
  els.reportLoadRetryButton.addEventListener("click", retryCurrentReportLoad);
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
  els.reportBuildButton.addEventListener("click", onReportBuildButtonClick);
  els.reportWizardClose.addEventListener("click", closeReportWizard);
  els.reportWizardOverlay.addEventListener("click", (event) => {
    if (event.target === els.reportWizardOverlay) {
      closeReportWizard();
    }
  });
  els.reportWizardMode.addEventListener("change", renderReportWizardSettings);
  els.reportWizardPeriodMode.addEventListener(
    "change",
    renderReportWizardSettings,
  );
  els.reportWizardDryRun.addEventListener("change", renderReportWizardSettings);
  els.reportWizardForm.addEventListener("submit", onReportWizardSubmit);
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
  els.mappingFilterForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    loadMappingItems(currentClientLoadContext());
  });
  els.mappingMarketplaceFilter?.addEventListener("change", () =>
    loadMappingItems(currentClientLoadContext()),
  );
  els.mappingStatusFilter?.addEventListener("change", () =>
    loadMappingItems(currentClientLoadContext()),
  );
  els.mappingSearch?.addEventListener(
    "input",
    debounce(() => loadMappingItems(currentClientLoadContext()), 300),
  );
  els.mappingRebuildButton?.addEventListener("click", () =>
    rebuildMappingCandidates(currentClientLoadContext()),
  );
  els.mappingExportButton?.addEventListener("click", () =>
    exportMappingRows(currentClientLoadContext()),
  );
  els.mappingOnecSearch?.addEventListener(
    "input",
    debounce(() => searchMappingOnec(currentClientLoadContext()), 300),
  );
  els.mappingItemRows?.addEventListener("click", (event) => {
    const row = event.target.closest("[data-mapping-item-id]");
    if (row) {
      selectMappingItem(row.dataset.mappingItemId || "", currentClientLoadContext());
    }
  });
  els.mappingCandidateList?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-mapping-action]");
    if (button) {
      handleMappingCandidateAction(button, currentClientLoadContext());
    }
  });
  els.mappingOnecResults?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-onec-mapping-id]");
    if (button) {
      acceptManualOnecMapping(
        button.dataset.onecMappingId || "",
        currentClientLoadContext(),
      );
    }
  });
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
  els.mappingWidgetClose.addEventListener("click", closeMappingWidget);
  els.mappingWidgetOverlay.addEventListener("click", (event) => {
    if (event.target === els.mappingWidgetOverlay) {
      closeMappingWidget();
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
  els.buyoutReconciliationClose.addEventListener(
    "click",
    closeBuyoutReconciliationWidget,
  );
  els.buyoutReconciliationOverlay.addEventListener("click", (event) => {
    if (event.target === els.buyoutReconciliationOverlay) {
      closeBuyoutReconciliationWidget();
    }
  });
  els.cogsReconciliationClose.addEventListener(
    "click",
    closeCogsReconciliationWidget,
  );
  els.cogsReconciliationOverlay.addEventListener("click", (event) => {
    if (event.target === els.cogsReconciliationOverlay) {
      closeCogsReconciliationWidget();
    }
  });
  els.marketplaceExpenseReconciliationClose.addEventListener(
    "click",
    closeMarketplaceExpenseReconciliationWidget,
  );
  els.marketplaceExpenseReconciliationOverlay.addEventListener("click", (event) => {
    if (event.target === els.marketplaceExpenseReconciliationOverlay) {
      closeMarketplaceExpenseReconciliationWidget();
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
      return;
    }
    if (event.key === "Tab") {
      trapWidgetFocus(event);
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
  const labels = shouldUseOzonWorkingView()
    ? ROW_PRESET_LABELS.ozon
    : ROW_PRESET_LABELS.wb;
  els.rowsPresetButtons.forEach((button) => {
    const preset = button.dataset.rowPreset || "";
    button.hidden = shouldUseOzonWorkingView() && preset === "penaltyOnly";
    const selected = preset === state.rowPreset;
    button.textContent = labels[preset] || ROW_PRESET_LABELS.wb[preset] || "Фильтр";
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", selected ? "true" : "false");
  });
}

function bindOnecReconciliationFilters() {
  [
    els.onecFilterStatus,
    els.onecFilterControlType,
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
    if (!els.onecFilterPeriodStart.value && els.topbarPeriodStart.value) {
      els.onecFilterPeriodStart.value = els.topbarPeriodStart.value;
    }
    if (!els.onecFilterPeriodEnd.value && els.topbarPeriodEnd.value) {
      els.onecFilterPeriodEnd.value = els.topbarPeriodEnd.value;
    }
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
      error?.status === 401
        ? ""
        : "Не удалось проверить сессию. Обновите страницу или войдите заново.";
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
  const kpiPanel = document.querySelector("#kpi-grid")?.closest(".money-strip");
  if (!kpiPanel || !els.ozonDiagnosticsPanel) {
    return;
  }
  if (kpiPanel.nextElementSibling !== els.ozonDiagnosticsPanel) {
    kpiPanel.after(els.ozonDiagnosticsPanel);
  }
}

function renderAiPageHeader(title = "AI-аналитик отчета", subtitle = "") {
  setTopbarNotice(
    title,
    subtitle || "Вопросы по уже рассчитанным фактам WB и 1C.",
  );
}

function setTopbarNotice(title, subtitle = "", tone = "") {
  const resolvedTone = tone || topbarNoticeToneFromText(title);
  els.reportTitle.textContent = title;
  els.reportSubtitle.textContent = subtitle;
  els.brandLockup.classList.remove("is-info", "is-ok", "is-warning", "is-blocked");
  els.brandLockup.classList.add(resolvedTone);
}

function topbarNoticeToneFromText(title = "") {
  const value = normalize(title);
  if (
    value.includes("ошиб") ||
    value.includes("нельзя") ||
    value.includes("не удалось") ||
    value.includes("заблок")
  ) {
    return "is-blocked";
  }
  if (value.includes("готов")) {
    return "is-ok";
  }
  if (
    value.includes("нет доступ") ||
    value.includes("нужна провер") ||
    value.includes("не найден")
  ) {
    return "is-warning";
  }
  return "is-info";
}

function reportTopbarTone(readiness = {}, refresh = null) {
  const readinessStatus = normalize(readiness.status);
  const refreshTone = refresh?.status ? sourceStatusTone(refresh.status) : "";
  if (
    ["failed", "blocked"].includes(readinessStatus) ||
    refreshTone === "is-blocked"
  ) {
    return "is-blocked";
  }
  if (readinessStatus === "ready" && refreshTone !== "is-warning") {
    return "is-ok";
  }
  if (readinessStatus || refreshTone === "is-warning") {
    return "is-warning";
  }
  return "is-info";
}

function openAiWidget(options = {}) {
  openWidgetOverlay(els.aiWidgetOverlay);
  if (!state.reportId) {
    els.aiError.textContent = "Сначала выберите клиента и отчет.";
    return;
  }
  els.aiError.textContent = "";
  if (options.focus !== false) {
    window.setTimeout(() => els.aiInput.focus(), 0);
  }
}

function closeAiWidget(options = {}) {
  closeWidgetOverlay(els.aiWidgetOverlay, options);
  if (isAiPage()) {
    window.history.replaceState({}, "", "/cabinet");
    document.body.classList.remove("ai-page");
  }
}

function openClientOutputWidget() {
  openWidgetOverlay(els.clientOutputWidgetOverlay);
  els.draftPanel.hidden = false;
  if (!state.reportId) {
    els.draftStatus.textContent = "Сначала выберите клиента и отчет.";
    return;
  }
  if (!els.draftStatus.textContent) {
    els.draftStatus.textContent = "Отчёт для клиента ещё не подготовлен.";
  }
  window.setTimeout(() => els.draftRefreshButton.focus(), 0);
}

function closeClientOutputWidget(options = {}) {
  closeWidgetOverlay(els.clientOutputWidgetOverlay, options);
}

function onReportBuildButtonClick() {
  if (!state.clientId) {
    return;
  }
  if (!isStaffUser()) {
    if (state.reportId) {
      window.location.assign(
        `/api/reports/${encodeURIComponent(state.reportId)}/export.xlsx`,
      );
    }
    return;
  }
  openReportWizard();
}

function openReportWizard() {
  if (!state.clientId || !isStaffUser()) {
    return;
  }
  const client = selectedClient();
  const selectedCabinet = selectedMarketplaceCabinet();
  els.reportWizardClient.textContent =
    client?.name || client?.clientId || client?.id || "Клиент не выбран";
  els.reportWizardMode.value =
    selectedCabinet && isOzonMarketplaceCabinet(selectedCabinet)
      ? "ozon-only"
      : "full";
  const hasSelectedPeriod = Boolean(
    els.topbarPeriodStart.value || els.topbarPeriodEnd.value,
  );
  els.reportWizardPeriodMode.value = hasSelectedPeriod ? "custom" : "default";
  els.reportWizardPeriodStart.value = els.topbarPeriodStart.value || "";
  els.reportWizardPeriodEnd.value = els.topbarPeriodEnd.value || "";
  els.reportWizardDryRun.checked = false;
  renderReportWizardSettings();
  renderReportWizardStatus(state.latestSourceRefresh);
  openWidgetOverlay(els.reportWizardOverlay);
  window.setTimeout(() => els.reportWizardMode.focus(), 0);
}

function closeReportWizard(options = {}) {
  closeWidgetOverlay(els.reportWizardOverlay, options);
}

function fillReportWizardPeriodFromTopbar() {
  if (!els.reportWizardPeriodStart.value && els.topbarPeriodStart.value) {
    els.reportWizardPeriodStart.value = els.topbarPeriodStart.value;
  }
  if (!els.reportWizardPeriodEnd.value && els.topbarPeriodEnd.value) {
    els.reportWizardPeriodEnd.value = els.topbarPeriodEnd.value;
  }
}

function renderReportWizardSettings() {
  const mode = els.reportWizardMode.value || "full";
  const customPeriod = els.reportWizardPeriodMode.value === "custom";
  if (customPeriod) {
    fillReportWizardPeriodFromTopbar();
  }
  const dryRun = els.reportWizardDryRun.checked;
  const cabinets = activeMarketplaceCabinets().filter((cabinet) =>
    mode === "ozon-only"
      ? isOzonMarketplaceCabinet(cabinet)
      : !isOzonMarketplaceCabinet(cabinet),
  );
  els.reportWizardScope.textContent = cabinets.length
    ? cabinets.map(marketplaceCabinetLabel).join(", ")
    : mode === "ozon-only"
      ? "Активный кабинет Ozon не найден"
      : "Все активные WB-кабинеты клиента";
  els.reportWizardModeHint.textContent =
    mode === "ozon-only"
      ? "Загрузится служебная витрина Ozon + 1С. Клиентский отчёт и Excel не публикуются."
      : "Система прочитает активные WB и 1С подключения, проверит данные и безопасно опубликует новый отчёт.";
  els.reportWizardPeriodFields.hidden = !customPeriod;
  els.reportWizardPeriodStart.required = customPeriod;
  els.reportWizardPeriodEnd.required = customPeriod;
  els.reportWizardSubmit.textContent = dryRun
    ? "Проверить готовность"
    : mode === "ozon-only"
      ? "Запустить диагностику"
      : "Проверить и сформировать";
  updateReportWizardDownload();
}

function updateReportWizardDownload() {
  const hasReport = Boolean(state.reportId);
  els.reportWizardDownload.hidden = !hasReport;
  els.reportWizardDownload.href = hasReport
    ? `/api/reports/${encodeURIComponent(state.reportId)}/export.xlsx`
    : "#";
}

function renderReportWizardStatus(refresh) {
  if (!els.reportWizardStatus) {
    return;
  }
  const status = normalize(refresh?.status);
  const active = isActiveSourceRefresh(refresh);
  els.reportWizardSubmit.disabled = active;
  const steps = Array.from(
    els.reportWizardOverlay.querySelectorAll(".report-wizard-steps span"),
  );
  const activeStep = active || status === "dry_run_ready" || status === "needs_review"
    ? 1
    : refresh?.newReportRunId || status === "report_created"
      ? 2
      : 0;
  steps.forEach((step, index) => {
    step.classList.toggle("active", index === activeStep);
    step.classList.toggle("done", index < activeStep);
  });
  updateReportWizardDownload();
  if (!refresh) {
    els.reportWizardStatus.className = "report-wizard-status";
    els.reportWizardStatus.textContent =
      "После запуска здесь появятся проверка источников и ход формирования отчёта.";
    return;
  }
  els.reportWizardStatus.className = `report-wizard-status ${sourceStatusTone(refresh.status)}`;
  if (active) {
    els.reportWizardStatus.textContent =
      `${sourceRefreshStartText({ dryRun: Boolean(refresh.dryRun), mode: refresh.mode || "full" })} ` +
      `Период: ${sourcePeriodText(refresh)}.`;
    return;
  }
  if (refresh.newReportRunId || status === "report_created") {
    els.reportWizardStatus.textContent =
      `Новый отчёт готов. Период: ${sourcePeriodText(refresh)}. Он уже открыт в кабинете.`;
    return;
  }
  if (status === "dry_run_ready") {
    els.reportWizardStatus.textContent =
      "Проверка пройдена. Снимите флажок «Только проверить готовность» и запустите формирование отчёта.";
    return;
  }
  els.reportWizardStatus.textContent =
    `${sourceStatusText(refresh.status)}. ${localizedOperationalMessage(
      refresh.safeMessage || sourceStatusHint(refresh.status),
    )}`;
}

async function onReportWizardSubmit(event) {
  event.preventDefault();
  if (!state.clientId || !isStaffUser() || els.reportWizardSubmit.disabled) {
    return;
  }
  const customPeriod = els.reportWizardPeriodMode.value === "custom";
  const periodStart = customPeriod ? els.reportWizardPeriodStart.value : "";
  const periodEnd = customPeriod ? els.reportWizardPeriodEnd.value : "";
  if (customPeriod && (!periodStart || !periodEnd)) {
    els.reportWizardStatus.className = "report-wizard-status is-warning";
    els.reportWizardStatus.textContent = "Укажите дату начала и дату конца периода.";
    return;
  }
  if (periodStart && periodEnd && periodStart > periodEnd) {
    els.reportWizardStatus.className = "report-wizard-status is-warning";
    els.reportWizardStatus.textContent =
      "Дата начала не может быть позже даты конца.";
    return;
  }
  els.reportWizardSubmit.disabled = true;
  const refresh = await runClientSourceRefresh({
    dryRun: els.reportWizardDryRun.checked,
    mode: els.reportWizardMode.value || "full",
    periodStart,
    periodEnd,
    origin: "wizard",
  });
  if (refresh) {
    renderReportWizardStatus(refresh);
  } else {
    els.reportWizardSubmit.disabled = false;
  }
}

function openIntegrationsWidget(options = {}) {
  openWidgetOverlay(els.integrationsWidgetOverlay);
  els.integrationsPanel.hidden = false;
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
      "Получаем подключения выбранного клиента только для чтения.",
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

function rowsRequestKey(reportId, params) {
  return `${reportId || ""}?${params || ""}`;
}

function isCurrentRowsRequest(context, reportId, requestKey) {
  return (
    reportId === state.reportId &&
    requestKey === state.rowsRequestKey &&
    isCurrentClientLoad(context)
  );
}

function onecReconciliationRequestKey(reportId, params) {
  return `${reportId || ""}?${params || ""}`;
}

function isCurrentOnecReconciliationRequest(context, reportId, requestKey) {
  return (
    reportId === state.reportId &&
    requestKey === state.onecReconciliationRequestKey &&
    isCurrentClientLoad(context)
  );
}

function mappingItemsRequestKey(clientId, params) {
  return `${clientId || ""}?${params || ""}`;
}

function isCurrentMappingItemsRequest(context, requestKey) {
  return requestKey === state.mappingItemsRequestKey && isCurrentClientLoad(context);
}

function closeIntegrationsWidget(options = {}) {
  closeWidgetOverlay(els.integrationsWidgetOverlay, options);
  if (isIntegrationsPage()) {
    window.history.replaceState({}, "", "/cabinet");
    document.body.classList.remove("integrations-page");
  }
}

async function openMappingWidget(options = {}) {
  syncSelectedClientFromControl();
  openWidgetOverlay(els.mappingWidgetOverlay);
  els.mappingServicePanel.hidden = false;
  if (!state.clientId) {
    els.mappingServiceStatus.textContent =
      "Выберите клиента, чтобы открыть очередь сопоставления.";
    return false;
  }
  if (!isStaffUser()) {
    els.mappingServiceStatus.textContent =
      "Сервис сопоставления доступен только консультанту или администратору.";
    return false;
  }
  if (options.marketplace !== undefined) {
    els.mappingMarketplaceFilter.value = options.marketplace || "";
  }
  if (options.status !== undefined) {
    els.mappingStatusFilter.value = options.status || "";
  }
  if (options.search !== undefined) {
    els.mappingSearch.value = options.search || "";
  }
  const marketplace = els.mappingMarketplaceFilter.value;
  els.mappingServiceTitle.textContent = marketplace === "wb"
    ? "Сопоставление WB ↔ 1C"
    : marketplace === "ozon"
      ? "Сопоставление Ozon ↔ 1C"
      : "Сопоставление маркетплейсов ↔ 1C";
  const context = currentClientLoadContext();
  await loadMappingItems(context);
  if (!isCurrentClientLoad(context)) {
    return false;
  }
  if (options.focus !== false) {
    window.setTimeout(() => {
      els.mappingMarketplaceFilter.focus();
    }, 0);
  }
  return true;
}

function closeMappingWidget(options = {}) {
  closeWidgetOverlay(els.mappingWidgetOverlay, options);
}

function openNewClientWidget() {
  if (!canCreateClient()) {
    return;
  }
  els.newClientForm.reset();
  els.newClientStatus.textContent = "";
  els.newClientSubmit.disabled = false;
  openWidgetOverlay(els.newClientWidgetOverlay);
  els.newClientName.focus();
}

function closeNewClientWidget(options = {}) {
  closeWidgetOverlay(els.newClientWidgetOverlay, options);
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
  openWidgetOverlay(els.drilldownWidgetOverlay);
  selectDrilldownPreset(preset);
}

function closeDrilldownWidget(options = {}) {
  closeWidgetOverlay(els.drilldownWidgetOverlay, options);
}

function openBuyoutReconciliationWidget() {
  if (!state.reportId) {
    return;
  }
  openWidgetOverlay(els.buyoutReconciliationOverlay);
  loadBuyoutReconciliation();
}

function closeBuyoutReconciliationWidget(options = {}) {
  closeWidgetOverlay(els.buyoutReconciliationOverlay, options);
}

function openCogsReconciliationWidget() {
  if (!state.reportId) {
    return;
  }
  openWidgetOverlay(els.cogsReconciliationOverlay);
  loadCogsReconciliation();
}

function closeCogsReconciliationWidget(options = {}) {
  closeWidgetOverlay(els.cogsReconciliationOverlay, options);
}

function openMarketplaceExpenseReconciliationWidget() {
  if (!state.reportId) {
    return;
  }
  openWidgetOverlay(els.marketplaceExpenseReconciliationOverlay);
  loadMarketplaceExpenseReconciliation();
}

function closeMarketplaceExpenseReconciliationWidget(options = {}) {
  closeWidgetOverlay(els.marketplaceExpenseReconciliationOverlay, options);
}

async function loadMarketplaceExpenseReconciliation() {
  const reportId = state.reportId;
  if (!reportId) {
    return;
  }
  const params = new URLSearchParams({ limit: "1000" });
  const periodStart = els.topbarPeriodStart.value;
  const periodEnd = els.topbarPeriodEnd.value;
  const cabinetId = els.topbarCabinetSelect.value;
  const companyId = els.filterOrganization?.value || "";
  if (periodStart) params.set("period_start", periodStart);
  if (periodEnd) params.set("period_end", periodEnd);
  if (cabinetId) params.set("wb_cabinet_id", cabinetId);
  if (companyId) params.set("client_company_id", companyId);
  const requestKey = `${reportId}:${params.toString()}`;
  state.marketplaceExpenseReconciliationRequestKey = requestKey;
  renderMarketplaceExpenseReconciliationStatus(
    "Собираем расходы WB и документы услуг 1С.",
  );
  try {
    const payload = await api(
      `/api/reports/${encodeURIComponent(reportId)}/marketplace-expense-reconciliation?${params}`,
    );
    if (
      state.reportId !== reportId ||
      state.marketplaceExpenseReconciliationRequestKey !== requestKey
    ) {
      return;
    }
    renderMarketplaceExpenseReconciliation(payload || {});
  } catch (_error) {
    if (
      state.reportId === reportId &&
      state.marketplaceExpenseReconciliationRequestKey === requestKey
    ) {
      renderMarketplaceExpenseReconciliationStatus(
        "Не удалось загрузить сверку расходов. Повторите запрос.",
      );
    }
  }
}

function renderMarketplaceExpenseReconciliationStatus(message) {
  els.marketplaceExpenseReconciliationCount.textContent = "";
  els.marketplaceExpenseReconciliationStatus.textContent = message;
  renderMetrics(els.marketplaceExpenseReconciliationGrid, []);
  replaceTableBodyWithMessage(
    els.marketplaceExpenseReconciliationGroups,
    8,
    message,
  );
  replaceTableBodyWithMessage(
    els.marketplaceExpenseReconciliationRows,
    10,
    message,
  );
}

function marketplaceExpenseStatusLabel(status) {
  return {
    matched: "Сверено",
    mismatch: "Есть расхождения",
    missing_source: "Не проверено: расходы 1С не загружены",
    missing_onec_document: "Нет документа 1С",
    ambiguous_mapping: "Нужна проверка сопоставления",
    ambiguous_cabinet_allocation: "Нужна проверка сопоставления",
    missing_cabinet_mapping: "Нужна проверка сопоставления",
    legacy_rebuild_required: "Нужна пересборка отчёта",
  }[status] || status || "Не проверено";
}

function renderMarketplaceExpenseReconciliation(payload = {}) {
  const kpis = payload.kpis || {};
  const source = payload.source || {};
  const groups = asArray(payload.groups);
  const items = asArray(payload.items);
  const status = kpis.marketplaceExpenseReconciliationStatus || source.status;
  els.marketplaceExpenseReconciliationCount.textContent = `${number(
    items.length,
  )} строк 1С · ${number(groups.length)} групп`;
  renderMetrics(els.marketplaceExpenseReconciliationGrid, [
    [
      "Расходы WB в P&L",
      optionalMoney(kpis.wbMarketplacePnlExpenses),
      "База применённого налогового профиля",
    ],
    [
      "Документные расходы WB",
      optionalMoney(kpis.wbMarketplaceDocumentExpensesWithVat),
      "Сумма статей WB с НДС",
    ],
    [
      "Услуги 1С с НДС",
      optionalMoney(kpis.onecMarketplaceExpensesWithVat),
      kpis.onecMarketplaceExpensesWithVat == null
        ? "Источник не загружен"
        : `Без НДС ${optionalMoney(kpis.onecMarketplaceExpensesWithoutVat)} + НДС ${optionalMoney(kpis.onecMarketplaceVat)}`,
      kpis.onecMarketplaceExpensesWithVat == null ? "warning" : "",
    ],
    [
      "Дельта 1С − WB",
      kpis.marketplaceExpenseDeltaWithVat == null
        ? "Не рассчитано"
        : signedMoney(kpis.marketplaceExpenseDeltaWithVat),
      `${marketplaceExpenseStatusLabel(status)} · проблемных групп ${number(
        kpis.marketplaceExpenseIssueGroups || 0,
      )}`,
      status === "matched" ? "ok" : "warning",
    ],
  ]);
  els.marketplaceExpenseReconciliationStatus.textContent =
    source.message || marketplaceExpenseStatusLabel(status);
  if (groups.length) {
    els.marketplaceExpenseReconciliationGroups.replaceChildren(
      ...groups.map(marketplaceExpenseGroupRowNode),
    );
  } else {
    replaceTableBodyWithMessage(
      els.marketplaceExpenseReconciliationGroups,
      8,
      source.message || "Контрольные группы не рассчитаны.",
    );
  }
  if (items.length) {
    els.marketplaceExpenseReconciliationRows.replaceChildren(
      ...items.map(marketplaceExpenseItemRowNode),
    );
  } else {
    replaceTableBodyWithMessage(
      els.marketplaceExpenseReconciliationRows,
      10,
      source.message || "Документы услуг 1С не загружены.",
    );
  }
}

function marketplaceExpenseGroupRowNode(item) {
  const row = document.createElement("tr");
  if (item.status !== "matched") row.className = "is-review has-delta";
  appendTableCells(row, [
    { value: [item.periodStart, item.periodEnd].filter(Boolean).join(" — ") || "-" },
    { value: [item.organization, item.cabinet].filter(Boolean).join(" · ") || "-" },
    { value: item.controlGroupLabel || item.controlGroup || "-", className: "text-wide" },
    { value: optionalMoney(item.wbAmountWithVat), className: "numeric" },
    { value: optionalMoney(item.onecAmountWithVat), className: "numeric" },
    {
      value: item.delta == null ? "-" : signedMoney(item.delta),
      className: `numeric ${valueTone(item.delta, { zero: "muted" })}`,
    },
    { value: marketplaceExpenseStatusLabel(item.status) },
    { value: item.message || "-", className: "text-wide" },
  ]);
  return row;
}

function marketplaceExpenseItemRowNode(item) {
  const row = document.createElement("tr");
  const itemStatus = item.status || item.matchStatus;
  if (itemStatus !== "matched") row.className = "is-review";
  appendTableCells(row, [
    { value: [item.periodStart, item.periodEnd].filter(Boolean).join(" — ") || "-" },
    { value: item.documentDate || item.recognitionDate || "-" },
    { value: [item.documentNumber, item.inputNumber].filter(Boolean).join(" · ") || "-", className: "text-code" },
    { value: item.serviceName || item.controlGroupLabel || "-", className: "text-wide" },
    { value: optionalMoney(item.amountWithoutVat), className: "numeric" },
    { value: optionalMoney(item.vat), className: "numeric" },
    { value: optionalMoney(item.amountWithVat), className: "numeric" },
    { value: item.sourceKind || "-" },
    { value: marketplaceExpenseStatusLabel(itemStatus) },
    { value: item.nextAction || "-", className: "text-wide" },
  ]);
  return row;
}

async function loadCogsReconciliation() {
  const reportId = state.reportId;
  if (!reportId) {
    return;
  }
  const params = new URLSearchParams();
  const periodStart = els.topbarPeriodStart.value;
  const periodEnd = els.topbarPeriodEnd.value;
  const cabinetId = els.topbarCabinetSelect.value;
  if (periodStart) {
    params.set("period_start", periodStart);
  }
  if (periodEnd) {
    params.set("period_end", periodEnd);
  }
  if (cabinetId) {
    params.set("wb_cabinet_id", cabinetId);
  }
  const requestKey = `${reportId}:${params.toString()}`;
  state.cogsReconciliationRequestKey = requestKey;
  renderCogsReconciliationStatus("Собираем сверку себестоимости WB и 1С.");
  try {
    const payload = await api(
      `/api/reports/${encodeURIComponent(reportId)}/cogs-reconciliation?${params}`,
    );
    if (
      state.reportId !== reportId ||
      state.cogsReconciliationRequestKey !== requestKey
    ) {
      return;
    }
    renderCogsReconciliation(payload || {});
  } catch (_error) {
    if (
      state.reportId === reportId &&
      state.cogsReconciliationRequestKey === requestKey
    ) {
      renderCogsReconciliationStatus(
        "Не удалось загрузить сверку себестоимости. Повторите запрос.",
      );
    }
  }
}

function renderCogsReconciliationStatus(message) {
  els.cogsReconciliationCount.textContent = "";
  els.cogsReconciliationStatus.textContent = message;
  renderMetrics(els.cogsReconciliationGrid, []);
  replaceTableBodyWithMessage(els.cogsReconciliationRows, 11, message);
  replaceTableBodyWithMessage(els.cogsCostIssueRows, 10, message);
}

function renderCogsReconciliation(payload = {}) {
  const summary = payload.summary || {};
  const items = asArray(payload.items);
  const costItems = asArray(payload.costItems);
  const delta = Number(summary.delta || 0);
  const unexplained = Number(summary.unexplainedDelta || 0);
  const reviewRows = Number(summary.costReviewRows || 0);
  els.cogsReconciliationCount.textContent = `${number(items.length)} компонентов`;
  renderMetrics(els.cogsReconciliationGrid, [
    [
      "Товарный P&L WB",
      optionalMoney(summary.pnlCogs),
      "Месяц окончания недели WB",
    ],
    [
      "Себестоимость 1С",
      optionalMoney(summary.onecCogs),
      "Календарная дата проведения 1С",
    ],
    [
      "Общая разница",
      signedMoney(delta),
      "1С календарь − товарный P&L WB",
      Math.abs(unexplained) <= 1 ? "warning" : "bad",
    ],
    [
      "Переходящие недели",
      signedMoney(
        Number(summary.commissionerBoundaryDelta || 0) +
          Number(summary.buyoutBoundaryDelta || 0),
      ),
      "Документ 1С и неделя WB попали в разные месяцы",
    ],
    [
      "Разница совпадающих недель",
      signedMoney(
        Number(summary.commissionerSameScopeDelta || 0) +
          Number(summary.buyoutSameScopeDelta || 0),
      ),
      "Цена и допрасходы 1С против себестоимости строк WB",
    ],
    [
      "Закрытие месяца 1С",
      signedMoney(summary.adjustmentDelta || 0),
      "Стоимостные корректировки без товарного количества WB",
    ],
    [
      "Не объяснено",
      signedMoney(unexplained),
      "Должно быть не более 1 ₽",
      Math.abs(unexplained) <= 1 ? "ok" : "bad",
    ],
    [
      "Строки к проверке",
      number(reviewRows),
      reviewRows
        ? `${optionalMoney(summary.costReviewCogs)} себестоимости · ${optionalMoney(
            summary.affectedRevenue,
          )} выручки`
        : "Нет строк с fallback себестоимости",
      reviewRows ? "warning" : "ok",
    ],
  ]);
  els.cogsReconciliationStatus.textContent = payload.supported
    ? summary.status === "explained"
      ? "Разница полностью объяснена периодами и документами."
      : "Разница разложена, но есть строки себестоимости для проверки."
    : payload.supportMessage ||
      "Для строк старого отчёта источник себестоимости не сохранён; нужна пересборка.";
  if (items.length) {
    els.cogsReconciliationRows.replaceChildren(
      ...items.map(cogsReconciliationRowNode),
    );
  } else {
    replaceTableBodyWithMessage(
      els.cogsReconciliationRows,
      11,
      "Нет документов себестоимости в выбранном диапазоне.",
    );
  }
  if (costItems.length) {
    els.cogsCostIssueRows.replaceChildren(...costItems.map(cogsCostIssueRowNode));
  } else {
    replaceTableBodyWithMessage(
      els.cogsCostIssueRows,
      10,
      payload.supported
        ? "Строки себестоимости, требующие проверки, не найдены."
        : "Источник себестоимости появится после пересборки отчёта.",
    );
  }
}

function cogsReconciliationRowNode(item) {
  const row = document.createElement("tr");
  if (item.status === "Проверить стоимость") {
    row.className = "is-review has-delta";
  } else if (item.status === "Переходящая неделя") {
    row.className = "is-review";
  }
  appendTableCells(row, [
    { value: item.documentType || item.component || "-", className: "text-wide" },
    {
      value: [item.salesPeriodStart, item.salesPeriodEnd].filter(Boolean).join(" — ") || "-",
      className: "text-nowrap",
    },
    { value: item.onecDocumentDate || "-", className: "text-nowrap" },
    {
      value: [item.wbReportIds, item.onecDocuments].filter(Boolean).join(" · ") || "-",
      className: "text-wide text-code",
    },
    { value: optionalMoney(item.pnlCogs), className: "numeric" },
    { value: optionalMoney(item.onecSameScopeCogs), className: "numeric" },
    { value: optionalMoney(item.onecCalendarCogs), className: "numeric" },
    {
      value: signedMoney(item.sameScopeDelta || 0),
      className: `numeric ${valueTone(item.sameScopeDelta, { zero: "muted" })}`,
    },
    {
      value: signedMoney(item.boundaryDelta || 0),
      className: `numeric ${valueTone(item.boundaryDelta, { zero: "muted" })}`,
    },
    {
      value: item.status || "-",
      badge: true,
      tone: item.status === "Сходится" ? "ok" : "warning",
    },
    { value: `${item.reason || ""} ${item.action || ""}`.trim() || "-", className: "text-wide" },
  ]);
  return row;
}

function cogsCostIssueRowNode(item) {
  const row = document.createElement("tr");
  row.className = "is-review";
  appendTableCells(row, [
    {
      value: [item.weekStart, item.weekEnd].filter(Boolean).join(" — ") || "-",
      className: "text-nowrap",
    },
    { value: item.product || item.articleWb || "-", className: "text-wide" },
    { value: item.article1c || "-", className: "text-code" },
    { value: number(item.netQuantity || 0), className: "numeric" },
    { value: optionalMoney(item.cogs), className: "numeric" },
    { value: optionalMoney(item.unitCost), className: "numeric" },
    {
      value: item.costMatchStatus || item.costMethod || "Не сохранён",
      badge: true,
      tone: "warning",
    },
    {
      value:
        [item.costSourcePeriodStart, item.costSourcePeriodEnd]
          .filter(Boolean)
          .join(" — ") || "-",
      className: "text-nowrap",
    },
    { value: item.costSourceDocument || "-", className: "text-wide text-code" },
    { value: item.reason || item.status || "-", className: "text-wide" },
  ]);
  return row;
}

async function loadBuyoutReconciliation() {
  const reportId = state.reportId;
  if (!reportId) {
    return;
  }
  const params = new URLSearchParams();
  const periodStart = els.topbarPeriodStart.value;
  const periodEnd = els.topbarPeriodEnd.value;
  const cabinetId = els.topbarCabinetSelect.value;
  if (periodStart) {
    params.set("period_start", periodStart);
  }
  if (periodEnd) {
    params.set("period_end", periodEnd);
  }
  if (cabinetId) {
    params.set("wb_cabinet_id", cabinetId);
  }
  const requestKey = `${reportId}:${params.toString()}`;
  state.buyoutReconciliationRequestKey = requestKey;
  renderBuyoutReconciliationStatus("Загружаем документы выкупов.");
  try {
    const payload = await api(
      `/api/reports/${encodeURIComponent(reportId)}/buyout-reconciliation?${params}`,
    );
    if (
      state.reportId !== reportId ||
      state.buyoutReconciliationRequestKey !== requestKey
    ) {
      return;
    }
    renderBuyoutReconciliation(payload || {});
  } catch (_error) {
    if (
      state.reportId === reportId &&
      state.buyoutReconciliationRequestKey === requestKey
    ) {
      renderBuyoutReconciliationStatus(
        "Не удалось загрузить расшифровку выкупов. Повторите запрос.",
      );
    }
  }
}

function renderBuyoutReconciliationStatus(message) {
  els.buyoutReconciliationCount.textContent = "";
  els.buyoutReconciliationStatus.textContent = message;
  renderMetrics(els.buyoutReconciliationGrid, []);
  replaceTableBodyWithMessage(els.buyoutReconciliationRows, 10, message);
}

function renderBuyoutReconciliation(payload = {}) {
  const summary = payload.summary || {};
  const rows = asArray(payload.items);
  const total = Number(payload.total || rows.length || 0);
  const missingOnecRows = Number(summary.missingOnecRows || 0);
  const quantityIssueRows = Number(summary.quantityIssueRows || 0);
  const unverifiedPrimaryRows = Number(summary.unverifiedPrimaryRows || 0);
  const primaryVerified = summary.primaryDocumentStatus === "verified";
  els.buyoutReconciliationCount.textContent = total
    ? `${number(total)} документов`
    : "Нет документов";
  renderMetrics(els.buyoutReconciliationGrid, [
    [
      "Первичка WB · сумма выкупа",
      primaryVerified ? optionalMoney(summary.primaryDocumentAmount) : "Не загружена",
      "Сопоставимая база для накладной 1С",
      primaryVerified ? "ok" : "warning",
    ],
    ["Накладные 1С", optionalMoney(summary.onecNetAmount)],
    [
      "Результат сверки первички",
      primaryVerified && summary.primaryDocumentDelta != null
        ? signedMoney(summary.primaryDocumentDelta)
        : "Не проверено",
      primaryVerified
        ? "Первичка WB − накладная 1С"
        : `${number(unverifiedPrimaryRows)} документов без первички WB`,
      primaryVerified && Math.abs(Number(summary.primaryDocumentDelta || 0)) <= 1
        ? "ok"
        : "warning",
    ],
    ["Розница WB · справочно", optionalMoney(summary.wbRetailAmount)],
    [
      "Разница ценовых баз · справочно",
      summary.nonComparableDifference == null
        ? "-"
        : signedMoney(summary.nonComparableDifference),
      "Не является расхождением документов",
      "",
    ],
    ["Нет накладной 1С", number(missingOnecRows), "", missingOnecRows ? "bad" : "ok"],
    [
      "Проверить количество",
      number(quantityIssueRows),
      "",
      quantityIssueRows ? "warning" : "ok",
    ],
  ]);
  els.buyoutReconciliationStatus.textContent =
    missingOnecRows || quantityIssueRows
      ? "Сначала исправьте строки в начале списка: без накладной 1С или с неподтверждённым количеством."
      : unverifiedPrimaryRows
        ? "Накладные 1С найдены, но денежная сверка не завершена: загрузите первичные уведомления WB с полем «Сумма выкупа» и пересоберите отчёт."
        : "Первичные уведомления WB и накладные 1С сверены.";
  if (!rows.length) {
    replaceTableBodyWithMessage(
      els.buyoutReconciliationRows,
      10,
      "Выкупы по выбранному периоду и кабинету не найдены.",
    );
    return;
  }
  els.buyoutReconciliationRows.replaceChildren(
    ...rows.map(buyoutReconciliationRowNode),
  );
}

function buyoutReconciliationRowNode(item) {
  const row = document.createElement("tr");
  if (item.missingOnec) {
    row.className = "is-missing-onec";
  } else if (item.quantityIssue) {
    row.className = "is-review has-delta";
  } else if (item.primaryDocumentStatus !== "verified") {
    row.className = "is-review";
  }
  appendTableCells(row, [
    { value: item.salesPeriod || "-", className: "text-nowrap" },
    { value: item.wbReports || "-", className: "text-wide text-code" },
    { value: item.onecDocumentDate || item.expectedDocumentDate || "-", className: "text-nowrap" },
    { value: item.onecDocuments || "Не найдена", className: "text-wide text-code" },
    {
      value:
        item.primaryDocumentStatus === "verified"
          ? optionalMoney(item.primaryDocumentAmount)
          : "Не загружена",
      className: "numeric",
    },
    { value: optionalMoney(item.onecNetAmount), className: "numeric" },
    {
      value:
        item.primaryDocumentDelta == null
          ? "-"
          : signedMoney(item.primaryDocumentDelta),
      className: `numeric delta ${valueTone(item.primaryDocumentDelta, { zero: "muted" })}`,
    },
    { value: optionalMoney(item.wbRetailAmount), className: "numeric" },
    {
      value: item.quantityStatus || "-",
      badge: true,
      tone: item.missingOnec ? "blocked" : item.quantityIssue ? "warning" : "ok",
    },
    { value: item.reason || "-", className: "text-wide" },
  ]);
  return row;
}

async function selectDrilldownPreset(preset = "review") {
  const descriptor = drilldownDescriptor(preset);
  state.drilldownPreset = descriptor.preset;
  els.drilldownTitle.textContent = descriptor.title;
  els.drilldownSubtitle.textContent = descriptor.subtitle;
  els.drilldownTabs.forEach((button) => {
    const selected = button.dataset.drilldownPreset === descriptor.preset;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", selected ? "true" : "false");
  });
  if (descriptor.preset === "sources") {
    state.drilldownRequestKey = "";
    els.drilldownTableWrap.hidden = true;
    els.drilldownSources.hidden = false;
    els.drilldownGuidance.hidden = true;
    els.drilldownGuidance.replaceChildren();
    renderSourceDrilldown();
    return;
  }
  els.drilldownSources.hidden = true;
  els.drilldownGuidance.hidden = descriptor.preset !== "missingCost";
  els.drilldownGuidance.replaceChildren();
  els.drilldownTableWrap.hidden = false;
  await loadDrilldownRows(descriptor.preset);
}

async function loadDrilldownRows(preset) {
  const reportId = state.reportId;
  if (!reportId) {
    return;
  }
  const params = rowsFilterParams(preset);
  const requestKey = rowsRequestKey(reportId, params);
  state.drilldownRequestKey = requestKey;
  renderDrilldownRowsStatus("Загружаем строки по текущим фильтрам.", "Загрузка");
  try {
    const payload = await api(`/api/reports/${encodeURIComponent(reportId)}/rows?${params}`);
    if (state.reportId !== reportId || state.drilldownRequestKey !== requestKey) {
      return;
    }
    renderDrilldownRows(
      payload.items || [],
      payload.total || 0,
      preset,
      payload.costIssueBreakdown || {},
    );
  } catch (error) {
    if (state.reportId !== reportId || state.drilldownRequestKey !== requestKey) {
      return;
    }
    renderDrilldownRowsStatus("Не удалось загрузить расшифровку. Повторите запрос.");
  }
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
      title: "Проверка себестоимости 1С",
      subtitle: "Отдельно показаны строки с временной себестоимостью и товары, где себестоимость действительно не найдена.",
    },
    missingMapping: {
      preset: "missingMapping",
      title: "Проблемы сопоставления WB ↔ 1C",
      subtitle: "Товары без связи WB–1С или с неоднозначным сопоставлением.",
    },
    losses: {
      preset: "losses",
      title: "Убыточные продажи",
      subtitle: "Продажи с отрицательной товарной маржой для проверки экономики.",
    },
    penaltyOnly: {
      preset: "penaltyOnly",
      title: "Штрафные инциденты без продаж",
      subtitle: "Штрафы WB без продаж и товарной себестоимости в той же строке.",
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
  closeAiWidget({ restoreFocus: false });
  closeClientOutputWidget({ restoreFocus: false });
  closeReportWizard({ restoreFocus: false });
  closeIntegrationsWidget({ restoreFocus: false });
  closeMappingWidget({ restoreFocus: false });
  closeNewClientWidget({ restoreFocus: false });
  closeDrilldownWidget({ restoreFocus: false });
  closeBuyoutReconciliationWidget({ restoreFocus: false });
  closeCogsReconciliationWidget({ restoreFocus: false });
  closeMarketplaceExpenseReconciliationWidget({ restoreFocus: false });
  state.activeWidgetOverlay = null;
  restoreWidgetFocus();
}

function updateWidgetBodyState() {
  document.body.classList.toggle(
    "widget-open",
      !els.aiWidgetOverlay.hidden ||
      !els.clientOutputWidgetOverlay.hidden ||
      !els.reportWizardOverlay.hidden ||
      !els.integrationsWidgetOverlay.hidden ||
      !els.mappingWidgetOverlay.hidden ||
      !els.newClientWidgetOverlay.hidden ||
      !els.drilldownWidgetOverlay.hidden ||
      !els.buyoutReconciliationOverlay.hidden ||
      !els.cogsReconciliationOverlay.hidden ||
      !els.marketplaceExpenseReconciliationOverlay.hidden,
  );
}

function openWidgetOverlay(overlay) {
  if (overlay.hidden) {
    state.widgetReturnFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
  }
  overlay.hidden = false;
  state.activeWidgetOverlay = overlay;
  document.body.classList.add("widget-open");
}

function closeWidgetOverlay(overlay, options = {}) {
  overlay.hidden = true;
  updateWidgetBodyState();
  if (state.activeWidgetOverlay === overlay) {
    state.activeWidgetOverlay = currentOpenWidgetOverlay();
  }
  if (!state.activeWidgetOverlay && options.restoreFocus !== false) {
    restoreWidgetFocus();
  }
}

function currentOpenWidgetOverlay() {
  return [
    els.aiWidgetOverlay,
    els.clientOutputWidgetOverlay,
    els.reportWizardOverlay,
    els.integrationsWidgetOverlay,
    els.mappingWidgetOverlay,
    els.newClientWidgetOverlay,
    els.drilldownWidgetOverlay,
    els.buyoutReconciliationOverlay,
    els.cogsReconciliationOverlay,
    els.marketplaceExpenseReconciliationOverlay,
  ].find((overlay) => overlay && !overlay.hidden) || null;
}

function restoreWidgetFocus() {
  const target = state.widgetReturnFocus;
  state.widgetReturnFocus = null;
  if (target?.isConnected && typeof target.focus === "function") {
    window.setTimeout(() => target.focus(), 0);
  }
}

function trapWidgetFocus(event) {
  const overlay = state.activeWidgetOverlay;
  if (!overlay || overlay.hidden) {
    return;
  }
  const focusable = Array.from(
    overlay.querySelectorAll(FOCUSABLE_WIDGET_SELECTOR),
  ).filter(isVisibleFocusable);
  if (!focusable.length) {
    event.preventDefault();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
    return;
  }
  if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function isVisibleFocusable(element) {
  return !element.closest("[hidden]") && element.getAttribute("aria-hidden") !== "true";
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
    await Promise.all([
      loadIntegrations(context),
      loadSourceRefreshStatus(context),
    ]);
    const keepOzonServiceVitrine = shouldKeepOzonDiagnosticsVisible();
    if (isAiPage()) {
      renderAiPageHeader(
        "Нет доступных отчетов",
        "После импорта отчета AI-аналитик сможет отвечать по расчетной витрине.",
      );
    } else if (isIntegrationsPage()) {
      if (keepOzonServiceVitrine) {
        setOzonServiceCabinetNotice();
        renderOzonDiagnosticsPayload(state.latestOzonDiagnostics);
      } else {
        setEmptyCabinet();
      }
      openIntegrationsWidget({ focus: false });
    } else if (keepOzonServiceVitrine) {
      setOzonServiceCabinetNotice();
      renderOzonDiagnosticsPayload(state.latestOzonDiagnostics);
    } else {
      setEmptyCabinet();
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
  els.reportLoadRetryButton.hidden = true;
  let summary;
  try {
    summary = await api(`/api/reports/${encodeURIComponent(reportId)}/summary`);
  } catch (error) {
    if (!isCurrentClientLoad(context) || state.reportId !== reportId) {
      return;
    }
    renderReportLoadError();
    return;
  }
  if (!isCurrentClientLoad(context) || state.reportId !== reportId) {
    return;
  }
  state.summary = summary;
  state.freshness = null;
  if (normalize(summary.marketplace) === "ozon") {
    state.latestOzonDiagnostics = summary.ozonDiagnostics || null;
    renderFilters(summary.options || clientScopedFilterOptions());
    setOzonDraftNotice(summary);
    renderOzonDiagnosticsPayload(state.latestOzonDiagnostics);
    await Promise.allSettled([
      loadIntegrations(context),
      loadSourceRefreshStatus(context),
    ]);
    configurePageMode();
    return;
  }
  renderReport();
  renderFilters(summary.options || {});
  renderOnecReconciliation([], 0, summary.quality || {});
  await Promise.allSettled([
    loadReportFreshness(reportId, context),
    loadReviewRows(state.rowPreset, { ...context, reportId }),
    loadClientDraft({ ...context, reportId }),
    loadIntegrations(context),
    loadSourceRefreshStatus(context),
  ]);
  configurePageMode();
}

async function loadReportFreshness(reportId, context = currentClientLoadContext()) {
  try {
    const freshness = await api(
      `/api/reports/${encodeURIComponent(reportId)}/freshness`,
    );
    if (!isCurrentClientLoad(context) || state.reportId !== reportId) {
      return;
    }
    state.freshness = freshness;
    renderReport();
  } catch (error) {
    if (!isCurrentClientLoad(context) || state.reportId !== reportId) {
      return;
    }
    state.freshness = null;
    renderReportFreshnessWarning();
  }
}

function renderReportLoadError() {
  state.summary = null;
  state.freshness = null;
  setEmptyCabinet(
    "Не удалось загрузить отчёт",
    "Показатели не получены. Повторите запрос; сохранённые данные отчёта не изменялись.",
  );
  renderReviewRows([], 0);
  renderLostSales([]);
  renderLiquidity([]);
  els.reportLoadRetryButton.disabled = false;
  els.reportLoadRetryButton.hidden = false;
}

function renderReportFreshnessWarning() {
  const currentSubtitle = els.reportSubtitle.textContent || "";
  const warning = "Статус свежести источников временно недоступен.";
  if (!currentSubtitle.includes(warning)) {
    els.reportSubtitle.textContent = currentSubtitle
      ? `${currentSubtitle} · ${warning}`
      : warning;
  }
  els.brandLockup.classList.remove("is-info", "is-ok", "is-blocked");
  els.brandLockup.classList.add("is-warning");
}

async function retryCurrentReportLoad() {
  const reportId = state.reportId;
  if (!reportId || els.reportLoadRetryButton.disabled) {
    return;
  }
  const context = currentClientLoadContext();
  els.reportLoadRetryButton.disabled = true;
  setEmptyCabinet(
    "Загружаем отчёт",
    "Повторно получаем показатели выбранного клиента.",
  );
  await loadReport(reportId, context);
}

async function loadReviewRows(preset = state.rowPreset, context = currentClientLoadContext()) {
  if (shouldUseOzonWorkingView()) {
    renderOzonWorkingView();
    return;
  }
  const reportId = context.reportId || state.reportId;
  if (!reportId) {
    return;
  }
  const params = rowsFilterParams(preset);
  const requestKey = rowsRequestKey(reportId, params);
  state.rowsRequestKey = requestKey;
  renderRowsLoadingState();
  let payload = null;
  try {
    payload = await api(`/api/reports/${encodeURIComponent(reportId)}/rows?${params}`);
  } catch (error) {
    if (!isCurrentRowsRequest(context, reportId, requestKey)) {
      return;
    }
    renderRowsErrorState();
    return;
  }
  if (!isCurrentRowsRequest(context, reportId, requestKey)) {
    return;
  }
  const hasDrilldownPreset = Boolean(preset);
  const analytics = hasDrilldownPreset
    ? state.summary || filteredAnalyticsSummary(payload)
    : filteredAnalyticsSummary(payload);
  renderKpis(
    (analytics || {}).kpis || {},
    (analytics || {}).taxContext || {},
    (analytics || {}).lostSalesCoverage || {},
  );
  renderAnalytics(analytics);
  renderLiquidity(asArray(analytics.liquidityRows));
  renderLostSales(
    asArray(analytics.lostSales),
    analytics.lostSalesCoverage || {},
  );
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
  const params = onecReconciliationFilterParams();
  const requestKey = onecReconciliationRequestKey(reportId, params);
  state.onecReconciliationRequestKey = requestKey;
  renderFinancialReconciliationStatus("Загружаем финансовую сверку.", "Загрузка");
  renderOnecReconciliationStatus("Загружаем техническую сверку WB ↔ 1C.");
  const [documentResult, financialResult] = await Promise.allSettled([
    api(
      `/api/reports/${encodeURIComponent(reportId)}/document-reconciliation?${params}`,
    ),
    api(
      `/api/reports/${encodeURIComponent(reportId)}/financial-document-reconciliation?${params}`,
    ),
  ]);
  if (!isCurrentOnecReconciliationRequest(context, reportId, requestKey)) {
    return;
  }
  state.onecReconciliationLoaded =
    documentResult.status === "fulfilled" || financialResult.status === "fulfilled";
  if (financialResult.status === "fulfilled") {
    const payload = financialResult.value || {};
    renderFinancialReconciliation(
      payload.items || [],
      payload.total || 0,
      payload.kpis || {},
      payload.source || {},
      payload.period || {},
    );
  } else {
    renderFinancialReconciliationStatus(
      "Не удалось загрузить выручку и штрафы. Повторите запрос.",
      "Ошибка",
    );
  }
  if (documentResult.status === "fulfilled") {
    const payload = documentResult.value || {};
    renderOnecReconciliation(
      payload.items || [],
      payload.total || 0,
      payload.kpis || {},
    );
  } else {
    renderOnecReconciliationStatus(
      "Не удалось загрузить техническую сверку WB ↔ 1C.",
    );
  }
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
    els.draftStatus.textContent = `Версия ${payload.latest.revision}: ${status}.`;
  } catch (error) {
    if (reportId !== state.reportId || !isCurrentClientLoad(context)) {
      return;
    }
    els.draftPanel.hidden = false;
    els.draftStatus.textContent = isStaffUser()
      ? "Отчёт для клиента пока не подготовлен."
      : "Отчёт для клиента готовит консультант. Данные отчета не менялись.";
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
      ? "Резервный ответ · расчётная витрина"
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
  const latestRefresh =
    state.latestSourceRefresh ||
    summary.latestSourceRefresh ||
    freshness.latestSourceRefresh;

  els.reviewRowsButton.disabled = false;
  els.reviewRowsButton.textContent = "Открыть проблемные строки";

  setTopbarNotice(
    readiness.status === "ready"
      ? "Пульт подготовки отчета"
      : "Предварительный отчёт — финансовая проверка не завершена",
    reportFreshnessSubtitle(summary.meta || {}, latestRefresh),
    reportTopbarTone(readiness, latestRefresh),
  );

  renderReadiness(readiness);
  updateReportBuildButton(latestRefresh);
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
  renderKpis(
    summary.kpis || {},
    summary.taxContext || {},
    summary.lostSalesCoverage || {},
  );
  renderAnalytics(summary);
  renderOzonPreview(latestRefresh, state.latestOzonDiagnostics);
  renderLiquidity(asArray(summary.liquidityRows));
  renderLostSales(
    asArray(summary.lostSales),
    summary.lostSalesCoverage || {},
  );
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
    loadSourceRefreshStatus(currentClientLoadContext());
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
      renderKpis(
        (state.summary || {}).kpis || {},
        (state.summary || {}).taxContext || {},
        (state.summary || {}).lostSalesCoverage || {},
      );
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
  if (!shouldUseOzonWorkingView() && els.filterMonth.value) {
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
      controlType: els.onecFilterControlType.value,
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
  setSelectValue(els.onecFilterControlType, onec.controlType || "");
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
  role.textContent = data.readOnly === false ? "доступ" : "только чтение";
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
      "В форме выше выбран API кабинета продавца Ozon. Заполните идентификатор клиента и API-ключ, затем сохраните и проверьте.",
    ];
  }
  if (state.integrationProviderFilter === "onec_readonly") {
    return [
      "1C еще не подключена",
      "В форме выше выбрана 1C только для чтения. Заполните URL, пользователя и пароль.",
    ];
  }
  if (state.integrationProviderFilter === "wb_api") {
    return [
      "WB еще не подключен",
      "Добавьте кабинет клиента и сохраните ключ WB только для чтения.",
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
  els.sourceRefreshStatus.textContent = "Проверяем последнее обновление данных...";
  try {
    const mode = selectedSourceRefreshMode();
    const modeQuery = mode ? `?mode=${encodeURIComponent(mode)}` : "";
    const payload = await api(
      `/api/clients/${encodeURIComponent(clientId)}/source-refresh/latest${modeQuery}`,
    );
    if (!isCurrentClientLoad(context)) {
      return;
    }
    state.activeSourceRefresh = payload.activeRun || null;
    state.latestSourceRefreshAttempt = payload.latestAttempt || null;
    state.latestSourceRefresh = state.activeSourceRefresh || payload.latest || null;
    renderSourceRefreshControl(
      state.latestSourceRefresh,
      state.latestSourceRefreshAttempt,
    );
    await loadOzonDiagnostics(context);
  } catch (error) {
    if (!isCurrentClientLoad(context)) {
      return;
    }
    state.latestSourceRefresh = null;
    state.latestSourceRefreshAttempt = null;
    state.activeSourceRefresh = null;
    state.latestOzonDiagnostics = null;
    updateReportBuildButton(null);
    renderReportWizardStatus(null);
    els.sourceRefreshStatus.textContent =
      "Не удалось загрузить статус обновления источников.";
    renderSourceRefreshSteps(null);
    els.sourceRefreshCollections.replaceChildren();
    renderOzonPreview(null, null);
  }
}

async function loadMappingItems(context = {}) {
  const clientId = context.clientId || state.clientId;
  if (!isStaffUser() || !clientId) {
    resetMappingServicePanel({ hide: true });
    return;
  }
  els.mappingServicePanel.hidden = false;
  els.mappingServiceStatus.textContent = "Загружаем товары для сопоставления...";
  const params = new URLSearchParams();
  const selectedStatus = els.mappingStatusFilter.value;
  const reviewMode = selectedStatus === "review";
  if (els.mappingMarketplaceFilter.value) {
    params.set("marketplace", els.mappingMarketplaceFilter.value);
  }
  if (selectedStatus && !reviewMode) {
    params.set("status", selectedStatus);
  }
  if (els.mappingSearch.value.trim()) {
    params.set("search", els.mappingSearch.value.trim());
  }
  params.set("limit", "100");
  const paramsKey = reviewMode
    ? `${params.toString()}&status=review`
    : params.toString();
  const requestKey = mappingItemsRequestKey(clientId, paramsKey);
  state.mappingItemsRequestKey = requestKey;
  try {
    let payload = null;
    if (reviewMode) {
      const reviewPayloads = await Promise.all(
        MAPPING_REVIEW_STATUSES.map((status) => {
          const reviewParams = new URLSearchParams(params);
          reviewParams.set("status", status);
          return api(
            `/api/clients/${encodeURIComponent(clientId)}/mapping/items?${reviewParams}`,
          );
        }),
      );
      payload = {
        items: reviewPayloads.flatMap((item) => item.items || []),
        total: reviewPayloads.reduce((total, item) => total + (item.total || 0), 0),
      };
    } else {
      payload = await api(
        `/api/clients/${encodeURIComponent(clientId)}/mapping/items?${paramsKey}`,
      );
    }
    if (!isCurrentMappingItemsRequest(context, requestKey)) {
      return;
    }
    state.mappingItems = payload.items || [];
    if (
      state.mappingSelectedItemId &&
      !state.mappingItems.some((item) => item.id === state.mappingSelectedItemId)
    ) {
      state.mappingSelectedItemId = "";
      state.mappingCandidates = [];
      state.mappingHistory = [];
    }
    renderMappingItems(payload.total || 0);
    if (state.mappingSelectedItemId) {
      await selectMappingItem(state.mappingSelectedItemId, context, { preserve: true });
    } else {
      renderMappingDetail();
    }
  } catch (error) {
    if (!isCurrentMappingItemsRequest(context, requestKey)) {
      return;
    }
    state.mappingItems = [];
    els.mappingServiceStatus.textContent =
      "Не удалось загрузить сервис сопоставления.";
    renderMappingItems(0);
    renderMappingDetail();
  }
}

async function selectMappingItem(itemId, context = {}, options = {}) {
  if (!itemId) {
    return;
  }
  state.mappingSelectedItemId = itemId;
  renderMappingItems(state.mappingItems.length);
  try {
    const clientId = context.clientId || state.clientId;
    const [candidatePayload, historyPayload] = await Promise.all([
      api(
        `/api/clients/${encodeURIComponent(clientId)}/mapping/items/${encodeURIComponent(itemId)}/candidates`,
      ),
      api(
        `/api/clients/${encodeURIComponent(clientId)}/mapping/items/${encodeURIComponent(itemId)}/history`,
      ),
    ]);
    if (!isCurrentClientLoad(context)) {
      return;
    }
    state.mappingCandidates = candidatePayload.candidates || [];
    state.mappingHistory = historyPayload.items || [];
    if (!options.preserve) {
      els.mappingOnecSearch.value = "";
      els.mappingOnecResults.replaceChildren();
    }
    renderMappingDetail(candidatePayload.item || selectedMappingItem());
  } catch (error) {
    if (!isCurrentClientLoad(context)) {
      return;
    }
    state.mappingCandidates = [];
    state.mappingHistory = [];
    renderMappingDetail(selectedMappingItem(), "Не удалось загрузить кандидатов.");
  }
}

async function rebuildMappingCandidates(context = {}) {
  const clientId = context.clientId || state.clientId;
  if (!clientId) {
    return;
  }
  els.mappingRebuildButton.disabled = true;
  els.mappingServiceStatus.textContent = "Перестраиваем кандидатов...";
  try {
    const payload = await api(
      `/api/clients/${encodeURIComponent(clientId)}/mapping/rebuild-candidates`,
      { method: "POST", body: JSON.stringify({}) },
    );
    if (!isCurrentClientLoad(context)) {
      return;
    }
    els.mappingServiceStatus.textContent = [
      `Автоматически сопоставлено по штрихкоду 1С: ${payload.autoAccepted || 0}.`,
      `Требует ручного решения: ${payload.remainingReview || 0}.`,
      `Конфликт с ранее принятой связью: ${payload.currentMappingConflictCount || 0}.`,
    ].join(" ");
    await loadMappingItems(context);
    await loadSourceRefreshStatus(context);
  } catch (error) {
    if (isCurrentClientLoad(context)) {
      els.mappingServiceStatus.textContent = "Не удалось перестроить кандидатов.";
    }
  } finally {
    els.mappingRebuildButton.disabled = false;
  }
}

async function exportMappingRows(context = {}) {
  const clientId = context.clientId || state.clientId;
  if (!clientId) {
    return;
  }
  els.mappingExportButton.disabled = true;
  try {
    const payload = await api(
      `/api/clients/${encodeURIComponent(clientId)}/mapping/export/sku-mapping`,
    );
    if (isCurrentClientLoad(context)) {
      const summary = payload.summary || {};
      els.mappingServiceStatus.textContent =
        `Экспорт готов: WB ${summary.wbRows || 0}, Ozon ${summary.ozonRows || 0}, сопоставлено ${summary.matched || 0}.`;
    }
  } catch (error) {
    if (isCurrentClientLoad(context)) {
      els.mappingServiceStatus.textContent = "Экспорт сопоставлений не собрался.";
    }
  } finally {
    els.mappingExportButton.disabled = false;
  }
}

async function searchMappingOnec(context = {}) {
  const clientId = context.clientId || state.clientId;
  const query = els.mappingOnecSearch.value.trim();
  if (!clientId || !state.mappingSelectedItemId || query.length < 2) {
    els.mappingOnecResults.replaceChildren();
    return;
  }
  const params = new URLSearchParams({ query, limit: "8" });
  try {
    const payload = await api(
      `/api/clients/${encodeURIComponent(clientId)}/mapping/onec-search?${params}`,
    );
    if (!isCurrentClientLoad(context)) {
      return;
    }
    renderMappingOnecResults(payload.items || []);
  } catch (error) {
    if (isCurrentClientLoad(context)) {
      els.mappingOnecResults.replaceChildren(mappingMessage("Поиск 1C не загрузился."));
    }
  }
}

async function handleMappingCandidateAction(button, context = {}) {
  const action = button.dataset.mappingAction || "";
  const candidateId = button.dataset.candidateId || "";
  const itemId = state.mappingSelectedItemId;
  if (!itemId || !action) {
    return;
  }
  let body = {};
  if (action === "accept") {
    body = { candidate_id: candidateId, reason: "Подтверждено в web-кабинете" };
  } else if (action === "reject") {
    body = { candidate_id: candidateId, reason: "Отклонено в web-кабинете" };
  } else if (action === "revoke") {
    body = { reason: "Отозвано в web-кабинете" };
  } else if (action === "exclude") {
    body = { reason: "Исключено из расчета в web-кабинете" };
  }
  await postMappingAction(action, itemId, body, context);
}

async function acceptManualOnecMapping(onecMappingItemId, context = {}) {
  if (!onecMappingItemId || !state.mappingSelectedItemId) {
    return;
  }
  await postMappingAction(
    "accept",
    state.mappingSelectedItemId,
    {
      onec_mapping_item_id: onecMappingItemId,
      reason: "Ручной выбор из поиска 1C",
    },
    context,
  );
}

async function postMappingAction(action, itemId, body, context = {}) {
  const clientId = context.clientId || state.clientId;
  if (!clientId) {
    return;
  }
  try {
    await api(
      `/api/clients/${encodeURIComponent(clientId)}/mapping/items/${encodeURIComponent(itemId)}/${action}`,
      { method: "POST", body: JSON.stringify(body) },
    );
    if (!isCurrentClientLoad(context)) {
      return;
    }
    await loadMappingItems(context);
    await selectMappingItem(itemId, context, { preserve: true });
  } catch (error) {
    if (isCurrentClientLoad(context)) {
      renderMappingDetail(selectedMappingItem(), "Действие не выполнено: есть конфликт или не хватает причины.");
    }
  }
}

function renderMappingItems(total = 0) {
  const rows = state.mappingItems.map((item) => {
    const row = document.createElement("tr");
    row.dataset.mappingItemId = item.id;
    row.classList.toggle("active", item.id === state.mappingSelectedItemId);
    row.tabIndex = 0;
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        selectMappingItem(item.id, currentClientLoadContext());
      }
    });
    [
      marketplaceLabel(item.marketplace),
      item.title || "-",
      mappingItemKey(item),
      mappingStatusLabel(item.status),
      String(item.candidateCount || 0),
    ].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    });
    return row;
  });
  if (!rows.length) {
    els.mappingItemRows.replaceChildren(mappingTableEmptyRow());
  } else {
    els.mappingItemRows.replaceChildren(...rows);
  }
  const reviewCount = state.mappingItems.filter((item) =>
    mappingItemNeedsAnalyst(item.status),
  ).length;
  if (total > 0 && els.mappingStatusFilter.value === "review") {
    els.mappingServiceStatus.textContent =
      `В очереди аналитика ${total}. Показано ${state.mappingItems.length}.`;
  } else if (total > 0) {
    els.mappingServiceStatus.textContent =
      `Показано ${state.mappingItems.length} из ${total}. Требуют решения: ${reviewCount}.`;
  } else if (els.mappingStatusFilter.value === "review") {
    els.mappingServiceStatus.textContent = "Очередь аналитика пуста.";
  } else {
    els.mappingServiceStatus.textContent =
      "Товаров для сопоставления пока нет. Обновите источники данных или нажмите «Перестроить».";
  }
}

function renderMappingDetail(item = selectedMappingItem(), message = "") {
  if (!item) {
    els.mappingSelectedCard.textContent = message || "Выберите строку товара.";
    els.mappingCandidateList.replaceChildren();
    els.mappingHistoryList.replaceChildren();
    return;
  }
  const title = document.createElement("strong");
  title.textContent = item.title || mappingItemKey(item);
  const meta = document.createElement("span");
  meta.textContent =
    `${marketplaceLabel(item.marketplace)} · ${mappingItemKey(item)} · ${mappingStatusLabel(item.status)}` +
    (item.currentMapping
      ? ` · ${mappingCurrentMethodLabel(item.currentMapping.matchMethod)}`
      : "");
  const hintText = mappingStatusHint(item.status);
  const hint = document.createElement("small");
  hint.className = "muted";
  hint.textContent = hintText;
  const actions = document.createElement("div");
  actions.className = "mapping-inline-actions";
  if (item.currentMapping) {
    const revoke = mappingActionButton("revoke", "", "Отозвать");
    actions.append(revoke);
  } else {
    const exclude = mappingActionButton("exclude", "", "Исключить");
    exclude.classList.add("secondary-button");
    actions.append(exclude);
  }
  els.mappingSelectedCard.replaceChildren(
    title,
    meta,
    ...(hintText ? [hint] : []),
    actions,
  );
  if (message) {
    els.mappingCandidateList.replaceChildren(mappingMessage(message));
  } else if (!state.mappingCandidates.length) {
    els.mappingCandidateList.replaceChildren(mappingMessage("Кандидатов нет."));
  } else {
    els.mappingCandidateList.replaceChildren(
      ...state.mappingCandidates.map(mappingCandidateNode),
    );
  }
  els.mappingHistoryList.replaceChildren(
    ...(state.mappingHistory.length
      ? state.mappingHistory.map(mappingHistoryNode)
      : [mappingMessage("История пока пустая.")]),
  );
}

function renderMappingOnecResults(items) {
  if (!items.length) {
    els.mappingOnecResults.replaceChildren(mappingMessage("Ничего не найдено."));
    return;
  }
  els.mappingOnecResults.replaceChildren(
    ...items.map((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "mapping-onec-result secondary-button";
      button.dataset.onecMappingId = item.id;
      button.textContent = `${item.onecArticle || item.onecItemId || "-"} · ${item.name || "1C"}`;
      return button;
    }),
  );
}

function mappingCandidateNode(candidate, index) {
  const node = document.createElement("article");
  node.className = `mapping-candidate is-${normalize(candidate.status)}`;
  const onec = candidate.onecItem || {};
  const title = document.createElement("strong");
  title.textContent = `${onec.onecArticle || onec.onecItemId || "-"} · ${onec.name || "1C"}`;
  const meta = document.createElement("span");
  meta.textContent =
    `${mappingCandidateMethodLabel(candidate.method)} · ${Math.round((candidate.confidence || 0) * 100)}% · ${mappingCandidateSourceLabel(candidate.source)}`;
  const explanation = document.createElement("small");
  explanation.className = "mapping-candidate-explanation";
  explanation.textContent =
    index === 0 && candidate.status !== "rejected"
      ? "Наиболее точный кандидат. Решение принимает аналитик."
      : "Альтернативный вариант для ручной проверки.";
  const actions = document.createElement("div");
  actions.className = "mapping-inline-actions";
  if (candidate.status !== "rejected") {
    actions.append(
      mappingActionButton("accept", candidate.id, "Выбрать эту номенклатуру"),
      mappingActionButton("reject", candidate.id, "Отклонить вариант"),
    );
  } else {
    const rejected = document.createElement("small");
    rejected.textContent = candidate.rejectedReason || "Отклонено";
    actions.append(rejected);
  }
  node.append(title, meta, explanation, actions);
  return node;
}

function mappingHistoryNode(item) {
  const node = document.createElement("div");
  node.className = "mapping-history-item";
  const title = document.createElement("strong");
  title.textContent = mappingActionLabel(item.action);
  const meta = document.createElement("span");
  meta.textContent = `${formatDateTime(item.createdAt)} · ${item.reason || "-"}`;
  node.append(title, meta);
  return node;
}

function mappingActionButton(action, candidateId, label) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = action === "accept" ? "" : "secondary-button";
  button.dataset.mappingAction = action;
  if (candidateId) {
    button.dataset.candidateId = candidateId;
  }
  button.textContent = label;
  return button;
}

function mappingMessage(text) {
  const node = document.createElement("p");
  node.className = "muted mapping-message";
  node.textContent = text;
  return node;
}

function mappingTableEmptyRow() {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = 5;
  cell.textContent = "Нет товаров по выбранным фильтрам.";
  row.append(cell);
  return row;
}

function resetMappingServicePanel(options = {}) {
  state.mappingItems = [];
  state.mappingItemsRequestKey = "";
  state.mappingSelectedItemId = "";
  state.mappingCandidates = [];
  state.mappingHistory = [];
  els.mappingServiceStatus.textContent = "Сервис сопоставления еще не загружен.";
  els.mappingItemRows.replaceChildren();
  els.mappingSelectedCard.textContent = "Выберите строку товара.";
  els.mappingCandidateList.replaceChildren();
  els.mappingHistoryList.replaceChildren();
  els.mappingOnecResults.replaceChildren();
  if (options.hide) {
    els.mappingServicePanel.hidden = true;
  }
}

function selectedMappingItem() {
  return state.mappingItems.find((item) => item.id === state.mappingSelectedItemId);
}

function mappingItemKey(item) {
  if (!item) {
    return "-";
  }
  return (
    item.nmId ||
    item.productId ||
    item.offerId ||
    item.ozonSku ||
    item.vendorCode ||
    item.barcode ||
    "-"
  );
}

function marketplaceLabel(value) {
  if (value === "wb") {
    return "WB";
  }
  if (value === "ozon") {
    return "Ozon";
  }
  return value || "-";
}

function mappingStatusLabel(value) {
  const labels = {
    matched: "Сопоставлено",
    needs_review: "Нужна проверка",
    ambiguous: "Несколько вариантов 1С",
    missing: "Нет связи",
    excluded: "Исключено",
  };
  return labels[normalize(value)] || value || "-";
}

function mappingStatusHint(value) {
  const labels = {
    ambiguous:
      "Нашлось несколько товаров 1C. Строка останется в очереди, пока аналитик не выберет вариант.",
    needs_review:
      "Есть слабый или неоднозначный кандидат, поэтому решение остается за аналитиком.",
    missing:
      "Готовой связи нет. Найдите товар 1C вручную или оставьте строку в очереди.",
  };
  return labels[normalize(value)] || "";
}

function mappingCurrentMethodLabel(value) {
  const labels = {
    mapping_service_auto_barcode: "Автоматически по штрихкоду 1С",
    imported_mapping_file: "Принято из файла",
    manual_search: "Сопоставлено вручную",
  };
  return labels[normalize(value)] || "Сопоставлено вручную";
}

function mappingItemNeedsAnalyst(value) {
  return ["needs_review", "ambiguous", "missing"].includes(normalize(value));
}

function mappingCandidateMethodLabel(value) {
  const labels = {
    barcode: "Совпадение по штрихкоду",
    vendor_article: "Совпадение по артикулу",
    imported_mapping_file: "Связь из загруженного файла",
  };
  return labels[normalize(value)] || value || "Способ не указан";
}

function mappingCandidateSourceLabel(value) {
  const labels = {
    auto: "найдено системой",
    import: "загружено из файла",
    manual: "добавлено вручную",
  };
  return labels[normalize(value)] || value || "источник не указан";
}

function mappingActionLabel(value) {
  const labels = {
    accept: "Принято",
    auto_accept: "Автоматически принято по штрихкоду 1С",
    reject: "Отклонено",
    revoke: "Отозвано",
    exclude: "Исключено",
    rebuild_candidates: "Кандидаты перестроены",
    import_candidates: "Кандидаты импортированы",
  };
  return labels[normalize(value)] || value || "-";
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
    const pinnedOzonDraft =
      normalize(state.summary?.marketplace) === "ozon" && state.reportId;
    const endpoint = pinnedOzonDraft
      ? `/api/reports/${encodeURIComponent(state.reportId)}/ozon-diagnostics`
      : `/api/clients/${encodeURIComponent(clientId)}/ozon-diagnostics`;
    diagnostics = await api(`${endpoint}?${params}`);
  } catch (error) {
    if (!isCurrentClientLoad(context) || params !== state.ozonDiagnosticsParams) {
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
  if (normalize(state.summary?.marketplace) === "ozon" && state.reportId) {
    const params = ozonDiagnosticsExportParams();
    els.ozonExcelLink.href = `/api/reports/${encodeURIComponent(
      state.reportId,
    )}/export.xlsx${params ? `?${params}` : ""}`;
  } else {
    const params = ozonDiagnosticsExportParams();
    els.ozonExcelLink.href =
      `/api/clients/${encodeURIComponent(clientId)}/ozon-diagnostics/export.xlsx` +
      (params ? `?${params}` : "");
  }
}

function updateReportBuildButton(refresh = state.latestSourceRefresh) {
  if (!els.reportBuildButton) {
    return;
  }
  const isStaff = isStaffUser();
  const reportId = state.reportId || "";
  els.reportBuildButton.hidden = !state.clientId || (!isStaff && !reportId);
  els.reportBuildButton.disabled = false;
  els.reportBuildButton.classList.remove("is-warning", "is-busy");
  if (!isStaff) {
    els.reportBuildButton.textContent = "Скачать отчёт";
    els.reportBuildButton.dataset.tooltip =
      "Скачать текущий опубликованный Excel-отчёт.";
    els.reportBuildButton.disabled = !reportId;
    return;
  }
  els.reportBuildButton.textContent = "Сформировать отчёт";
  els.reportBuildButton.dataset.tooltip =
    "Открыть мастер формирования отчета и выбрать нужные настройки.";
  if (isActiveSourceRefresh(refresh)) {
    els.reportBuildButton.textContent =
      normalize(refresh?.mode) === "ozon-only"
        ? "Диагностика выполняется"
        : sourceRefreshCreatesReport(refresh?.mode)
          ? "Отчёт формируется"
          : "Данные обновляются";
    els.reportBuildButton.dataset.tooltip = excelBusyTooltip(refresh);
    els.reportBuildButton.classList.add("is-busy");
    return;
  }
  if (excelNeedsReportRebuild(refresh)) {
    els.reportBuildButton.dataset.tooltip =
      "Источники свежее текущего отчета. Откройте мастер и сформируйте новый.";
    els.reportBuildButton.classList.add("is-warning");
  }
}

function reportFreshnessSubtitle(meta, refresh) {
  const parts = [];
  const generatedAt = meta.generatedAt || formatDateTime(meta.generatedAtIso);
  if (generatedAt) {
    parts.push(`Отчет собран: ${generatedAt}`);
  }
  if (meta.sourceCoverage) {
    parts.push(`Данные в отчете: ${meta.sourceCoverage}`);
  } else if (meta.reportPeriod || meta.period) {
    parts.push(`Период отчета: ${meta.reportPeriod || meta.period}`);
  }
  if (refresh?.periodStart || refresh?.periodEnd) {
    parts.push(
      `Последнее обновление данных: ${sourcePeriodText(refresh)} (${sourceStatusText(refresh.status)})`,
    );
  }
  const mappingAutoSync = refresh?.mappingAutoSync;
  if (mappingAutoSync) {
    els.sourceRefreshStatus.append(
      sourceRefreshStatusLine(
        "Сопоставление 1С",
        `авто: ${mappingAutoSync.autoAccepted || 0}; вручную: ${mappingAutoSync.remainingReview || 0}; конфликты: ${mappingAutoSync.currentMappingConflictCount || 0}`,
      ),
    );
  }
  return parts.join(" · ");
}

function excelBusyTooltip(refresh) {
  const status = normalize(refresh?.status);
  const mode = normalize(refresh?.mode);
  if (status === "rebuilding" || mode === "full") {
    return "Идет сборка нового Excel. Откройте статус обновления.";
  }
  return "Идет обновление источников. Откройте статус обновления данных.";
}

function excelNeedsReportRebuild(refresh) {
  if (!refresh || !state.reportId || !isStaffUser()) {
    return false;
  }
  const status = normalize(refresh.status);
  if (!EXCEL_REBUILD_SOURCE_REFRESH_STATUSES.has(status)) {
    return false;
  }
  const newReportId = refresh.newReportRunId || "";
  if (newReportId && newReportId !== state.reportId) {
    return false;
  }
  if (reportCoversRefresh(refresh)) {
    return false;
  }
  const refreshTime = timestampMs(refresh.finishedAt);
  const reportTime = timestampMs((state.summary || {}).meta?.generatedAtIso);
  return refreshTime > 0 && reportTime > 0 && refreshTime > reportTime;
}

function reportCoversRefresh(refresh) {
  const meta = (state.summary || {}).meta || {};
  const coverageStart = String(meta.sourceCoverageStart || "");
  const coverageEnd = String(meta.sourceCoverageEnd || "");
  const refreshStart = String(refresh?.periodStart || "");
  const refreshEnd = String(refresh?.periodEnd || "");
  if (!coverageEnd || !refreshEnd) {
    return false;
  }
  const startsCovered =
    !coverageStart || !refreshStart || refreshStart >= coverageStart;
  return startsCovered && refreshEnd <= coverageEnd;
}

function timestampMs(value) {
  if (!value) {
    return 0;
  }
  const date = new Date(value);
  const time = date.getTime();
  return Number.isNaN(time) ? 0 : time;
}

function sourceRefreshCreatesReport(mode) {
  return ["full", "weekly", "onec-only"].includes(normalize(mode));
}

function sourceRefreshAppearsStalled(refresh) {
  if (!refresh?.isStale) {
    return false;
  }
  const recentActivityAt = timestampMs(refresh?.progress?.lastActivityAt);
  return !recentActivityAt || Date.now() - recentActivityAt > 5 * 60 * 1000;
}

function renderSourceRefreshControl(refresh, latestAttempt = null) {
  els.sourceRefreshPanel.hidden = false;
  updateReportBuildButton(refresh);
  renderReportWizardStatus(refresh);
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
  const appearsStalled = sourceRefreshAppearsStalled(refresh);
  const createsReport = sourceRefreshCreatesReport(refresh.mode);
  const isOzonOnly = normalize(refresh.mode) === "ozon-only";
  els.sourceRefreshStatus.replaceChildren(
    sourceRefreshStatusLine(
      "Статус",
      appearsStalled
        ? "Нет подтверждённой активности"
        : sourceStatusText(refresh.status),
    ),
    sourceRefreshStatusLine("Режим", sourceRefreshModeText(refresh.mode)),
    sourceRefreshStatusLine("Период", sourcePeriodText(refresh)),
    sourceRefreshStatusLine("Прогресс", sourceRefreshProgressText(refresh.progress)),
    sourceRefreshStatusLine(
      isOzonOnly ? "Диагностика" : createsReport ? "Отчёт" : "Обновление данных",
      refresh.newReportRunId ||
        (isOzonOnly
          ? active
            ? "готовится"
            : "готова без отчёта"
          : !createsReport
            ? active
              ? "идёт"
              : "завершено"
          : active
            ? "создаётся"
            : "не создан"),
    ),
  );
  if (excelNeedsReportRebuild(refresh)) {
    els.sourceRefreshStatus.append(
      sourceRefreshStatusLine(
        "Excel",
        "Источники свежее отчета. Запустите полное обновление, чтобы скачать актуальный файл.",
      ),
    );
  }
  const collections = asArray(refresh.collections);
  const nodes = [];
  if (
    latestAttempt &&
    latestAttempt.id !== refresh.id &&
    normalize(latestAttempt.status) === "blocked_active_refresh"
  ) {
    nodes.push(sourceRefreshBlockedAttemptMessage(latestAttempt, refresh));
  }
  nodes.push(sourceRefreshCompactMessage(refresh));
  if (collections.length) {
    nodes.push(...collections.map(sourceRefreshCollectionChip));
  } else {
    nodes.push(sourceRefreshEmptyDetailsNode(refresh));
  }
  els.sourceRefreshCollections.replaceChildren(...nodes);
  setSourceRefreshActiveLock(active);
  scheduleSourceRefreshPolling(refresh);
}

function sourceRefreshProgressText(progress) {
  if (!progress) {
    return "Ожидаем данные";
  }
  const parts = [progress.currentSource || "Обновление"];
  const pages = Number(progress.pagesLoaded || 0);
  const rows = Number(progress.rowsLoaded || 0);
  const bytes = Number(progress.bytesWritten || 0);
  const completedAccounts = Number(progress.wbAccountsCompleted || 0);
  const totalAccounts = Number(progress.wbAccountsTotal || 0);
  if (pages) {
    parts.push(`${number(pages)} страниц WB`);
  }
  if (rows) {
    parts.push(`${number(rows)} строк`);
  }
  if (bytes) {
    parts.push(formatDataSize(bytes));
  }
  if (totalAccounts) {
    parts.push(`${number(completedAccounts)} из ${number(totalAccounts)} кабинетов завершено`);
  }
  return parts.join(" · ");
}

function formatDataSize(bytes) {
  const value = Math.max(0, Number(bytes || 0));
  if (value >= 1024 ** 3) {
    return `${(value / 1024 ** 3).toFixed(1)} ГБ`;
  }
  if (value >= 1024 ** 2) {
    return `${Math.round(value / 1024 ** 2)} МБ`;
  }
  if (value >= 1024) {
    return `${Math.round(value / 1024)} КБ`;
  }
  return `${number(value)} Б`;
}

function sourceRefreshBlockedAttemptMessage(attempt, activeRun) {
  const node = document.createElement("div");
  node.className = "source-refresh-compact-status is-warning";
  const title = document.createElement("strong");
  title.textContent = `${sourceRefreshModeText(attempt.mode)} не запущен.`;
  const meta = document.createElement("span");
  meta.textContent = `Продолжается ${sourceRefreshModeText(activeRun.mode)}; ниже показаны его реальные коллекции и прогресс.`;
  node.append(title, meta);
  return node;
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
  const createsReport = sourceRefreshCreatesReport(refresh?.mode);
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
      label: isOzonOnly ? "Диагностика" : createsReport ? "Отчёт" : "Готово",
      state: reportCreated
        ? "done"
        : !createsReport && !isActive && status === "needs_review"
          ? "done"
          : refreshCompleted
            ? createsReport
              ? "active"
              : "done"
            : "pending",
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
  const appearsStalled = sourceRefreshAppearsStalled(refresh);
  title.textContent = appearsStalled
    ? "Нет подтверждённой активности фонового обновления."
    : normalize(refresh.status) === "dry_run_ready"
      ? "Готово к полному обновлению. Отчет еще не создан."
      : localizedOperationalMessage(
          refresh.safeMessage || sourceStatusHint(refresh.status),
        );
  const meta = document.createElement("span");
  meta.textContent = appearsStalled
    ? "Не запускайте ещё одно обновление: сначала проверьте текущий процесс. Уже сохранённые снимки останутся на месте."
    : refresh.failureCode?.startsWith("worker_")
      ? "Повторите обновление: новый run продолжит совместимый checkpoint автоматически."
      : sourceRefreshAdvice(refresh.status);
  node.append(title, meta);
  return node;
}

function sourceRefreshCollectionChip(item) {
  const chip = document.createElement("div");
  chip.className = `source-refresh-chip ${sourceStatusTone(item.status)}`;
  const title = document.createElement("strong");
  title.textContent = sourceLabelText(item);
  const meta = document.createElement("span");
  const requirement = item.required
    ? "обязателен для расчета"
    : item.publicationRequired
      ? "обязателен для публикации"
      : "дополнительный";
  meta.textContent = [
    sourceStatusText(item.status),
    requirement,
    `${number(item.rowCount || 0)} строк`,
    localizedOperationalMessage(item.payload?.message || ""),
  ].filter(Boolean).join(" · ");
  chip.append(title, meta);
  asArray(item.payload?.companyDiagnostics).forEach((diagnostic) => {
    const detail = document.createElement("span");
    const missing = asArray(diagnostic.missingFields)
      .map(taxSourceFieldLabel)
      .join(", ");
    detail.textContent = [
      diagnostic.companyLabel || diagnostic.organizationId || "Организация 1С",
      diagnostic.message || "",
      missing ? `Не опубликовано: ${missing}` : "",
    ].filter(Boolean).join(" — ");
    chip.append(detail);
  });
  return chip;
}

function taxSourceFieldLabel(value) {
  return {
    taxSystem: "система налогообложения",
    vatRate: "ставка НДС",
    vatMode: "НДС внутри или сверху",
    vatDeductionMode: "право на вычет НДС",
    revenueTaxRate: "ставка налога УСН",
  }[value] || value;
}

function renderOzonPreview(refresh, diagnostics = state.latestOzonDiagnostics) {
  if (
    !els.ozonPreviewSummary ||
    !els.ozonPreviewCount ||
    !els.ozonPreviewGrid ||
    !els.ozonVitrineStatus ||
    !els.ozonIssueList ||
    !els.ozonIssueEmpty ||
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
  const mappingCheckRows = asArray(ozonMapping.rows);
  const mappingCheckSummary = ozonMapping.summary || {};
  const blockingIssues = Number(issues.blockingCount || 0);
  const reviewIssues = Number(issues.reviewCount || 0);
  const issueCount = blockingIssues + reviewIssues;
  const onecLoadedLabel = onecSummary.required
    ? `${number(onecSummary.loaded || 0)} / ${number(onecSummary.required || 0)}`
    : number(onecSummary.loaded || 0);

  if (diagnostics?.latestRun) {
    const calculationText = `Расчетный снимок: ${sourceStatusText(
      diagnostics.latestRun.status,
    )}, ${sourcePeriodText(diagnostics.latestRun)}.`;
    const attempt = diagnostics.latestAttempt;
    els.ozonPreviewSummary.textContent = attempt
      ? `${calculationText} Последняя попытка: ${sourceStatusText(
          attempt.status,
        )}${attempt.dryRun ? " (проверка)" : ""}.`
      : calculationText;
  } else if (diagnostics?.message) {
    els.ozonPreviewSummary.textContent = diagnostics.message;
  } else {
    els.ozonPreviewSummary.textContent = refresh
      ? `Последнее обновление данных: ${sourceStatusText(refresh.status)}, ${sourcePeriodText(refresh)}.`
      : "Обновление данных ещё не запускалось для выбранного клиента.";
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
    "Служебная витрина Ozon: расчет можно читать консультанту, клиентский отчет не публикуется.";
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
  const showDiagnosticCalculation = !shouldUseOzonWorkingView();
  setOzonDiagnosticCalculationSectionsVisible(showDiagnosticCalculation);
  renderOzonIssues(issues);
  if (showDiagnosticCalculation) {
    renderOzonUnitEconomics(
      diagnostics?.ozonMart || diagnostics?.unitRows || {},
      { realizationRows: realizationSummary.rowCount || 0 },
    );
  }
  renderOzonBuyouts(buyoutSummary);
  els.ozonPreviewEmpty.hidden = visibleCollections.length > 0 || Boolean(diagnostics);
  els.ozonPreviewRows.replaceChildren(
    ...visibleCollections.map((item) => ozonPreviewRowNode(item)),
  );
  els.ozonMappingEmpty.hidden = mappingCheckRows.length > 0;
  els.ozonMappingEmpty.textContent =
    ozonMapping.message || "Нужен каталог Ozon: товары, артикул продавца, SKU и штрихкоды.";
  els.ozonMappingRows.replaceChildren(
    ...mappingCheckRows.map((item) => ozonMappingRowNode(item)),
  );
}

function setOzonDiagnosticCalculationSectionsVisible(visible) {
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
  return "финансовые данные API продавца";
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
  const profitAmount = item.profitBeforeTax ?? item.profitAmount ?? item.profit;
  const margin = item.marginBeforeTax ?? item.margin;
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
      value: ozonUnitProfitMarginText(profitAmount, margin, item.expenseStatus),
      className: `numeric ${metricToneForAmount(profitAmount)}`,
    },
    { value: ozonUnitOnecText(item), className: "text-wide" },
    {
      value: ozonUnitStatusText(item.qualityStatus),
      className: ozonUnitStatusTone(item.qualityStatus),
    },
    { value: ozonUnitProblemText(item), className: "text-wide" },
  ]);
  if (
    ["ambiguous_mapping", "missing_mapping"].includes(
      normalize(item.qualityStatus),
    )
  ) {
    appendOzonMappingQueueButton(row.lastElementChild, item);
  }
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
    ambiguous_mapping: "несколько вариантов 1С",
    missing_cost: "нет себестоимости",
    missing_1c_organization: "не выбрана организация 1С",
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
  if (item.qualityStatus === "missing_1c_organization") {
    return "Выберите организацию 1C.";
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
  const costQuality = ozonUnitCostQualityText(item);
  const parts = [];
  if (reason) {
    parts.push(reason);
  }
  if (costQuality) {
    parts.push(costQuality);
  }
  if (action && action !== "Действие не требуется.") {
    parts.push(action);
  }
  return parts.join(" ") || action;
}

function ozonUnitCostQualityText(item = {}) {
  const reason = item.costQualityReason || "";
  if (reason === "insufficient_history") {
    return "Недостаточно двух закрытых месяцев для сравнения стоимости.";
  }
  if (reason === "unit_cost_outlier") {
    return `Стоимость отличается от истории; влияние ${optionalMoney(
      item.estimatedCostImpact,
    )}.`;
  }
  if (reason === "nonpositive_unit_cost") {
    return "Стоимость 1C неположительная; прибыль месяца заблокирована.";
  }
  if (reason === "missing_cost") {
    return "Себестоимость отсутствует; прибыль месяца заблокирована.";
  }
  if (reason === "missing_1c_organization") {
    return "Организация 1C не выбрана; прибыль месяца заблокирована.";
  }
  return "";
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
    const suffix = ozonUnitExpenseSuffix(item);
    return `${optionalMoney(item.ozonPartnerServices)}${suffix}`;
  }
  if (first == null && second == null) {
    if (item.expenseStatus === "partial_source") {
      return "не распределено по SKU";
    }
    return "не рассчитано";
  }
  const suffix = ozonUnitExpenseSuffix(item);
  return `${optionalMoney(first ?? 0)} / ${optionalMoney(second ?? 0)}${suffix}`;
}

function ozonUnitExpenseSuffix(item = {}) {
  const status = normalize(item.expenseStatus);
  if (status === "allocated_period_expense") {
    return " · по выручке";
  }
  if (status === "mixed_sku_and_period_unattributed") {
    return " · SKU + остаток";
  }
  if (status === "loaded" && item.expenseBasis === "ozon_realization_sku_fields") {
    return " · по SKU";
  }
  return "";
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
  if (els.ozonIssuesPanel) {
    els.ozonIssuesPanel.hidden = false;
  }
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
    sourceLabelText(item),
    sourceStatusText(item.status),
    number(item.rowCount || 0),
    endpoint || "служебный файл загрузки",
    reportCode || "-",
    localizedOperationalMessage(
      error || sourceStatusHint(item.status, item.required !== false),
    ),
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
  if (["ambiguous", "missing"].includes(normalize(item.status))) {
    appendOzonMappingQueueButton(row.lastElementChild, item);
  }
  return row;
}

function appendOzonMappingQueueButton(cell, item) {
  if (!cell) {
    return;
  }
  const button = document.createElement("button");
  button.type = "button";
  button.className = "table-inline-action secondary-button";
  button.textContent = "Открыть в очереди";
  button.title = "Перейти к этой позиции в очереди аналитика без автоматического решения";
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    openMappingAnalystQueue(item);
  });
  cell.classList.add("table-action-cell");
  cell.append(button);
}

async function openMappingAnalystQueue(item) {
  const query =
    item.offerId || item.sku || item.productId || item.barcode || item.productName || "";
  const opened = await openMappingWidget({
    marketplace: "ozon",
    status: "review",
    search: String(query),
    focus: false,
  });
  if (!opened) {
    return;
  }
  els.mappingServiceStatus.textContent = `Ищем ${query || "позицию"} в очереди аналитика...`;
  const context = currentClientLoadContext();
  if (!isCurrentClientLoad(context)) {
    return;
  }
  const target = state.mappingItems.find((candidate) =>
    mappingItemMatchesOzonIssue(candidate, item),
  );
  if (target) {
    await selectMappingItem(target.id, context);
    return;
  }
  els.mappingServiceStatus.textContent =
    `Позиция ${query || "Ozon"} пока не найдена в очереди. Перестройте кандидатов после обновления источников.`;
}

function mappingItemMatchesOzonIssue(candidate, issue) {
  const candidateKeys = [
    candidate.offerId,
    candidate.ozonSku,
    candidate.productId,
    candidate.barcode,
    candidate.vendorCode,
  ]
    .map((value) => normalize(value))
    .filter(Boolean);
  return [issue.offerId, issue.sku, issue.productId, issue.barcode]
    .map((value) => normalize(value))
    .filter(Boolean)
    .some((value) => candidateKeys.includes(value));
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
    ambiguous: "несколько вариантов",
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
    offer_id: "артикул продавца → артикул 1C",
    offer_id_code: "артикул продавца → код 1C",
    barcode: "штрихкод → штрихкод 1C",
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
    ? "Последнее обновление данных есть, но деталей по источникам пока нет."
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
  state.latestSourceRefreshAttempt = null;
  state.activeSourceRefresh = null;
  state.latestOzonDiagnostics = null;
  updateReportBuildButton(null);
  renderReportWizardStatus(null);
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

async function runClientSourceRefresh({
  dryRun,
  mode = "full",
  periodStart = "",
  periodEnd = "",
  origin = "integrations",
}) {
  const context = currentClientLoadContext();
  const clientId = context.clientId;
  if (!clientId) {
    return;
  }
  setSourceRefreshButtonsBusy(true);
  els.sourceRefreshStatus.textContent = sourceRefreshStartText({ dryRun, mode });
  renderReportWizardStatus({
    status: "queued",
    mode,
    dryRun: Boolean(dryRun),
    periodStart: periodStart || null,
    periodEnd: periodEnd || null,
  });
  try {
    const payload = await api(
      `/api/clients/${encodeURIComponent(clientId)}/source-refresh`,
      {
        method: "POST",
        body: JSON.stringify({
          mode,
          dry_run: Boolean(dryRun),
          reason: sourceRefreshReason({ dryRun, mode, origin }),
          period_start: periodStart || null,
          period_end: periodEnd || null,
        }),
      },
    );
    if (!isCurrentClientLoad(context)) {
      return null;
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
    return refresh;
  } catch (error) {
    if (!isCurrentClientLoad(context)) {
      return null;
    }
    const safeMessage = integrationErrorMessage(
      error,
      dryRun
        ? "Не удалось проверить готовность обновления источников."
        : mode === "ozon-only"
          ? "Не удалось загрузить служебную витрину Ozon + 1C."
        : "Не удалось запустить полное обновление источников.",
    );
    els.sourceRefreshStatus.textContent = safeMessage;
    els.reportWizardStatus.className = "report-wizard-status is-blocked";
    els.reportWizardStatus.textContent = safeMessage;
    return null;
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
    return "Загружаем служебную витрину Ozon + 1C без обязательного WB. Клиентский отчет не публикуется.";
  }
  return "Запускаем полное обновление. Это может занять время.";
}

function sourceRefreshReason({ dryRun, mode, origin = "integrations" }) {
  const location = origin === "wizard" ? "мастера формирования отчета" : "виджета интеграций";
  if (dryRun) {
    return `Проверка готовности из ${location}`;
  }
  if (mode === "ozon-only") {
    return `Ручная загрузка служебной витрины Ozon + 1C из ${location}`;
  }
  return `Ручное полное обновление из ${location}`;
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
        { providerBase: "wb_api", label: "API Wildberries" },
        { providerBase: "onec_readonly", label: "1С — только чтение" },
        { providerBase: "ozon_api", label: "API кабинета продавца Ozon" },
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
    : "После создания карточка откроется ниже для настройки доступа только для чтения.";
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
  if (item.runtimeCheckedAt) {
    details.append(
      detailItem("Автопроверка", formatDateTime(item.runtimeCheckedAt)),
    );
  }
  if (item.lastCheck && item.lastCheck.message) {
    details.append(detailItem("Результат", item.lastCheck.message));
  }
  if (item.runtimeMessage) {
    details.append(detailItem("Текущее состояние", item.runtimeMessage));
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
      label: "Идентификатор клиента",
      type: "text",
      placeholder: "Идентификатор клиента Ozon",
      autocomplete: "off",
    }),
    integrationSecretField({
      name: "ozon_api_key",
      label: "API-ключ",
      type: "password",
      placeholder: item.secretHint ? "Новый API-ключ" : "API-ключ Ozon",
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
      missing.push("идентификатор клиента");
    }
    if (!apiKey) {
      missing.push("API-ключ");
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
    label: "API Wildberries",
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
      label: `API Wildberries · ${cabinet.label || "кабинет"}`,
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
  const effectiveStatus = integrationEffectiveStatus(item);
  if (isOptionalIntegration(item)) {
    return "Опционально";
  }
  if (effectiveStatus === "disabled") {
    return "Отключено";
  }
  if (effectiveStatus === "check_failed") {
    return isOnecIntegrationProvider(item.providerBase || item.provider)
      ? "1С недоступна"
      : "Нужна проверка";
  }
  if (integrationRuntimeIsNewer(item) && item.runtimeCheckedAt) {
    return `Автопроверка ${formatShortDateTime(item.runtimeCheckedAt)}`;
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
  if (
    !item.storageMode &&
    !item.lastCheck?.message &&
    !item.lastCheckedAt &&
    !item.runtimeCheckedAt
  ) {
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
  if (item.runtimeCheckedAt) {
    list.append(detailItem("Автопроверка", formatDateTime(item.runtimeCheckedAt)));
  }
  if (item.runtimeMessage) {
    list.append(detailItem("Текущее состояние", item.runtimeMessage));
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
    parts.push("Кабинет продавца Ozon — только чтение");
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
    setIntegrationFeedback(form, "Проверяем сохранённое подключение только для чтения...", "info");
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
  if (integrationEffectiveStatus(item) === "check_failed") {
    const runtimeFailure = integrationRuntimeIsNewer(item) && item.runtimeMessage;
    return {
      type: "danger",
      text: runtimeFailure
        ? `Автопроверка не прошла: ${item.runtimeMessage}`
        : item.lastCheck?.message
          ? `Проверка не прошла: ${item.lastCheck.message}`
          : "Проверка не прошла. Проверьте ключ и права доступа.",
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
  if (item.storageMode === "hash_only") {
    return {
      type: "warning",
      text:
        "Ключ сохранён только как контрольная метка. Для автоматической проверки нужно зашифрованное хранение.",
    };
  }
  if (item.configured || item.secretHint) {
    const accessName = isOnecIntegrationProvider(item.providerBase || item.provider)
      ? "Доступ"
      : "Ключ";
    return {
      type: "success",
      text: `${accessName} сохранён. Теперь нажмите «Проверить», чтобы убедиться в доступе только для чтения.`,
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
        "Сохранено как контрольная метка. Секрет не показывается, но проверка подключения требует зашифрованного хранения.",
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
        : "Проверка прошла. Доступ только для чтения подтверждён.",
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
  const effectiveStatus = integrationEffectiveStatus(item);
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
  return labels[effectiveStatus] || effectiveStatus || "Не настроено";
}

function integrationStatusClass(item) {
  const effectiveStatus = integrationEffectiveStatus(item);
  if (effectiveStatus === "check_ok") {
    return "ok";
  }
  if (effectiveStatus === "check_failed") {
    return "danger";
  }
  if (effectiveStatus === "disabled") {
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

function integrationEffectiveStatus(item) {
  if (!item.runtimeStatus || !integrationRuntimeIsNewer(item)) {
    return item.status;
  }
  return item.runtimeStatus;
}

function integrationRuntimeIsNewer(item) {
  if (!item.runtimeStatus) {
    return false;
  }
  const runtimeTime = Date.parse(item.runtimeCheckedAt || "");
  const manualTime = Date.parse(item.lastCheckedAt || "");
  if (!Number.isFinite(runtimeTime)) {
    return !item.lastCheckedAt;
  }
  return !Number.isFinite(manualTime) || runtimeTime >= manualTime;
}

function storageModeText(storageMode) {
  return {
    encrypted: "зашифрованное хранение",
    hash_only: "контрольная метка, нужен повторный ввод",
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
  const financialFailure = financialCheckFailed(readiness);
  els.overviewTitle.textContent = financialFailure
    ? "Финансовая проверка не пройдена"
    : readinessHeadline(readiness.status);
  els.readinessLabel.textContent = financialFailure
    ? "Финансовая проверка не пройдена"
    : readiness.label || "Статус не рассчитан";
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
      title: "Подготовить отчёт для клиента",
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
      button: "Открыть отчёт для клиента",
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
      label: "Excel и отчёт для клиента",
      value: clientDraftReady ? "Артефакты готовы к работе" : "Нужен отчёт для клиента",
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
    ["Сопоставление", mapping],
    ["Сверка WB ↔ 1С", onecIssues],
    ["Неполный период", partialPeriod],
    ["Неполные источники", incomplete],
  ]);
}

function renderKpis(kpis, taxContext = {}, lostSalesCoverage = {}) {
  if (shouldRenderOzonAnalytics()) {
    renderOzonKpis(state.latestOzonDiagnostics);
    return;
  }
  setKpiHeading();
  const revenue = Number(kpis.revenueWithoutVat ?? kpis.revenue ?? 0);
  const revenueWithVat = Number(kpis.revenueWithVat ?? kpis.revenue ?? revenue);
  const cogs = numberOrNull(kpis.cogs);
  const costIssueRows = Number(kpis.costIssueRows || 0);
  const onecRevenueWithVat = numberOrNull(kpis.onecRevenueWithVat);
  const onecSalesQuantity = numberOrNull(kpis.onecSalesQuantity);
  const onecCogs = numberOrNull(kpis.onecCogs);
  const onecCostAdjustmentRows = Number(kpis.onecCostAdjustmentRows || 0);
  const wbMarketplacePnlExpenses = numberOrNull(
    kpis.wbMarketplacePnlExpenses,
  );
  const onecMarketplaceExpensesWithVat = numberOrNull(
    kpis.onecMarketplaceExpensesWithVat,
  );
  const marketplaceExpenseDeltaWithVat = numberOrNull(
    kpis.marketplaceExpenseDeltaWithVat,
  );
  const marketplaceExpenseStatus =
    kpis.marketplaceExpenseReconciliationStatus || "missing_source";
  const marketplaceExpenseIssueGroups = Number(
    kpis.marketplaceExpenseIssueGroups || 0,
  );
  const onecRevenueDocumentCount = Number(kpis.onecRevenueDocumentCount || 0);
  const onecRevenueCaption =
    onecRevenueWithVat === null
      ? "Нет подтверждённых проведённых документов 1С за выбранный период"
      : `По ${number(onecRevenueDocumentCount)} проведённым документам 1С за календарный период`;
  const wbDocumentRevenueWithVat = numberOrNull(kpis.wbDocumentRevenueWithVat);
  const wbCommissionerRevenueWithVat = numberOrNull(
    kpis.wbCommissionerRevenueWithVat,
  );
  const wbBuyoutRetailRevenueWithVat = numberOrNull(
    kpis.wbBuyoutRetailRevenueWithVat,
  );
  const commissionerRevenueDelta = numberOrNull(kpis.commissionerRevenueDelta);
  const buyoutPrimaryDocumentDelta = numberOrNull(
    kpis.buyoutPrimaryDocumentDelta,
  );
  const buyoutPrimaryDocumentStatus = String(
    kpis.buyoutPrimaryDocumentStatus || "not_loaded",
  );
  const buyoutUnverifiedPrimaryRows = Number(
    kpis.buyoutUnverifiedPrimaryRows || 0,
  );
  const accountingReconciliationDelta = numberOrNull(
    kpis.accountingReconciliationDelta,
  );
  const accountingReconciliationAmount = numberOrNull(
    kpis.accountingReconciliationOnecAmount,
  );
  const accountingReconciliationStatus =
    kpis.accountingReconciliationStatus || "Не рассчитано";
  const profitBeforeTax = numberOrNull(
    kpis.profitBeforeTax ?? kpis.profitManagement,
  );
  const profitAfterTax = numberOrNull(
    kpis.profitAfterTax ?? kpis.profitAfterIncomeTax ?? kpis.profit,
  );
  const returns = Number(kpis.returns || 0);
  const sales = Number(kpis.sales || 0);
  const lossRows = Number(kpis.lossRows || 0);
  const penaltyOnlyRows = Number(kpis.penaltyOnlyRows || 0);
  const lostContribution = numberOrNull(
    kpis.lostContributionMargin ?? kpis.lostSalesProfit,
  );
  const taxCalculated = taxContext.calculated === true;
  const lostSalesCalculated = lostSalesCoverage.calculated === true;
  const lostSalesPeriod = lostSalesCoveragePeriodText(lostSalesCoverage);
  const netSales = sales - returns;
  const returnRate = sales ? `${Math.round((returns / sales) * 1000) / 10}%` : "-";
  const revenuePerSale = sales ? revenue / sales : 0;
  const managementMargin = kpis.marginManagement;
  const margin =
    managementMargin === null || managementMargin === undefined
      ? "-"
      : `${Math.round(Number(managementMargin || 0) * 1000) / 10}%`;
  const taxSystem = normalize(taxContext.taxSystem);
  const isUsn = taxSystem.includes("усн") || taxSystem.includes("упрощ");
  const revenueTaxRate = Number(taxContext.revenueTaxRate || 0) * 100;
  const revenueTaxLabel = isUsn
    ? `Налог УСН${revenueTaxRate ? ` ${number(revenueTaxRate)}%` : ""}`
    : "Налог с выручки";
  const managementInputVat = kpis.inputVatMode === "management_assumption";
  const inputVatLabel = managementInputVat
    ? "Расчётный входящий НДС"
    : "Входящий НДС";
  const vatPayableLabel = managementInputVat
    ? "Расчётный НДС к уплате"
    : "НДС к уплате";
  els.onecKpiSection.hidden = false;
  const controlMetrics = [
    [
      "Единый стандарт WB ↔ 1С",
      accountingReconciliationDelta === null
        ? "Не рассчитано"
        : signedMoney(accountingReconciliationDelta),
      accountingReconciliationDelta === null
        ? accountingReconciliationStatus
        : `Календарь 1С; сумма ${optionalMoney(accountingReconciliationAmount)}. По выкупам — первичка WB.`,
      accountingReconciliationDelta !== null &&
      Math.abs(accountingReconciliationDelta) <= 1
        ? "ok"
        : "warning",
      "Единый стандарт использует календарную дату проведения 1С. Отчёт комиссионера сравнивается с retailAmountSum WB, а выкуп — с полем «Сумма выкупа» первичного уведомления WB. Без сохранённой первички выкуп не считается проверенным.",
    ],
    [
      "Выручка 1С с НДС",
      onecRevenueWithVat === null ? "Не рассчитано" : money(onecRevenueWithVat),
      onecRevenueWithVat === null
        ? onecRevenueCaption
        : `${onecRevenueCaption}: комиссионер ${optionalMoney(
            kpis.onecCommissionerRevenueWithVat,
          )} + выкупы ${optionalMoney(
            kpis.onecBuyoutRevenueWithVat,
          )} + корректировки ${optionalMoney(kpis.onecOtherRevenueWithVat)}`,
      onecRevenueWithVat === null ? "warning" : "ok",
      "Σ поля «Сумма» проведённых документов 1С за календарный период: ОтчетКомиссионера, РасходнаяНакладная по выкупам и отдельные корректировки. Дата — дата проведения документа в 1С.",
    ],
    [
      "Количество продаж 1С, шт",
      onecSalesQuantity === null ? "Не рассчитано" : number(onecSalesQuantity),
      onecSalesQuantity === null
        ? "Нет сохранённых количеств документов 1С"
        : `Комиссионер нетто ${number(
            kpis.onecCommissionerQuantity || 0,
          )} + выкупы ${number(kpis.onecBuyoutQuantity || 0)} + корректировки ${number(
            kpis.onecOtherQuantity || 0,
          )}`,
      onecSalesQuantity === null ? "warning" : "ok",
      "Календарное количество 1С: чистое количество ОтчетКомиссионера + положительное количество РасходнаяНакладная по выкупу + отдельные количественные корректировки. Дата — фактическая дата проведения в 1С.",
    ],
    [
      "Себестоимость продаж 1С",
      onecCogs === null ? "Не рассчитано" : money(onecCogs),
      onecCogs === null
        ? "Текущий отчёт не содержит себестоимость документов 1С"
        : `Комиссионер ${optionalMoney(
            kpis.onecCommissionerCogs,
          )} + выкупы ${optionalMoney(kpis.onecBuyoutCogs)} + корректировки ${optionalMoney(
            kpis.onecOtherCogs,
          )}${
            onecCostAdjustmentRows
              ? ` · ${number(onecCostAdjustmentRows)} строк закрытия месяца`
              : ""
          }`,
      onecCogs === null ? "warning" : "ok",
      "Прямая сумма поля «Себестоимость» регистра Продажи 1С за календарный период. Включает ОтчетКомиссионера, РасходнаяНакладная по выкупам и стоимостные корректировки ЗакрытиеМесяца.",
      openCogsReconciliationWidget,
    ],
    [
      "Услуги WB по документам 1С",
      onecMarketplaceExpensesWithVat === null
        ? "Не загружено"
        : money(onecMarketplaceExpensesWithVat),
      onecMarketplaceExpensesWithVat === null
        ? marketplaceExpenseStatusLabel(marketplaceExpenseStatus)
        : `Без НДС ${optionalMoney(
            kpis.onecMarketplaceExpensesWithoutVat,
          )} + НДС ${optionalMoney(kpis.onecMarketplaceVat)}`,
      onecMarketplaceExpensesWithVat === null ? "warning" : "info",
      "Σ проведённых документов услуг WB в 1С. Карточка показывает сумму с НДС; расшифровка отдельно показывает базу без НДС и НДС.",
      openMarketplaceExpenseReconciliationWidget,
    ],
    [
      "Сверка расходов WB ↔ 1С",
      marketplaceExpenseDeltaWithVat === null
        ? marketplaceExpenseStatusLabel(marketplaceExpenseStatus)
        : signedMoney(marketplaceExpenseDeltaWithVat),
      marketplaceExpenseDeltaWithVat === null
        ? "Дельта не подменяется нулём"
        : `1С − WB · проблемных групп ${number(
            marketplaceExpenseIssueGroups,
          )}`,
      marketplaceExpenseStatus === "matched" ? "ok" : "warning",
      "Сопоставимая документная сверка с НДС. Статус «Сверено» требует дельту не более 1 ₽ отдельно в каждой контрольной группе.",
      openMarketplaceExpenseReconciliationWidget,
    ],
    [
      "Выручка WB по документам, с НДС",
      wbDocumentRevenueWithVat === null
        ? "Не рассчитано"
        : money(wbDocumentRevenueWithVat),
      wbDocumentRevenueWithVat === null
        ? "Нет подтверждённых документов для сверки"
        : `Комиссионер ${optionalMoney(
            wbCommissionerRevenueWithVat,
          )} + выкупы ${optionalMoney(wbBuyoutRetailRevenueWithVat)}`,
      wbDocumentRevenueWithVat === null ? "warning" : "info",
      "Выручка WB по документам = retailAmountSum отчётов комиссионера WB + retailAmountSum уведомлений о выкупе WB. Это полная формула WB-выручки с НДС в документной сверке.",
    ],
    [
      "Сверка комиссионера WB ↔ 1С",
      commissionerRevenueDelta === null
        ? "Не рассчитано"
        : signedMoney(commissionerRevenueDelta),
      "1С − WB; должна быть 0 ₽ для одинаковых недель продаж",
      commissionerRevenueDelta !== null && Math.abs(commissionerRevenueDelta) <= 1
        ? "ok"
        : "warning",
      "Σ «ОтчетКомиссионера» 1С − Σ retailAmountSum отчётов комиссионера WB по тем же неделям продаж. Это единственная денежная часть, которая сравнивается напрямую.",
    ],
    [
      "Выкупы: первичка WB ↔ 1С",
      buyoutPrimaryDocumentStatus === "verified" &&
      buyoutPrimaryDocumentDelta !== null
        ? signedMoney(buyoutPrimaryDocumentDelta)
        : "Не проверено",
      buyoutPrimaryDocumentStatus === "verified"
        ? "Сумма выкупа из первички WB − накладная 1С"
        : `Юнит-экономика рассчитана. Документальная сверка выкупов не завершена${
            buyoutUnverifiedPrimaryRows
              ? `: ${number(buyoutUnverifiedPrimaryRows)} документов без первички WB`
              : ""
          }.`,
      buyoutPrimaryDocumentStatus === "verified" &&
      Math.abs(Number(buyoutPrimaryDocumentDelta || 0)) <= 1
        ? "ok"
        : "warning",
      "Сопоставимая денежная проверка: поле «Сумма выкупа» из первичного уведомления WB − сумма расходной накладной 1С. retailAmountSum, forPaySum и bankPaymentSum являются другими денежными базами и не создают расхождение.",
      openBuyoutReconciliationWidget,
    ],
  ];
  const profitUsesRevenueWithoutVat = Boolean(kpis.pnlWithoutVat);
  const profitFormula = profitUsesRevenueWithoutVat
    ? "Выручка WB без НДС − себестоимость 1С без НДС − расходы WB без НДС. Налоги ещё не вычтены."
    : "Выручка WB с НДС − себестоимость 1С − расходы WB. Затем отдельно вычитаются исходящий НДС и налог с выручки по профилю 1С.";
  const marginFormula = profitUsesRevenueWithoutVat
    ? "Маржинальный доход до налогов ÷ выручка WB без НДС."
    : "Маржинальный доход до налогов ÷ выручка WB с НДС.";
  const unitMetrics = [
    [
      "Выручка WB по товарным строкам, с НДС",
      money(revenueWithVat),
      "База товарного P&L WB; может отличаться от документной сверки",
      "",
      "Σ выручки товарных строк финансовой детализации WB с НДС. Используется в товарном P&L, а не как сумма документов комиссионера и выкупов.",
    ],
    [
      "Выручка WB без НДС",
      money(revenue),
      profitUsesRevenueWithoutVat
        ? "База товарного P&L для применённого профиля"
        : "Справочная выручка после выделения исходящего НДС",
      "",
      "Выручка WB с НДС − исходящий НДС по строкам отчёта. Для legacy/УСН прибыль до налогов считается от выручки с НДС; для ОСНО — от сопоставимой базы без НДС.",
    ],
    [
      "Себестоимость товарного P&L WB",
      cogs === null ? "Не рассчитано" : money(cogs),
      costIssueRows
        ? `${number(costIssueRows)} строк требуют проверки себестоимости`
        : "Стоимость единицы 1С × товарное количество WB",
      costIssueRows ? "warning" : "",
      "Себестоимость товарного P&L по неделям продаж WB. reportType=1 использует стоимость ОтчетКомиссионера, reportType=2 — РасходнаяНакладная по выкупу. Этот показатель может отличаться от календарного итога 1С.",
      openCogsReconciliationWidget,
    ],
    [
      "Расходы WB в товарном P&L",
      wbMarketplacePnlExpenses === null
        ? "Не рассчитано"
        : money(wbMarketplacePnlExpenses),
      "Комиссия, логистика, хранение, приёмка, продвижение, штрафы и эквайринг",
      "",
      "Расходы WB в базе применённого налогового профиля. Для документной сверки с 1С используется отдельная сумма с НДС.",
      openMarketplaceExpenseReconciliationWidget,
    ],
    [
      "Маржинальный доход до налогов",
      profitBeforeTax === null ? "Не рассчитано" : money(profitBeforeTax),
      "",
      "",
      profitFormula,
    ],
    [
      "Маржа до налогов",
      margin,
      "",
      "",
      marginFormula,
    ],
    [
      "Исходящий НДС",
      taxCalculated ? money(kpis.vatOutput || 0) : "Не рассчитано",
      "",
      "",
      "Σ начисленного НДС с реализации по применённому налоговому профилю 1С.",
    ],
    [
      inputVatLabel,
      taxCalculated ? money(kpis.vatInput || 0) : "Не рассчитано",
      managementInputVat
        ? "Управленческое допущение; не подтверждено книгой покупок 1С"
        : "",
      managementInputVat ? "warning" : "",
      managementInputVat
        ? "Расчётный НДС импорта по разнице себестоимости с НДС и без НДС плюс расчётный НДС услуг WB. Это сценарий юнит-экономики, а не бухгалтерски подтверждённый вычет."
        : "Σ подтверждённого к вычету НДС по себестоимости и услугам, если профиль 1С разрешает вычет.",
    ],
    [
      vatPayableLabel,
      taxCalculated ? money(kpis.vatPayable || 0) : "Не рассчитано",
      managementInputVat
        ? "Сценарная величина до бухгалтерской сверки"
        : "",
      managementInputVat ? "warning" : "",
      managementInputVat
        ? "Исходящий НДС − расчётный входящий НДС по управленческому сценарию."
        : "Исходящий НДС − входящий НДС к вычету.",
    ],
    [
      revenueTaxLabel,
      taxCalculated ? money(kpis.revenueTax || 0) : "Не рассчитано",
      "",
      "",
      "Налоговая база, заданная применённым профилем 1С, × подтверждённая ставка налога.",
    ],
    [
      "Всего налогов",
      taxCalculated ? money(kpis.totalTax || 0) : "Не рассчитано",
      "",
      "",
      "НДС к уплате + налог с выручки + налог на прибыль, если он включён в профиль.",
    ],
    [
      "Прибыль после налогов",
      taxCalculated && profitAfterTax !== null ? money(profitAfterTax) : "Не рассчитано",
      taxCalculated
        ? kpis.taxBridgeCalculated
          ? "Налоговый мост сходится"
          : "Требуется сверка налогового моста"
        : "Налоговый профиль не применён",
      taxCalculated && kpis.taxBridgeCalculated ? "ok" : "warning",
      "Маржинальный доход до налогов − всего налогов. Карточка доступна только после подтверждения налогового профиля 1С.",
    ],
    [
      "Недополученный маржинальный доход",
      lostSalesCalculated && lostContribution !== null
        ? money(lostContribution)
        : "Не рассчитано",
      lostSalesCalculated && lostSalesPeriod
        ? `За доступный период ${lostSalesPeriod}, без экстраполяции`
        : lostSalesCoverage.message || "",
      lostSalesCalculated && lostSalesCoverage.fullCoverage !== true
        ? "warning"
        : "",
      "Оценённые недополученные продажи × маржинальный доход на единицу; показывается только для покрытого периода без экстраполяции.",
    ],
    [
      "Продажи WB до возвратов, шт",
      number(sales),
      "",
      "",
      "Σ количества продаж из строк WB до вычета возвратов.",
    ],
    [
      "Чистые продажи WB, шт",
      number(netSales),
      "",
      "",
      "Количество продаж WB − количество возвратов WB.",
    ],
    [
      "Возвраты, шт",
      number(returns),
      "",
      "",
      "Σ количества возвратов из строк WB за выбранный период.",
    ],
    [
      "Возвратность",
      returnRate,
      "",
      "",
      "Количество возвратов WB ÷ количество продаж WB до возвратов.",
    ],
    [
      "Выручка / продажа",
      money(revenuePerSale),
      "",
      "",
      "Выручка WB без НДС ÷ количество продаж WB до возвратов.",
    ],
    [
      "Убыточных продаж",
      lossRows,
      "",
      "",
      "Количество строк WB, в которых управленческая прибыль после расходов отрицательна.",
    ],
    [
      "Штрафов без продаж",
      penaltyOnlyRows,
      "",
      "",
      "Количество строк WB с удержанием или штрафом без продажи товара.",
    ],
  ];
  renderMetrics(els.kpiGrid, unitMetrics);
  renderMetrics(els.onecKpiGrid, controlMetrics);
}

function lostSalesCoveragePeriodText(coverage = {}) {
  const periodStart = coverage.calculationPeriodStart || "";
  const periodEnd = coverage.calculationPeriodEnd || "";
  if (!periodStart && !periodEnd) {
    return "";
  }
  return [formatCompactDate(periodStart), formatCompactDate(periodEnd)]
    .filter(Boolean)
    .join("–");
}

function renderOzonKpis(diagnostics = state.latestOzonDiagnostics) {
  const payload = diagnostics || {};
  els.onecKpiSection.hidden = true;
  renderMetrics(els.onecKpiGrid, []);
  setKpiHeading({
    eyebrow: "Служебная витрина",
    title: "Показатели",
  });
  renderMetrics(
    els.kpiGrid,
    ozonMartMetricItems(
      payload.ozonMart || payload.unitRows || {},
      payload.reconciliation || {},
    ),
  );
}

function ozonMartMetricItems(mart = {}, reconciliation = {}) {
  const totals = mart.totals || {};
  const reconciliationTotals = mart.reconciliationTotals || {};
  const closedTotals = mart.closedPeriodTotals || {};
  const excludedOpenPeriods = asArray(mart.excludedOpenPeriods);
  const excludedIncompletePeriods = asArray(mart.excludedIncompletePeriods);
  const excludedPeriodCount =
    excludedOpenPeriods.length + excludedIncompletePeriods.length;
  const costQuality = mart.costQuality || {};
  const profitBeforeTax = totals.profitBeforeTax ?? totals.profit;
  const afterTax = totals.profitAfterTax;
  const taxProfile = mart.taxProfile || {};
  const osno = ["осно", "общ"].some((marker) =>
    normalize(taxProfile.taxSystem).includes(marker),
  );
  const canonicalProfit =
    afterTax ?? totals.profitBeforeIncomeTax ?? profitBeforeTax;
  const canonicalProfitLabel =
    afterTax != null
      ? "Прибыль после налогов"
      : osno
        ? "Управленческая прибыль до НДФЛ"
        : "Прибыль до налогов";
  const includesAdditionalOnecDocuments =
    mart.pnlScope === "onec_sales_register_including_additional_documents";
  const profitCaption = excludedPeriodCount
    ? `не рассчитано: исключено периодов ${excludedPeriodCount}`
    : includesAdditionalOnecDocuments
      ? "регистр продаж 1C · включая выкупы и дополнительные документы"
    : `SKU-экономика без выкупов · ${
        totals.taxCompleteness || "единая формула Ozon mart"
      }`;
  const directOnecRevenue = numberOrNull(reconciliationTotals.onecRevenue);
  const directOnecCogs = numberOrNull(reconciliationTotals.cogs);
  const hasDirectOnecRevenue =
    reconciliationTotals.revenueStatus === "available" &&
    directOnecRevenue !== null;
  const hasDirectOnecCogs =
    reconciliationTotals.cogsStatus === "available" && directOnecCogs !== null;
  const cogsVatCaption = "НДС не выделен: поле «Себестоимость» из 1C";
  const documentControl = reconciliation.documentControl || {};
  const documentIssueCount = Number(documentControl.issueCount || 0);
  return [
    [
      "Выручка 1C Ozon · факт",
      optionalMoney(hasDirectOnecRevenue ? directOnecRevenue : totals.onecRevenue),
      hasDirectOnecRevenue
        ? "Источник: 1C OData · регистр продаж · включая выкупы"
        : "SKU / закрывающие документы 1C",
      hasDirectOnecRevenue ? "ok" : "warning",
      "Это факт 1С, не API Ozon и не WB: Σ поля «Сумма» регистра продаж 1С по контрагенту Ozon, включая отчёты комиссионера, выкупы и другие проведённые документы.",
    ],
    [
      "Ozon API · ожидается в 1C",
      optionalMoney(reconciliation.ozonTotalAmount),
      "Реализация Ozon API + выкупы Ozon API",
      reconciliation.ozonTotalAmount == null ? "warning" : "info",
      "Ожидаемая первичка 1С = Σ реализации Ozon API + Σ выкупов Ozon API за выбранный период.",
      openOzonDocumentControlDetails,
    ],
    [
      "Дельта 1C − Ozon API",
      reconciliation.deltaAmount == null
        ? "Не рассчитано"
        : signedMoney(reconciliation.deltaAmount),
      "Ненулевая дельта раскрывается по первичным документам ниже",
      reconciliation.status === "matched" ? "ok" : "warning",
      "Факт регистра продаж 1С − ожидаемая сумма по API Ozon. Ноль означает, что первичные документы отражены полностью в сопоставимом периоде.",
      openOzonDocumentControlDetails,
    ],
    [
      "Первичные документы 1C",
      documentControl.status
        ? documentIssueCount
          ? `${number(documentIssueCount)} к исправлению`
          : "Сходятся"
        : "Не проверено",
      `${
        documentControl.status
          ? `Нет документа: ${number(
              documentControl.missingPrimaryCount || 0,
            )}; не проведён: ${number(
              documentControl.notPostedCount || 0,
            )}; не та дата: ${number(
              documentControl.wrongDateCount || 0,
            )}; не та сумма: ${number(documentControl.amountMismatchCount || 0)}`
          : "Нужны Ozon API и 1C за один период"
      } · Нажмите для расшифровки`,
      documentControl.status === "matched" ? "ok" : "warning",
      "Контроль классифицирует проблемы первички: документ отсутствует, не проведён, проведён не той датой или имеет сумму, отличную от Ozon API.",
      openOzonDocumentControlDetails,
    ],
    [
      "Себестоимость 1C",
      optionalMoney(hasDirectOnecCogs ? directOnecCogs : totals.cogs),
      hasDirectOnecCogs
        ? `регистр продаж 1C · включая выкупы · ${cogsVatCaption}`
        : `по SKU, месяцу и номенклатуре · ${cogsVatCaption}`,
      hasDirectOnecCogs ? "ok" : "warning",
      "Σ поля «Себестоимость» регистра продаж 1С. НДС в текущем источнике отдельно не выделен, поэтому карточка не заявляет сумму с НДС или без НДС.",
    ],
    [
      "Расходы Ozon",
      optionalMoney(totals.ozonExpenses),
      "по месячным документам",
      "",
      "Σ расходов Ozon из месячных закрывающих документов по статьям маркетплейса.",
    ],
    [
      canonicalProfitLabel,
      optionalMoney(excludedPeriodCount ? null : canonicalProfit),
      profitCaption,
      canonicalProfit == null || excludedPeriodCount
        ? "warning"
        : metricToneForAmount(canonicalProfit),
      "Выручка 1С Ozon − себестоимость 1С − расходы Ozon − применимые налоги. Состав зависит от статуса закрытия периода.",
    ],
    [
      "Закрытие периода",
      excludedOpenPeriods.length
        ? "Есть незакрытые"
        : excludedIncompletePeriods.length
          ? "Есть исключенные"
          : "Закрыт",
      excludedPeriodCount
        ? `закрытая часть: ${optionalMoney(
            closedTotals.profitBeforeTax ?? closedTotals.profit,
          )}`
        : "все месяцы диапазона закрыты в 1C",
      excludedPeriodCount ? "warning" : "ok",
      "Период закрыт, если все месяцы в выбранном диапазоне имеют подтверждённые закрывающие документы 1С. Незакрытые и неполные месяцы не входят в итог.",
    ],
    [
      "Качество себестоимости",
      costQuality.status === "complete"
        ? "Полное"
        : costQuality.status === "blocked"
          ? "Заблокировано"
          : "Есть предупреждения",
      `покрытие сопоставленной выручки ${percent(
        costQuality.eligibleRevenueCoveragePct,
      )}; покрытие количества ${percent(
        costQuality.quantityCoveragePct,
      )}; без связи ${number(costQuality.unmappedQuantity || 0)}; неоднозначно ${number(
        costQuality.ambiguousQuantity || 0,
      )}; неизвестная выручка ${number(
        Number(costQuality.unmappedRevenueRowCount || 0) +
          Number(costQuality.ambiguousRevenueRowCount || 0),
      )} строк; аномалий ${number(costQuality.anomalyCount || 0)}; влияние ${optionalMoney(
        costQuality.estimatedImpactAmount,
      )}`,
      costQuality.status === "complete" ? "ok" : "warning",
      "Покрытие рассчитывается как доля сопоставленной выручки и количества с подтверждённой себестоимостью 1С. Неоднозначные связи и аномалии не считаются качественными строками.",
    ],
    [
      "Налоговый профиль",
      taxProfile.taxSystem || "не найден",
      taxProfile.source || taxProfile.status || "1C",
      taxProfile.status === "ready" ? "ok" : "warning",
      "Налоговый режим, ставки и правила НДС из подтверждённого профиля организации 1С на период отчёта.",
    ],
  ];
}

function setKpiHeading(
  { eyebrow = "Основной расчёт", title = "Юнит-экономика WB" } = {},
) {
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
    .replaceAll("Ozon mart v1", "Расчет Ozon")
    .replaceAll("Ozon mart", "Расчет Ozon")
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
  renderDataTrustStatus(summary);
  renderMoneyTrendChart(els.moneyTrendChart, asArray(summary.monthly));
  renderUnitProfitAndLossTable(
    els.unitPlTable,
    summary.kpis || {},
    asArray(summary.expenses),
  );
  renderLossDriversChart(
    els.lossDriversChart,
    asArray(summary.liquidityRows),
  );
  renderLostContributionChart(
    els.lostMarginChart,
    asArray(summary.lostSales),
    summary.lostSalesCoverage || {},
  );
  renderReturnsChart(els.returnsChart, asArray(summary.monthly), summary.kpis || {});
  renderTaxInputReconciliation(
    els.taxInputChart,
    asArray(summary.taxInputReconciliation),
    summary.taxContext || {},
  );
}

function renderDataTrustStatus(summary = {}) {
  if (!els.dataTrustGrid || !els.dataTrustBadge || !els.dataTrustStrip) {
    return;
  }
  const taxContext = summary.taxContext || {};
  const taxProfileSync = summary.taxProfileSync || {};
  const coverage = summary.lostSalesCoverage || {};
  const monthly = asArray(summary.monthly);
  const partialMonth = monthly.find((row) => row.isPartial === true);
  const onecCollections = asArray((summary.latestSourceRefresh || {}).collections).filter(
    (item) => normalize(item.sourceType || item.source_type).startsWith("onec"),
  );
  const onecReady = onecCollections.length > 0 && onecCollections.every((item) =>
    ["loaded", "empty_expected"].includes(normalize(item.status)),
  );
  const taxReady =
    taxContext.calculated === true && taxProfileSync.reportStatus !== "stale";
  const liveTaxProfileReady = taxProfileSync.liveStatus === "ready";
  const reportTaxNotApplied = taxProfileSync.reportStatus === "not_applied";
  const taxProfileNeedsRebuild =
    ["not_applied", "confirmed_not_applied", "stale"].includes(
      normalize(taxProfileSync.reportStatus),
    );
  const stockReady = coverage.calculated === true;
  const stockFullCoverage = coverage.fullCoverage === true;
  const stockPeriod = lostSalesCoveragePeriodText(coverage);
  const trustReady =
    taxReady && stockReady && stockFullCoverage && !partialMonth && onecReady;
  const taxProfiles = asArray(taxContext.profiles);
  const taxProfilePeriod = taxProfiles.length
    ? `${taxProfiles[0].periodStart || "?"} — ${taxProfiles[0].periodEnd || "?"}`
    : "период не подтверждён";
  const taxBasis = taxProfileNeedsRebuild
    ? "профиль требует пересборки"
    : taxContext.rateBasisKind === "regional_preference"
    ? taxContext.basisDocument
      ? `региональная льгота: ${taxContext.basisDocument}`
      : "ставка подтверждена настройками"
    : taxContext.calculated === true && taxContext.revenueTaxRate != null
      ? "ставка подтверждена настройками"
      : taxContext.rateBasisKind || "источник ставки не указан";
  const taxMessage = taxReady
    ? taxContext.message
    : taxProfileNeedsRebuild
      ? taxProfileSync.message
      : taxContext.message || taxProfileSync.message;
  els.dataTrustStrip.classList.toggle("readiness-ready", trustReady);
  els.dataTrustStrip.classList.toggle("readiness-review", !trustReady);
  els.dataTrustBadge.textContent = trustReady ? "Данные подтверждены" : "Есть ограничения";
  renderMetrics(els.dataTrustGrid, [
    [
      "Налоговый профиль",
      taxReady
        ? taxContext.taxSystem || "Применён"
        : liveTaxProfileReady
          ? "Получен из 1С"
          : reportTaxNotApplied
            ? "Не применён к расчёту"
            : "Не подтверждён",
      `${taxMessage || "Профиль проверяется."} ${taxBasis}; период ${taxProfilePeriod}.`,
      taxReady ? "ok" : "warning",
    ],
    [
      "История остатков",
      stockFullCoverage
        ? "Полное покрытие"
        : stockReady
          ? `${number(coverage.coveredDays || 0)} дней рассчитано`
        : `${number(coverage.coveredDays || 0)} из ${number(coverage.totalDays || 0)} дней`,
      stockReady && stockPeriod
        ? `${coverage.message || ""} Период расчёта: ${stockPeriod}.`
        : coverage.message || "Недополученный доход не рассчитан.",
      stockFullCoverage ? "ok" : "warning",
    ],
    [
      "Период",
      partialMonth ? "Есть неполный месяц" : "Полные месяцы",
      partialMonth
        ? `${partialMonth.month}: ${number(partialMonth.daysElapsed || 0)} из ${number(
            partialMonth.daysInMonth || 0,
          )} дней`
        : "Сопоставление месяцев корректно.",
      partialMonth ? "warning" : "ok",
    ],
    [
      "Источники 1С",
      onecReady ? "Загружены" : "Требуют проверки",
      onecCollections.length
        ? `${number(onecCollections.length)} источников в последнем обновлении`
        : "Нет подтверждающих документов в текущем контексте.",
      onecReady ? "ok" : "warning",
    ],
  ]);
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

function shouldKeepOzonDiagnosticsVisible(
  diagnostics = state.latestOzonDiagnostics,
) {
  return Boolean(
    shouldRenderOzonAnalytics() &&
      diagnostics?.latestRun &&
      normalize(diagnostics?.ozonMart?.status) !== "not_started",
  );
}

function setOzonServiceCabinetNotice(
  diagnostics = state.latestOzonDiagnostics,
) {
  setTopbarNotice(
    "Доступна служебная витрина Ozon + 1C",
    "Ниже показана служебная витрина Ozon + 1C по последнему расчетному снимку.",
  );
  renderOzonPreflightWithoutReport(diagnostics);
}

function setOzonDraftNotice(summary = state.summary || {}) {
  const diagnostics = summary.ozonDiagnostics || state.latestOzonDiagnostics || {};
  const needsReview = normalize(diagnostics.status) !== "ready";
  setTopbarNotice(
    needsReview ? "Черновик Ozon — требуется проверка" : "Черновик Ozon готов",
    "Внутренний отчёт закреплён за конкретным снимком Ozon + 1C и не опубликован клиенту.",
    needsReview ? "warning" : "ok",
  );
  renderOzonPreflightWithoutReport(diagnostics);
}

function selectedSourceRefreshMode() {
  const selectedCabinet = selectedMarketplaceCabinet();
  return selectedCabinet && isOzonMarketplaceCabinet(selectedCabinet)
    ? "ozon-only"
    : "";
}

function renderOzonPreflightWithoutReport(diagnostics = {}) {
  const mart = diagnostics?.ozonMart || diagnostics?.unitRows || {};
  const summary = mart.summary || {};
  const rowCount = Number(mart.rowCount || 0);
  const readyRows = Number(summary.ready || 0);
  const missingCost = Number(summary.missingCost || 0);
  const mappingRows =
    Number(summary.missingMapping || 0) + Number(summary.ambiguousMapping || 0);
  const martReady = normalize(mart.status) === "ready";
  const issueCount = asArray(diagnostics?.issues?.items).length;

  els.reviewRowsButton.disabled = true;
  els.reviewRowsButton.textContent = "Нужен клиентский отчёт";
  els.qualityProgressFill.style.width = rowCount
    ? `${Math.round((readyRows / rowCount) * 100)}%`
    : "0%";
  els.qualitySummaryText.textContent =
    "Контроль перед отправкой пока недоступен: клиентский отчёт не создан. Ниже — проверка служебной витрины Ozon + 1C.";
  renderMetrics(els.qualityGrid, [
    [
      "Клиентский отчёт",
      "Не создан",
      "Проверки строк для отправки появятся после создания отчёта.",
      "warning",
    ],
    [
      "Расчёт Ozon + 1C",
      martReady ? "Загружен" : "Требует проверки",
      rowCount ? `${number(rowCount)} товарных строк в служебной витрине.` : "Нет расчетных строк.",
      martReady ? "ok" : "warning",
    ],
    ["Без себестоимости", missingCost, "По SKU Ozon.", missingCost ? "warning" : "ok"],
    ["Сопоставление", mappingRows, "Строки без надежной пары Ozon ↔ 1C.", mappingRows ? "warning" : "ok"],
  ]);
  renderReasons(
    els.blockingReasons,
    [],
    "Клиентский отчёт не создан: отправлять клиенту пока нечего.",
    "blocker",
  );
  renderReasons(
    els.reviewReasons,
    [],
    issueCount
      ? `${number(issueCount)} ограничений показано в документном контроле Ozon + 1C.`
      : "Ограничений Ozon в текущем снимке не найдено.",
    "review",
  );
  renderReasons(
    els.doneReasons,
    [],
    rowCount
      ? "Снимок Ozon + 1C загружен; доступна служебная витрина."
      : "Снимок Ozon + 1C пока не содержит расчетных строк.",
    "review",
  );
}

function renderOzonAnalytics(diagnostics = state.latestOzonDiagnostics) {
  const payload = diagnostics || {};
  const mart = payload.ozonMart || payload.unitRows || {};
  setAnalyticsTitles("ozon", mart);
  const rows = asArray(mart.rows);
  const totals = mart.totals || {};
  const summary = mart.summary || {};
  renderOzonActionInsights(els.actionInsightsList, payload, mart);
  renderOzonMoneyTrendChart(els.moneyTrendChart, payload, mart);
  renderOzonProfitAndLoss(els.unitPlTable, totals, mart);
  renderOzonProblems(els.lossDriversChart, summary);
  renderOzonReconciliationAnalytics(els.returnsChart, payload);
  renderOzonArticleEconomics(els.taxInputChart, mart);
  if (!rows.length && normalize(payload.status) === "error") {
    renderAnalyticsEmpty(
      els.moneyTrendChart,
      ozonMartMessageText(payload.message || "Расчет Ozon не загрузился."),
    );
  }
}

function setAnalyticsTitles(mode, mart = {}) {
  const ozonMode = mode === "ozon";
  const includesAdditionalOnecDocuments =
    mart.pnlScope === "onec_sales_register_including_additional_documents";
  document.body.classList.toggle("ozon-analytics-mode", ozonMode);
  if (!ozonMode) {
    resetOzonAnalyticsCardGrids();
  }
  els.moneyTrendTitle.textContent = "Динамика денег";
  els.moneyTrendCopy.textContent = "Выручка, прибыль и маржа по месяцам.";
  els.unitPlTitle.textContent = ozonMode
    ? includesAdditionalOnecDocuments
      ? "P&L Ozon (включая выкупы)"
      : "SKU-P&L Ozon (без выкупов)"
    : "Прибыли и убытки юнит-экономики";
  els.unitPlCopy.textContent = ozonMode
    ? includesAdditionalOnecDocuments
      ? "Итоги совпадают с верхними KPI регистра 1C и включают выкупы. Без подтвержденной связи выкупы остаются документным контролем, а не распределяются по SKU. НДС в себестоимости не выделен."
      : "Только товарные строки реализации/комиссионера: не равен верхним KPI регистра 1C, где есть выкупы. НДС в себестоимости не выделен."
    : "Для ОСНО выручка и расходы показываются без НДС.";
  els.lossDriversTitle.textContent = ozonMode
    ? "Что мешает расчету"
    : "Фактические убытки";
  els.lossDriversCopy.textContent = ozonMode
    ? "Сопоставление, себестоимость, закрытие 1C и неполные расходы."
    : "Товары и строки с уже полученным отрицательным результатом.";
  els.returnsChartTitle.textContent = ozonMode
    ? "Документный контроль Ozon + 1C"
    : "Возвраты";
  els.returnsChartCopy.textContent = ozonMode
    ? "Комиссионер, выкупы и расходы: что сходится и что проверить."
    : "Возвратность и объем возвратов по месяцам.";
  els.taxInputTitle.textContent = ozonMode
    ? "Статьи экономики Ozon"
    : "Сверка входящего НДС";
  els.taxInputCopy.textContent = ozonMode
    ? "Расходы, распределение и контрольные строки отдельным широким блоком."
    : "Начисления, сторно, нетто, подтверждение 1С и право на вычет.";
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

function renderOzonMoneyTrendChart(target, diagnostics = {}, mart = {}) {
  renderMoneyTrendChart(target, ozonMoneyTrendRows(diagnostics, mart));
}

function ozonMoneyTrendRows(diagnostics = {}, mart = {}) {
  const rows = asArray(mart.rows);
  const totals = mart.totals || {};
  const rowCount = Number(mart.rowCount || rows.length || 0);
  if (!rowCount) {
    return [];
  }
  if (
    mart.pnlScope !== "onec_sales_register_including_additional_documents" &&
    !mart.previewLimited &&
    rows.some(ozonMoneyTrendHasOwnPeriod)
  ) {
    return ozonMoneyTrendRowsFromItems(rows, diagnostics);
  }
  return [ozonMoneyTrendTotalsRow(diagnostics, mart)];
}

function ozonMoneyTrendRowsFromItems(rows, diagnostics = {}) {
  const buckets = new Map();
  asArray(rows).forEach((item) => {
    const key = ozonMoneyTrendBucketKey(item, diagnostics);
    const bucket = buckets.get(key) || {
      key,
      month: ozonMoneyTrendPeriodLabel(
        item.periodStart || item.periodEnd,
        item.periodEnd || item.periodStart,
      ),
      revenue: 0,
      profit: 0,
      hasProfit: false,
    };
    const revenue = numberOrNull(item.onecRevenue ?? item.revenueAmount ?? item.revenue) || 0;
    const profit = numberOrNull(
      item.profitBeforeTax ?? item.profitAmount ?? item.profit,
    );
    bucket.revenue += revenue;
    if (profit !== null) {
      bucket.profit += profit;
      bucket.hasProfit = true;
    }
    buckets.set(key, bucket);
  });
  return Array.from(buckets.values())
    .sort((left, right) => left.key.localeCompare(right.key))
    .map((bucket) => ({
      month: bucket.month,
      revenue: bucket.revenue,
      profit: bucket.hasProfit ? bucket.profit : null,
      profitDisplay: bucket.hasProfit ? "" : "не рассчитано",
      margin: bucket.revenue && bucket.hasProfit ? bucket.profit / bucket.revenue : null,
    }));
}

function ozonMoneyTrendTotalsRow(diagnostics = {}, mart = {}) {
  const totals = mart.totals || {};
  const profit = numberOrNull(totals.profitBeforeTax ?? totals.profit);
  const period = ozonMoneyTrendFallbackPeriod(diagnostics);
  return {
    month: ozonMoneyTrendPeriodLabel(period.periodStart, period.periodEnd),
    revenue: Number(totals.onecRevenue ?? totals.revenue ?? 0),
    profit: profit === null ? null : profit,
    profitDisplay: profit === null ? "не рассчитано" : "",
    margin: numberOrNull(totals.marginBeforeTax ?? totals.margin),
  };
}

function ozonMoneyTrendHasOwnPeriod(item = {}) {
  return Boolean(item.periodStart || item.periodEnd);
}

function ozonMoneyTrendBucketKey(item = {}, diagnostics = {}) {
  const value =
    item.periodStart ||
    item.periodEnd ||
    diagnostics.latestRun?.periodStart ||
    els.topbarPeriodStart?.value ||
    "";
  return ozonPeriodMonthKey(value) || "selected-period";
}

function ozonMoneyTrendFallbackPeriod(diagnostics = {}) {
  const latestRun = diagnostics.latestRun || {};
  return {
    periodStart: latestRun.periodStart || els.topbarPeriodStart?.value || "",
    periodEnd: latestRun.periodEnd || els.topbarPeriodEnd?.value || "",
  };
}

function ozonMoneyTrendPeriodLabel(periodStart, periodEnd) {
  const startMonth = ozonPeriodMonthKey(periodStart);
  const endMonth = ozonPeriodMonthKey(periodEnd);
  if (startMonth && (!endMonth || startMonth === endMonth)) {
    return formatMonthYearLabel(periodStart);
  }
  if (startMonth && endMonth) {
    return `${formatCompactDate(periodStart)} - ${formatCompactDate(periodEnd)}`;
  }
  return "Выбранный период";
}

function ozonPeriodMonthKey(value) {
  const date = parseIsoDate(value);
  if (!date) {
    return "";
  }
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function formatMonthYearLabel(value) {
  const date = parseIsoDate(value);
  if (!date) {
    return String(value || "Выбранный период");
  }
  const label = new Intl.DateTimeFormat("ru-RU", {
    month: "long",
    year: "numeric",
  }).format(date);
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function formatCompactDate(value) {
  const date = parseIsoDate(value);
  if (!date) {
    return String(value || "");
  }
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
}

function parseIsoDate(value) {
  if (!value) {
    return null;
  }
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (match) {
    return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function renderOzonProfitAndLoss(target, totals = {}, mart = {}) {
  const articleRows = ozonMartArticlePlRows(mart);
  if (articleRows.length) {
    const revenue = Number(totals.onecRevenue || 0);
    target.replaceChildren(profitAndLossTable(articleRows, revenue));
    return;
  }
  const revenue = Number(totals.onecRevenue || 0);
  const cogs = Number(totals.cogs || 0);
  const includesAdditionalOnecDocuments =
    mart.pnlScope === "onec_sales_register_including_additional_documents";
  const hasOzonExpenses = totals.ozonExpenses !== null && totals.ozonExpenses !== undefined;
  const ozonExpenses = hasOzonExpenses ? Number(totals.ozonExpenses || 0) : null;
  const profitValue = totals.profitBeforeTax ?? totals.profit;
  const profit = profitValue == null ? null : Number(profitValue || 0);
  if (!revenue && !cogs && !hasOzonExpenses && profit == null) {
    renderAnalyticsEmpty(target, "Прибыли и убытки Ozon не рассчитаны: нужны выручка 1C и расходы.");
    return;
  }
  target.replaceChildren(
    profitAndLossTable(
      [
        {
          label: includesAdditionalOnecDocuments
            ? "1C выручка Ozon (включая выкупы)"
            : "1C выручка Ozon SKU (без выкупов)",
          amount: revenue,
          tone: "revenue",
        },
        {
          label: includesAdditionalOnecDocuments
            ? "Себестоимость 1C (включая выкупы; НДС не выделен)"
            : "Себестоимость 1C по SKU (НДС не выделен)",
          amount: -cogs,
          tone: "expense",
        },
        {
          label: "Прямые расходы Ozon по товарам",
          amount: ozonExpenses == null ? null : -ozonExpenses,
          display: ozonExpenses == null ? "не рассчитано" : null,
          tone: "expense",
        },
        {
          label: includesAdditionalOnecDocuments
            ? "Прибыль до налогов (включая выкупы)"
            : "Прибыль до налогов по SKU",
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

function renderOzonArticleEconomics(target, mart = {}) {
  const hasArticleContext =
    Number(mart.rowCount || 0) ||
    asArray(mart.articleRows).length ||
    asArray(mart.articleDrilldown).length;
  if (!hasArticleContext) {
    renderAnalyticsEmpty(target, "Статьи экономики Ozon не рассчитаны для выбранного периода.");
    return;
  }
  const cards = ozonArticleEconomicsCards(mart);
  if (!cards.length) {
    renderAnalyticsEmpty(target, "Нет детализации статей Ozon для выбранного периода.");
    return;
  }
  const grid = document.createElement("div");
  grid.className = "metric-grid ozon-economics-grid";
  grid.replaceChildren(...cards);
  target.replaceChildren(grid);
}

function ozonArticleEconomicsCards(mart = {}) {
  const cards = [];
  const copyText = ozonExpenseAttributionCopy(mart);
  if (copyText) {
    cards.push(
      ozonArticleEconomicsCard({
        label: "База расходов Ozon",
        value: "Распределение расходов",
        caption: copyText,
        tone: "info",
      }),
    );
  }
  ozonArticleDrilldownRows(mart).forEach((item) => {
    cards.push(
      ozonArticleEconomicsCard({
        label: item.label || item.articleId || "Статья Ozon",
        value: ozonArticleAmountText(item),
        caption: ozonArticleCardCaption(item),
        tone: item.status === "ready" ? "ok" : "warning",
      }),
    );
  });
  return cards;
}

function ozonArticleEconomicsCard({ label, value, caption, tone = "" }) {
  const item = document.createElement("div");
  item.className = `metric ${tone ? `metric-${tone}` : ""}`.trim();
  const labelNode = document.createElement("span");
  labelNode.textContent = label;
  const valueNode = document.createElement("strong");
  valueNode.textContent = value;
  item.append(labelNode, valueNode);
  if (caption) {
    const captionNode = document.createElement("small");
    captionNode.textContent = caption;
    item.append(captionNode);
  }
  return item;
}

function ozonArticleDrilldownRows(mart = {}) {
  return asArray(mart.articleDrilldown)
    .filter(
      (item) =>
        item &&
        (item.includedInSkuProfit ||
          item.kind === "period_expense_control" ||
          normalize(item.group) === "reconciliation"),
    )
    .slice(0, 10);
}

function ozonArticleAmountText(item = {}) {
  return optionalMoney(
    item.amount ??
      item.unattributedExpenseAmount ??
      item.periodExpenseDeltaAmount,
  );
}

function ozonArticleCardCaption(item = {}) {
  return [
    ozonArticleAttributionLabel(item),
    localizedOperationalMessage(item.note || ozonUnitStatusText(item.status)),
    localizedOperationalMessage(item.sourceLabel),
    item.offerId,
    item.sku,
  ]
    .filter(Boolean)
    .join(" · ");
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
  const rows = ozonArticleDrilldownRows(mart);
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
  copy.textContent = ozonExpenseAttributionCopy(mart);
  heading.append(title, copy);

  const table = document.createElement("div");
  table.className = "analytics-detail-table";
  table.setAttribute("role", "table");
  const header = document.createElement("div");
  header.className = "analytics-detail-row header";
  header.setAttribute("role", "row");
  ["Статья", "Тип / источник", "Сумма", "Статус"].forEach((label) => {
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
      source.textContent = localizedOperationalMessage(item.sourceLabel);
      label.append(source);
    }

    const source = document.createElement("span");
    source.setAttribute("role", "cell");
    source.textContent =
      [
        ozonArticleAttributionLabel(item),
        item.offerId,
        item.sku,
        item.productName || localizedOperationalMessage(item.sourceLabel),
      ]
        .filter(Boolean)
        .join(" · ") || "-";

    const amount = document.createElement("span");
    amount.className = "analytics-detail-value";
    amount.setAttribute("role", "cell");
    amount.textContent = ozonArticleAmountText(item);

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

function ozonExpenseAttributionNotice(mart = {}) {
  const copyText = ozonExpenseAttributionCopy(mart);
  if (!copyText) {
    return null;
  }
  const wrapper = document.createElement("div");
  wrapper.className = "analytics-detail";
  const heading = document.createElement("div");
  heading.className = "analytics-detail-heading";
  const title = document.createElement("strong");
  title.textContent = "База расходов Ozon";
  const copy = document.createElement("span");
  copy.textContent = copyText;
  heading.append(title, copy);
  wrapper.append(heading);
  return wrapper;
}

function ozonExpenseAttributionCopy(mart = {}, summary = {}, totals = {}) {
  const attribution = mart.expenseAttribution || {};
  const status = normalize(attribution.status);
  if (status === "sku_direct") {
    return "Расходы по SKU из детализации Ozon; отчёт о взаиморасчётах использован для контроля.";
  }
  if (status === "mixed_sku_and_period_unattributed") {
    return "Часть расходов распределена: детализация по SKU сохранена, остаток периода распределён по выручке 1C.";
  }
  if (status === "allocated_period_expense") {
    return "Часть расходов распределена: детализации расходов по SKU нет, период распределён по выручке 1C.";
  }
  if (status === "sku_detail_above_period") {
    return "Расходы по SKU из детализации Ozon больше отчёта о взаиморасчётах; отрицательный остаток не распределён.";
  }
  if (totals.expenseBasis === "ozon_cash_flow_statement") {
    return "Денежный контроль, без SKU-распределения.";
  }
  if (Number(summary.partialExpenses || 0)) {
    return "Частичные расходы: нужна сверка.";
  }
  return "Расходы по SKU из детализации Ozon.";
}

function ozonArticleAttributionLabel(item = {}) {
  const kind = normalize(item.kind);
  const attributionType = normalize(item.attributionType || item.expenseAttributionType);
  if (kind === "period_expense_control") {
    return "сверка детализации Ozon";
  }
  if (kind.startsWith("reconciliation_") || normalize(item.group) === "reconciliation") {
    return "сверка 1C/Ozon";
  }
  if (attributionType === "period_unattributed" || kind === "period_unattributed") {
    return "нераспределенный остаток";
  }
  if (
    attributionType === "mixed_sku_and_period_unattributed" ||
    kind === "mixed_sku_and_period_unattributed"
  ) {
    return "часть распределена";
  }
  if (attributionType === "sku_direct" || kind === "sku_direct") {
    return "по SKU";
  }
  return "по SKU";
}

function renderOzonProblems(target, summary = {}) {
  const rows = [
    ["Нет сопоставления", summary.missingMapping],
    ["Несколько вариантов сопоставления", summary.ambiguousMapping],
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
    clearAnalyticsMetricsGrid(target);
    renderAnalyticsEmpty(target, "Критичных проблем по расчету Ozon нет.");
    return;
  }
  renderAnalyticsMetricsGrid(
    target,
    rows.map((row) => [
      row.label,
      `${number(row.value)} строк`,
      row.meta,
      "warning",
    ]),
  );
}

function renderOzonReconciliationAnalytics(target, diagnostics = {}) {
  const reconciliation = diagnostics.reconciliation || {};
  const expenseReconciliation = diagnostics.expenseReconciliation || {};
  const buyouts = diagnostics.ozonBuyouts?.summary || {};
  const mart = diagnostics.ozonMart || diagnostics.unitRows || {};
  const expenseStatus = normalize(expenseReconciliation.status);
  renderAnalyticsMetricsGrid(target, [
    [
      "Статус сверки",
      reconciliation.status || mart.status || "-",
      reconciliation.message || mart.message || "",
      reconciliation.status === "matched" ? "ok" : "warning",
    ],
    [
      "Реализация · Ozon API",
      optionalMoney(reconciliation.ozonCommissionerAmount),
      "ожидаемая первичка",
    ],
    [
      "Отчет комиссионера · 1C",
      optionalMoney(reconciliation.commissionerAmount),
      "фактический документ 1C",
    ],
    [
      "Дельта комиссионера · 1C − Ozon",
      reconciliation.commissionerDeltaAmount == null
        ? "не рассчитано"
        : signedMoney(reconciliation.commissionerDeltaAmount),
      "должна быть 0 ₽",
      Math.abs(Number(reconciliation.commissionerDeltaAmount || 0)) > 1
        ? "warning"
        : "ok",
    ],
    [
      "Выкупы · Ozon API",
      optionalMoney(reconciliation.buyoutAmount ?? buyouts.amount),
      `${number(reconciliation.buyoutQuantity ?? buyouts.quantity ?? 0)} шт`,
    ],
    [
      "Выкупы · документы 1C",
      optionalMoney(reconciliation.onecBuyoutAmount),
      "расходные накладные",
    ],
    [
      "Ожидается в 1C · итого Ozon API",
      optionalMoney(reconciliation.ozonTotalAmount),
      "реализация + выкупы",
    ],
    [
      "Факт 1C · регистр продаж",
      optionalMoney(reconciliation.onecSalesRegisterAmount),
      "проведённые документы",
    ],
    [
      "Дельта итого · 1C − Ozon API",
      reconciliation.deltaAmount == null
        ? "не рассчитано"
        : signedMoney(reconciliation.deltaAmount),
      "раскрывается по первичным документам",
      Math.abs(Number(reconciliation.deltaAmount || 0)) > 1 ? "warning" : "ok",
    ],
    [
      "Прямые расходы Ozon по товарам",
      optionalMoney(expenseReconciliation.ozonExpenseAmount),
      ozonExpenseSourceCaption(expenseReconciliation.ozon || {}, mart.totals || {}),
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
  const documentControlNode = ozonRevenueDocumentControlNode(
    reconciliation.documentControl || {},
  );
  if (documentControlNode) {
    target.append(documentControlNode);
  }
  if (detailNode) {
    target.append(detailNode);
  }
}

function ozonRevenueDocumentControlNode(control = {}) {
  const rows = asArray(control.rows);
  if (!rows.length) {
    return null;
  }
  const wrapper = document.createElement("div");
  wrapper.className = "analytics-detail ozon-document-control";

  const heading = document.createElement("div");
  heading.className = "analytics-detail-heading";
  const headingText = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = control.issueCount
    ? `Первичные документы 1C: ${number(control.issueCount)} к исправлению`
    : "Первичные документы 1C сходятся";
  const copy = document.createElement("span");
  copy.textContent =
    "Сначала исправьте документ в 1C, затем запустите повторную проверку Ozon + 1C.";
  headingText.append(title, copy);

  const actions = document.createElement("div");
  actions.className = "inline-actions";
  const openButton = document.createElement("button");
  openButton.type = "button";
  openButton.className = "secondary-button";
  openButton.textContent = "Открыть документы Ozon";
  openButton.addEventListener("click", () => {
    selectDetailTab("ozon");
    els.ozonBuyoutRows?.closest(".ozon-table-section")?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  });
  const refreshButton = document.createElement("button");
  refreshButton.type = "button";
  refreshButton.textContent = "Перепроверить после исправления";
  refreshButton.disabled = !isStaffUser() || !state.clientId;
  refreshButton.addEventListener("click", () =>
    runClientSourceRefresh({ dryRun: false, mode: "ozon-only" }),
  );
  actions.append(openButton, refreshButton);
  heading.append(headingText, actions);

  const tableWrap = document.createElement("div");
  tableWrap.className = "table-wrap";
  const table = document.createElement("table");
  table.className = "products-table data-table ozon-document-control-table";
  const tableHead = document.createElement("thead");
  const headRow = document.createElement("tr");
  [
    "Проверка",
    "Ozon API",
    "1C",
    "Дельта",
    "Документы 1C",
    "Проблема",
    "Что сделать",
  ].forEach((label) => {
    const cell = document.createElement("th");
    cell.textContent = label;
    headRow.append(cell);
  });
  tableHead.append(headRow);
  const body = document.createElement("tbody");
  rows.forEach((item) => body.append(ozonDocumentControlRowNode(item)));
  table.append(tableHead, body);
  tableWrap.append(table);
  wrapper.append(heading, tableWrap);
  return wrapper;
}

function openOzonDocumentControlDetails() {
  let target = document.querySelector(".ozon-document-control");
  if (!target && state.latestOzonDiagnostics) {
    renderOzonAnalytics(state.latestOzonDiagnostics);
    target = document.querySelector(".ozon-document-control");
  }
  if (!target) {
    return;
  }
  const issueRow = target.querySelector("tr.is-review");
  target.classList.add("is-focused");
  issueRow?.classList.add("is-focused");
  target.scrollIntoView({ behavior: "smooth", block: "start" });
  if (issueRow) {
    issueRow.tabIndex = -1;
    window.setTimeout(() => issueRow.focus({ preventScroll: true }), 350);
  }
  window.setTimeout(() => {
    target.classList.remove("is-focused");
    issueRow?.classList.remove("is-focused");
  }, 3200);
}

function ozonDocumentControlRowNode(item = {}) {
  const row = document.createElement("tr");
  row.className = item.status === "matched" ? "" : "is-review";
  appendTableCells(row, [
    {
      value: `${item.label || "Документ"} · ${periodRangeText(
        item.periodStart,
        item.periodEnd,
      )}`,
      className: "text-wide text-strong",
    },
    { value: optionalMoney(item.ozonAmount), className: "numeric" },
    { value: optionalMoney(item.onecAmount), className: "numeric" },
    {
      value: item.deltaAmount == null ? "-" : signedMoney(item.deltaAmount),
      className: "numeric",
    },
    {
      value: asArray(item.documents).join("; ") || "не найден",
      className: "text-wide",
    },
    {
      value: item.problem || "-",
      badge: true,
      tone: item.status === "matched" ? "ok" : "warning",
    },
    { value: item.action || "-", className: "text-wide" },
  ]);
  return row;
}

function renderAnalyticsMetricsGrid(target, items) {
  target.classList.add("metric-grid", "ozon-analytics-card-grid");
  renderMetrics(target, items);
}

function clearAnalyticsMetricsGrid(target) {
  target?.classList.remove("metric-grid", "ozon-analytics-card-grid");
}

function resetOzonAnalyticsCardGrids() {
  [
    els.lossDriversChart,
    els.returnsChart,
    els.taxInputChart,
  ].forEach(clearAnalyticsMetricsGrid);
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
      title: "Недополученный маржинальный доход",
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
  if (action.name === "missingMapping" && isStaffUser()) {
    node.setAttribute("aria-haspopup", "dialog");
    node.setAttribute("aria-controls", "mapping-widget-overlay");
  }
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
    if (isStaffUser()) {
      openMappingWidget({ marketplace: "wb", status: "review", search: "" });
    } else {
      openDrilldownWidget("missingMapping");
    }
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
    (row) =>
      Number(row.revenue || 0) ||
      Number(row.profit || 0) ||
      Boolean(row.revenueDisplay || row.profitDisplay),
  );
  if (!rows.length) {
    renderAnalyticsEmpty(target, "Нет месячных данных для динамики.");
    return;
  }
  renderColumnChart(
    target,
    rows.map((row) => {
      const revenue = Number(row.revenue || 0);
      const profit = numberOrNull(row.profit);
      const profitValue = profit === null ? 0 : profit;
      return {
        label: row.month || "-",
        meta: `Маржа ${percent(row.margin)}`,
        action: { name: "month", month: row.month || "" },
        series: [
          {
            label: "Выручка",
            value: revenue,
            tone: "revenue",
            display: row.revenueDisplay || money(revenue),
          },
          {
            label: "Прибыль",
            value: profitValue,
            tone: profitValue < 0 ? "negative" : "profit",
            display: row.profitDisplay || signedMoney(profitValue),
          },
        ],
      };
    }),
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
  const revenueWithVat = numberOrNull(kpis.revenueWithVat ?? kpis.grossRevenue);
  const showRevenueWithVat =
    revenueWithVat !== null && Math.abs(Number(revenueWithVat || 0) - revenue) > 1;
  const expenseRows = asArray(expenses)
    .filter((row) => !isTaxBridgeExpense(row))
    .map((row) => ({
      label: row.expense || "Расход",
      amount: Math.abs(Number(row.amount || 0)),
    }))
    .filter((row) => row.amount > 0);
  const expenseTotal = expenseRows.reduce((total, row) => total + row.amount, 0);
  const explicitProfit = managementProfitFromKpis(kpis, null);
  const profit = explicitProfit === null ? revenue - expenseTotal : explicitProfit;
  if (financialCheckFailed((state.summary || {}).readiness || {})) {
    renderAnalyticsEmpty(
      target,
      "Прибыли и убытки не рассчитаны: финансовая проверка источников и методики не пройдена.",
    );
    return;
  }
  if (!revenue && !profit && !expenseRows.length) {
    renderAnalyticsEmpty(target, "Нет данных для расчёта прибылей и убытков.");
    return;
  }
  const unallocated = Math.max(0, revenue - profit - expenseTotal);
  const rows = [
    {
      label: showRevenueWithVat ? "Выручка WB без НДС" : "Выручка WB",
      amount: revenue,
      tone: "revenue",
    },
    ...(showRevenueWithVat
      ? [
          {
            label: "Выручка WB по товарным строкам, с НДС",
            amount: revenueWithVat,
            tone: "reference",
            shareDisplay: "справочно",
          },
        ]
      : []),
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
      label: "Маржинальный доход до налогов",
      amount: profit,
      tone: profit < 0 ? "negative result" : "profit result",
      action: profit < 0 ? { name: "rowsPreset", preset: "losses" } : null,
    },
  ];
  target.replaceChildren(profitAndLossTable(rows, revenue));
}

function managementProfitFromKpis(kpis = {}, fallback = 0) {
  const value = numberOrNull(
    kpis.profitManagement ?? kpis.managementProfit ?? kpis.profitBeforeTax,
  );
  if (value !== null) {
    return value;
  }
  if (fallback === null) {
    return null;
  }
  return Number(kpis.profit || fallback || 0);
}

function isTaxBridgeExpense(row = {}) {
  const key = normalize(
    [row.key, row.kind, row.articleId, row.metric, row.code].filter(Boolean).join(" "),
  );
  const label = normalize(
    [row.expense, row.label, row.name, row.title].filter(Boolean).join(" "),
  );
  const haystack = `${key} ${label}`;
  return (
    haystack.includes("ндс") ||
    haystack.includes("vat") ||
    haystack.includes("усн") ||
    haystack.includes("tax") ||
    haystack.includes("ндфл") ||
    haystack.includes("налог")
  );
}

function renderLossDriversChart(target, liquidityRows) {
  const losses = asArray(liquidityRows)
    .filter((row) => Number(row.profit || 0) < 0 && !isPenaltyOnlyEconomics(row))
    .map((row) => ({
      label: row.product || row.liquidityDriver || "Убыточная группа",
      value: Math.abs(Number(row.profit || 0)),
      meta: row.liquidityDriver || row.liquidityStatus || "Отрицательная прибыль",
      tone: "negative",
      action: { name: "rowsPreset", preset: "losses" },
    }));
  const rows = losses
    .sort((left, right) => right.value - left.value)
    .slice(0, 6);
  renderBarRows(target, rows, {
    emptyText: "Нет фактических убыточных строк для рейтинга.",
  });
}

function renderLostContributionChart(target, lostSales, coverage = {}) {
  if (coverage.calculated !== true) {
    renderAnalyticsEmpty(
      target,
      coverage.message || "Не рассчитано: полная история остатков не получена.",
    );
    return;
  }
  const rows = asArray(lostSales)
    .filter((row) => Number(row.lostContributionMargin ?? row.lostProfit ?? 0) > 0)
    .map((row) => ({
      label: row.product || row.article1c || "Товар",
      value: Number(row.lostContributionMargin ?? row.lostProfit ?? 0),
      meta: "Предварительная оценка до налогов",
      tone: "missed",
      action: { name: "lostSales" },
    }))
    .sort((left, right) => right.value - left.value)
    .slice(0, 6);
  renderBarRows(target, rows, {
    emptyText: "Нет положительной оценки недополученного маржинального дохода.",
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
        monthStart: row.monthStart || "",
        isPartial: row.isPartial === true,
        className: row.isPartial === true ? "partial-period" : "",
        meta: `${number(returns)} возвратов / ${number(sales)} продаж${
          row.isPartial === true
            ? ` · неполный месяц: ${number(row.daysElapsed || 0)} из ${number(
                row.daysInMonth || 0,
              )} дней`
            : ""
        }`,
        action: { name: "month", month: row.month || "" },
        series: [
          {
            label: "Возвратность",
            value: rate,
            tone: "returns",
            display: percent(rate),
          },
        ],
      };
    })
    .filter((row) => Number(row.series[0].value || 0))
    .sort(
      (left, right) =>
        Number(left.isPartial) - Number(right.isPartial) ||
        String(left.monthStart).localeCompare(String(right.monthStart)),
    );
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

function renderTaxInputReconciliation(target, rows, taxContext = {}) {
  if (!target) {
    return;
  }
  const allRows = asArray(rows).filter(
    (row) =>
      Number(row.vatInputFromWb || 0) ||
      Number(row.vatInputFromWbCharges || 0) ||
      Number(row.vatInputFromWbReversals || 0) ||
      Number(row.vatInputFrom1c || 0) ||
      Number(row.vatInputDifference || 0),
  ).sort(
    (left, right) =>
      Math.abs(Number(right.vatInputDifference || 0)) -
        Math.abs(Number(left.vatInputDifference || 0)) ||
      String(right.week || "").localeCompare(String(left.week || "")),
  );
  if (!allRows.length) {
    renderAnalyticsEmpty(target, "Нет выделенного входящего НДС для сверки.");
    return;
  }
  const cabinets = [...new Set(allRows.map((row) => row.cabinet || "").filter(Boolean))]
    .sort((left, right) => left.localeCompare(right, "ru"));
  if (state.taxInputCabinet && !cabinets.includes(state.taxInputCabinet)) {
    state.taxInputCabinet = "";
  }
  const sourceRows = state.taxInputCabinet
    ? allRows.filter((row) => row.cabinet === state.taxInputCabinet)
    : allRows;
  const totalCharges = sourceRows.reduce(
    (total, row) => total + Number(row.vatInputFromWbCharges || 0),
    0,
  );
  const totalReversals = sourceRows.reduce(
    (total, row) => total + Number(row.vatInputFromWbReversals || 0),
    0,
  );
  const totalNet = sourceRows.reduce(
    (total, row) => total + Number(row.vatInputFromWb || 0),
    0,
  );
  const turnover = totalCharges + Math.abs(totalReversals);
  const totalOnec = sourceRows.reduce(
    (total, row) => total + Number(row.vatInputFrom1c || 0),
    0,
  );
  const totalGap = sourceRows.reduce(
    (total, row) => total + Number(row.vatInputDifference || 0),
    0,
  );

  const toolbar = document.createElement("div");
  toolbar.className = "tax-input-toolbar";
  const count = document.createElement("strong");
  count.textContent = `${number(sourceRows.length)} строк`;
  const filterLabel = document.createElement("label");
  filterLabel.textContent = "Кабинет ";
  const filter = document.createElement("select");
  filter.setAttribute("aria-label", "Фильтр сверки НДС по кабинету");
  filter.append(new Option("Все кабинеты", ""));
  cabinets.forEach((cabinet) => filter.append(new Option(cabinet, cabinet)));
  filter.value = state.taxInputCabinet;
  filter.addEventListener("change", () => {
    state.taxInputCabinet = filter.value;
    state.taxInputPage = 0;
    renderTaxInputReconciliation(target, allRows, taxContext);
  });
  filterLabel.append(filter);
  toolbar.append(count, filterLabel);

  const summary = document.createElement("p");
  summary.className = "analytics-summary-line";
  summary.textContent = `Начислено ${moneyWithCents(totalCharges)}, корректировки/сторно ${signedMoneyWithCents(
    totalReversals,
  )}, нетто ${moneyWithCents(totalNet)}. Оборот начислений и сторно ${moneyWithCents(
    turnover,
  )}; подтверждено 1С ${moneyWithCents(totalOnec)}, разница ${signedMoneyWithCents(totalGap)}. Право на вычет: ${vatDeductionModeLabel(
    taxContext.vatDeductionMode,
  )}.`;

  const pageSize = 10;
  const pageCount = Math.max(1, Math.ceil(sourceRows.length / pageSize));
  state.taxInputPage = Math.min(state.taxInputPage, pageCount - 1);
  const pageRows = sourceRows.slice(
    state.taxInputPage * pageSize,
    (state.taxInputPage + 1) * pageSize,
  );
  const wrap = document.createElement("div");
  wrap.className = "table-wrap tax-input-table-wrap";
  const table = document.createElement("table");
  table.className = "products-table data-table tax-input-semantic-table";
  const thead = table.createTHead();
  const header = thead.insertRow();
  [
    "Неделя / статус",
    "Кабинет",
    "Организация",
    "Начислено WB",
    "Сторно WB",
    "Нетто WB",
    "Документы 1С",
    "Разница / вычет",
  ].forEach((label) => {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = label;
    header.append(cell);
  });
  const tbody = table.createTBody();
  pageRows.forEach((row) => {
    const item = tbody.insertRow();
    item.className = taxInputCompletenessClass(row.vatInputCompleteness);
    const statusCell = item.insertCell();
    const heading = document.createElement("strong");
    heading.textContent = row.week || "-";
    const note = document.createElement("small");
    note.textContent = `${taxInputCompletenessLabel(
      row.vatInputCompleteness,
    )}: ${taxInputCompletenessNote(row)}`;
    statusCell.append(heading, note);
    const values = [
      row.cabinet || "-",
      row.organization || "-",
      moneyWithCents(row.vatInputFromWbCharges || 0),
      signedMoneyWithCents(row.vatInputFromWbReversals || 0),
      moneyWithCents(row.vatInputFromWb || 0),
      normalize(row.onecEvidenceStatus) === "missing"
        ? "Нет подтверждающих документов"
        : moneyWithCents(row.vatInputFrom1c || 0),
      `${signedMoneyWithCents(row.vatInputDifference || 0)} · ${vatDeductionModeLabel(
        row.vatDeductionMode || taxContext.vatDeductionMode,
      )}`,
    ];
    values.forEach((value) => {
      const cell = item.insertCell();
      cell.textContent = value;
    });
  });
  wrap.append(table);

  const pagination = document.createElement("div");
  pagination.className = "tax-input-pagination";
  const previous = document.createElement("button");
  previous.type = "button";
  previous.textContent = "Назад";
  previous.disabled = state.taxInputPage === 0;
  previous.addEventListener("click", () => {
    state.taxInputPage -= 1;
    renderTaxInputReconciliation(target, allRows, taxContext);
  });
  const pageLabel = document.createElement("span");
  pageLabel.textContent = `Страница ${state.taxInputPage + 1} из ${pageCount}`;
  const next = document.createElement("button");
  next.type = "button";
  next.textContent = "Далее";
  next.disabled = state.taxInputPage >= pageCount - 1;
  next.addEventListener("click", () => {
    state.taxInputPage += 1;
    renderTaxInputReconciliation(target, allRows, taxContext);
  });
  pagination.append(previous, pageLabel, next);
  target.replaceChildren(toolbar, summary, wrap, pagination);
}

function vatDeductionModeLabel(value) {
  return {
    allowed: "разрешено",
    not_allowed: "не разрешено",
    not_applicable: "не применимо",
    unknown: "не подтверждено",
    mixed: "различается по организациям",
  }[normalize(value)] || "не подтверждено";
}

function taxInputCompletenessLabel(value) {
  const status = normalize(value || "");
  if (status === "confirmed") {
    return "Подтверждено";
  }
  if (status === "management_assumption") {
    return "Управленческое допущение";
  }
  if (status === "partial") {
    return "Частично подтверждено";
  }
  if (status === "mismatch") {
    return "Есть расхождение";
  }
  if (status === "missing") {
    return "Нет подтверждающих документов";
  }
  return value || "-";
}

function taxInputCompletenessClass(value) {
  const status = normalize(value || "");
  if (status === "confirmed") {
    return "matched";
  }
  if (status === "management_assumption") {
    return "warning";
  }
  if (status === "partial" || status === "mismatch") {
    return "warning";
  }
  if (status === "missing") {
    return "muted";
  }
  return "";
}

function taxInputDisplayAmount(value) {
  return Math.abs(Number(value || 0));
}

function taxInputGap(row) {
  return Math.abs(
    taxInputDisplayAmount(row.vatInputFrom1c) -
      taxInputDisplayAmount(row.vatInputFromWb),
  );
}

function taxInputCompletenessNote(row) {
  const status = normalize(row.vatInputCompleteness || "");
  const wbAmount = taxInputDisplayAmount(row.vatInputFromWb);
  const onecAmount = taxInputDisplayAmount(row.vatInputFrom1c);
  if (status === "confirmed") {
    return "WB и 1С сходятся.";
  }
  if (status === "management_assumption") {
    return "расчёт для юнит-экономики; книга покупок 1С его пока не подтверждает.";
  }
  if (status === "partial" && wbAmount && !onecAmount) {
    return "в WB есть НДС по расходам, в 1С за неделю подтверждение не найдено.";
  }
  if (status === "partial") {
    return "часть суммы подтверждена, остаток надо сверить с закрывающими.";
  }
  if (status === "mismatch") {
    return "WB и закрывающие 1С дают разные суммы.";
  }
  if (status === "missing") {
    return "в 1С не найдены подтверждающие документы; ноль не подставлен.";
  }
  return "нужна ручная проверка.";
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
    item.className = `analytics-column-group ${group.className || ""}`.trim();
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
      share.textContent =
        row.shareDisplay !== undefined
          ? row.shareDisplay
          : revenue && row.amount != null
            ? percent(Number(row.amount) / revenue)
            : "-";

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

function moneyWithCents(value) {
  return `${new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value || 0))} ₽`;
}

function signedMoneyWithCents(value) {
  const numericValue = Number(value || 0);
  return numericValue < 0
    ? `−${moneyWithCents(Math.abs(numericValue))}`
    : moneyWithCents(numericValue);
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
  const penaltyOnlyRows = safeRows.filter(isPenaltyOnlyEconomics);
  const lossRows = safeRows.filter(
    (row) => Number(row.profit || 0) < 0 && !isPenaltyOnlyEconomics(row),
  );
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
      "Группы с отрицательной управленческой прибылью.",
      lossRows.length ? "bad" : "ok",
    ],
    [
      "Штрафы без продаж",
      number(penaltyOnlyRows.length),
      "Отдельные инциденты; не входят в рейтинг товарной маржи.",
      penaltyOnlyRows.length ? "warning" : "ok",
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
    ...sorted
      .filter((row) => Number(row.profit || 0) < 0 && !isPenaltyOnlyEconomics(row))
      .slice(0, 12),
    ...penaltyOnlyRows.slice(0, 4),
    ...sorted
      .filter((row) => Number(row.profit || 0) >= 0 && !isPenaltyOnlyEconomics(row))
      .slice(-8)
      .reverse(),
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
          title: "Управленческий МД: для ОСНО считается без НДС.",
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
    ...items.map(([label, value, caption = "", tone = "", formula = "", action = null]) => {
      const item = document.createElement("div");
      item.className = `metric ${tone ? `metric-${tone}` : ""} ${
        typeof action === "function" ? "metric-action" : ""
      }`.trim();
      if (formula) {
        item.dataset.tooltip = String(formula);
      }
      if (typeof action === "function") {
        item.tabIndex = 0;
        item.setAttribute("role", "button");
        item.setAttribute("aria-label", `${label}. Открыть расшифровку.`);
        item.addEventListener("click", action);
        item.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            action();
          }
        });
      } else if (formula) {
        item.tabIndex = 0;
        item.setAttribute("aria-label", `${label}. Формула: ${formula}`);
      }
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
      if (Number(reason.affectedRevenue || 0)) {
        const impact = document.createElement("small");
        impact.textContent = `Выручка под риском: ${money(reason.affectedRevenue)}`;
        content.append(impact);
      }
      const hint = document.createElement("small");
      hint.className = "reason-hint";
      hint.textContent = guide.hint;
      const action = document.createElement("button");
      action.type = "button";
      action.className = "reason-action-link";
      action.textContent = guide.label;
      action.addEventListener("click", () => runReasonAction(guide.action));
      const actions = document.createElement("div");
      actions.className = "task-card-actions";
      actions.append(action);
      if (tone !== "blocker") {
        const markViewed = document.createElement("button");
        markViewed.type = "button";
        markViewed.className = "reason-action-link task-done-link";
        markViewed.textContent = "Отметить просмотренным";
        markViewed.title = "Отметка не меняет данные и расчетный статус отчёта.";
        markViewed.addEventListener("click", () => setTaskReviewed(reason, true));
        actions.append(markViewed);
      }
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
        title: `Просмотрено: ${reason.message || "задача по отчету"}`,
        detail: "Локальная отметка не меняет данные. Расчетный статус изменится только после исправления источника и пересборки отчета.",
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
      detail: "Критических препятствий для готовности отчёта нет.",
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
      detail: "Можно открыть отчёт для клиента и приложить Excel.",
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
  return reason?.fingerprint || normalize(
    [reason?.code, reason?.message].filter(Boolean).join(":"),
  );
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
  if (code === "cogs_reconciliation_failed") {
    return costReconciliationGuide(reason);
  }
  const guides = {
    missing_cost: {
      hint: "Расшифровка откроет строки, где не подтянулась подтвержденная себестоимость из 1С.",
      label: "Показать строки без себестоимости",
      action: "missingCost",
    },
    mapping_review: {
      hint: "Расшифровка откроет товары без сопоставления WB-1С или с несколькими вариантами связи.",
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
      hint: "Это проблема загрузки: расшифровка покажет статус последнего обновления данных и источники.",
      label: "Показать источники",
      action: "sources",
    },
    source_load_failed: {
      hint: "Источник не загрузился: расшифровка покажет последнее обновление данных и проблемные наборы.",
      label: "Показать источники",
      action: "sources",
    },
    source_load_review_required: {
      hint: "Источник загружен. Перед отправкой отчёта проверьте отмеченные данные — например, сопоставление WB ↔ 1С.",
      label: "Проверить источник",
      action: "sources",
    },
    source_loads_missing: {
      hint: "Нет истории загрузок: проверьте последнюю выгрузку источников и пересоберите отчёт.",
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
      hint: "Откройте отчёт для клиента и подготовьте его к отправке вместе с Excel.",
      label: "Открыть отчёт для клиента",
      action: "clientOutput",
    },
    client_draft_not_ready: {
      hint: "Откройте отчёт для клиента, проверьте черновик и доведите его до готового состояния.",
      label: "Открыть отчёт для клиента",
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

function costReconciliationGuide(reason = {}) {
  const total = Number(reason.count || 0);
  const requiresReview = Number(reason.costRequiresReviewRows || 0);
  const absent = Number(reason.costAbsentRows || 0);
  const breakdown = requiresReview || absent
    ? `${number(requiresReview)} рассчитаны по ближайшей себестоимости и требуют сверки; ${number(absent)} без действующей себестоимости 1С.`
    : "Расшифровка разделит временную себестоимость и товары, где стоимостной слой не найден.";
  return {
    hint: `${breakdown} Блокер исчезнет только после обновления данных 1С и пересборки отчёта.`,
    label: total
      ? `Открыть ${number(total)} строк себестоимости`
      : "Открыть проверку себестоимости",
    action: "missingCost",
  };
}

function runReasonAction(action) {
  if (action === "missingCost") {
    openDrilldownWidget("missingCost");
    return;
  }
  if (action === "missingMapping") {
    if (isStaffUser()) {
      openMappingWidget({ marketplace: "wb", status: "review", search: "" });
    } else {
      openDrilldownWidget("missingMapping");
    }
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

function renderRowsLoadingState() {
  const message = "Загружаем строки и показатели по текущим фильтрам.";
  renderRowsAnalyticsStatus(message, "Загрузка", "info");
  renderReviewRowsStatus(message, "Загрузка");
}

function renderRowsErrorState() {
  const message = "Не удалось загрузить строки отчета. Старые данные скрыты, повторите запрос.";
  renderRowsAnalyticsStatus(message, "Ошибка", "warning");
  renderReviewRowsStatus(message, "Ошибка");
}

function renderRowsAnalyticsStatus(message, value, tone) {
  setKpiHeading();
  renderMetrics(els.kpiGrid, [["Статус", value, message, tone]]);
  renderMetrics(els.qualityGrid, []);
  renderAnalyticsEmpty(els.actionInsightsList, message);
  renderAnalyticsEmpty(els.moneyTrendChart, message);
  renderAnalyticsEmpty(els.unitPlTable, message);
  renderAnalyticsEmpty(els.lossDriversChart, message);
  renderAnalyticsEmpty(els.returnsChart, message);
  renderAnalyticsEmpty(els.taxInputChart, message);
  renderLiquidityStatus(message, value);
  renderLostSalesStatus(message, value);
}

function renderReviewRowsStatus(message, countText) {
  renderReportRowsHeader("wb");
  renderReportRowsControls("wb");
  els.rowsCount.textContent = countText;
  replaceTableBodyWithMessage(els.reviewRows, 17, message);
}

function renderLiquidityStatus(message, countText) {
  els.liquidityCount.textContent = countText;
  els.liquiditySummary.textContent = message;
  renderMetrics(els.liquidityGrid, []);
  replaceTableBodyWithMessage(els.liquidityRows, 19, message);
}

function renderLostSalesStatus(message, countText) {
  els.lostSalesCount.textContent = countText;
  replaceTableBodyWithMessage(els.lostSalesRows, 10, message);
}

function replaceTableBodyWithMessage(target, colSpan, message) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = colSpan;
  cell.textContent = message;
  row.append(cell);
  target.replaceChildren(row);
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
  const allRows = asArray(mart.rows);
  const rows = filteredOzonMartRows(allRows);
  const rowCount = Number(mart.rowCount || allRows.length || 0);
  renderReportRowsHeader("ozon");
  renderReportRowsControls("ozon");
  els.rowsTitle.textContent = "Ozon: детализация по товарам";
  els.rowsCount.textContent = ozonRowsCountText(rows, allRows, rowCount);
  if (!rows.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 12;
    cell.textContent = allRows.length
      ? "Строки Ozon не найдены по выбранным фильтрам."
      : state.latestOzonDiagnostics
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
    presetBar.hidden = false;
  }
  if (els.rowsFilterForm) {
    els.rowsFilterForm.hidden = false;
  }
  applyRowsFilterMode(ozonMode ? "ozon" : "wb");
}

function applyRowsFilterMode(mode) {
  const ozonMode = mode === "ozon";
  document.body.classList.toggle("ozon-rows-mode", ozonMode);
  setRowsFilterLabel(els.filterQuery, "Поиск");
  setRowsFilterLabel(els.filterStatus, "Статус");
  setRowsFilterLabel(els.filterCabinet, "Кабинет");
  setRowsFilterLabel(els.filterPeriodStart, "Начало");
  setRowsFilterLabel(els.filterPeriodEnd, "Конец");
  setRowsFilterHidden(els.filterMonth, ozonMode);
  setRowsFilterHidden(els.filterOrganization, ozonMode);
  setRowsFilterHidden(els.filterScheme, ozonMode);
  setRowsFilterHidden(els.filterLossClass, ozonMode);
  els.filterQuery.placeholder = ozonMode
    ? "Товар, артикул продавца, SKU, штрихкод, 1C"
    : "Товар, артикул, баркод, nmId";
  if (ozonMode) {
    setOptions(els.filterStatus, OZON_UNIT_STATUS_OPTIONS, "Все статусы Ozon");
  } else {
    setOptions(els.filterStatus, (state.summary || {}).options?.statuses || [], "Все статусы");
  }
  syncRowsPresetButtons();
}

function setRowsFilterHidden(control, hidden) {
  const label = control?.closest("label");
  if (label) {
    label.hidden = hidden;
  }
}

function setRowsFilterLabel(control, text) {
  const label = control?.closest("label");
  if (!label) {
    return;
  }
  const textNode = Array.from(label.childNodes).find(
    (node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim(),
  );
  if (textNode) {
    textNode.textContent = `${text}\n                `;
  }
}

function filteredOzonMartRows(rows) {
  const query = normalize(els.filterQuery.value);
  const status = els.filterStatus.value;
  return asArray(rows).filter((item) => {
    if (status && item.qualityStatus !== status) {
      return false;
    }
    if (query && !ozonMartRowMatchesQuery(item, query)) {
      return false;
    }
    return ozonMartRowMatchesPreset(item, state.rowPreset);
  });
}

function ozonMartRowMatchesQuery(item, query) {
  const haystack = [
    item.offerId,
    item.sku,
    item.productId,
    item.barcode,
    item.productName,
    item.onecName,
    item.onecItemId,
    item.problemReason,
    item.statusReason,
    item.actionText,
  ].map(normalize).join(" ");
  return haystack.includes(query);
}

function ozonMartRowMatchesPreset(item, preset) {
  if (!preset) {
    return true;
  }
  const status = item.qualityStatus;
  if (preset === "losses") {
    const profit = numberOrNull(
      item.profitBeforeTax ?? item.profitAmount ?? item.profit,
    );
    return profit !== null && profit < 0;
  }
  if (preset === "missingCost") {
    return status === "missing_cost";
  }
  if (preset === "missingMapping") {
    return ["missing_mapping", "ambiguous_mapping"].includes(status);
  }
  if (preset === "returns") {
    return status === "buyout_period_only" || item.revenueBasis === "ozon_buyout_period_total";
  }
  if (preset === "review") {
    return status !== "ready" || normalize(item.expenseStatus) === "partial_source";
  }
  return true;
}

function ozonRowsCountText(rows, allRows, rowCount) {
  const total = Number(rowCount || allRows.length || 0);
  if (!total) {
    return "Нет строк";
  }
  if (rows.length === allRows.length) {
    return `${number(total)} строк`;
  }
  const previewText = total > allRows.length ? ` из ${number(allRows.length)} показанных` : "";
  return `${number(rows.length)}${previewText} строк`;
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
  const profitAmount = item.profitBeforeTax ?? item.profitAmount ?? item.profit;
  const margin = item.marginBeforeTax ?? item.margin;
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
      value: ozonUnitProfitMarginText(profitAmount, margin, item.expenseStatus),
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

function renderFinancialReconciliationStatus(message, countText = "") {
  els.onecReconciliationCount.textContent = countText;
  els.financialReconciliationSource.textContent = "";
  renderMetrics(els.financialReconciliationGrid, []);
  replaceTableBodyWithMessage(els.financialReconciliationRows, 9, message);
}

function renderFinancialReconciliation(rows, total, kpis = {}, source = {}, period = {}) {
  const safeRows = asArray(rows);
  const issueRows = Number(kpis.issueRows || 0);
  els.onecReconciliationCount.textContent = total
    ? `${number(total)} строк · ${number(issueRows)} к проверке`
    : "Нет строк";
  const revenueDelta = kpis.revenueDelta;
  const penaltiesDelta = kpis.penaltiesDelta;
  renderMetrics(els.financialReconciliationGrid, [
    [
      "Выручка 1С за календарный период",
      optionalMoney(kpis.onecCalendarRevenue),
      `Отчёты комиссионера и выкупы: ${number(kpis.onecCalendarDocumentCount || 0)} документов`,
      "ok",
    ],
    [
      "1С · отчёты комиссионера",
      optionalMoney(kpis.onecCalendarCommissionerRevenue),
    ],
    [
      "1С · выкупы по накладным",
      optionalMoney(kpis.onecCalendarBuyoutRevenue),
    ],
    ["Выручка комиссионера · WB", optionalMoney(kpis.revenueWb)],
    ["Выручка комиссионера · 1С", optionalMoney(kpis.revenueOnec)],
    [
      "Дельта выручки комиссионера · 1С − WB",
      revenueDelta == null ? "-" : signedMoney(revenueDelta),
      "Положительная дельта: в 1С больше",
      Math.abs(Number(revenueDelta || 0)) > 1 ? "warning" : "ok",
    ],
    ["Выкупы · розница WB", optionalMoney(kpis.buyoutRetailWb)],
    ["Выкупы · накладные 1С в периоде WB", optionalMoney(kpis.buyoutNetOnec)],
    ["Штрафы · WB", optionalMoney(kpis.penaltiesWb)],
    ["Штрафы · 1С", optionalMoney(kpis.penaltiesOnec)],
    [
      "Дельта штрафов · 1С − WB",
      penaltiesDelta == null ? "-" : signedMoney(penaltiesDelta),
      "Отрицательная дельта: в кабинете больше",
      Math.abs(Number(penaltiesDelta || 0)) > 1 ? "warning" : "ok",
    ],
  ]);
  const periodText = period.start && period.end ? `${period.start} — ${period.end}` : "";
  els.financialReconciliationSource.textContent = source.refreshRunId
    ? `Календарный период 1С ${periodText}: итог включает отчёты комиссионера, расходные накладные по выкупам и корректировки. Розница WB показана справочно; денежная сверка выкупа требует первичного уведомления WB с полем «Сумма выкупа».`
    : "Источник 1С не найден: суммы 1С оставлены пустыми, а не заменены нулем.";
  renderFinancialReconciliationRows(safeRows, total);
}

function renderFinancialReconciliationRows(rows, total) {
  if (!rows.length) {
    const message =
      !total && els.onecFilterDeltaOnly.checked
        ? "Расхождений по выручке и штрафам не найдено."
        : "Строки финансовой сверки не найдены. Измените фильтры.";
    replaceTableBodyWithMessage(els.financialReconciliationRows, 9, message);
    return;
  }
  els.financialReconciliationRows.replaceChildren(
    ...rows.map(financialReconciliationRowNode),
  );
}

function financialReconciliationRowNode(item) {
  const row = document.createElement("tr");
  const status = normalize(item.status);
  if (!["сходится", "справочно"].includes(status)) {
    row.className = "is-review has-delta";
  }
  appendTableCells(row, [
    { value: item.controlLabel || "-", badge: true, tone: "neutral" },
    { value: item.period || "-", className: "text-nowrap" },
    { value: item.wbDocument || "-", className: "text-wide text-code" },
    { value: item.onecDocuments || "-", className: "text-wide text-code" },
    { value: optionalMoney(item.wbAmount), className: "numeric" },
    { value: optionalMoney(item.onecAmount), className: "numeric" },
    {
      value: item.delta == null ? "-" : signedMoney(item.delta),
      className: `numeric delta ${valueTone(item.delta, { zero: "muted" })}`,
    },
    {
      value: item.status || "-",
      badge: true,
      tone: financialReconciliationStatusTone(item.status),
    },
    { value: item.comment || "-", className: "text-wide" },
  ]);
  return row;
}

function financialReconciliationStatusTone(status) {
  const value = normalize(status);
  if (value === "сходится") {
    return "status-ok";
  }
  if (value === "справочно") {
    return "neutral";
  }
  if (value.includes("вне периода") || value.includes("только в 1с")) {
    return "status-warning";
  }
  return "status-blocked";
}

function renderOnecReconciliationStatus(message) {
  els.onecReconciliationTechnicalCount.textContent = "";
  renderMetrics(els.onecReconciliationGrid, []);
  replaceTableBodyWithMessage(els.onecReconciliationRows, 15, message);
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
  const comparableRevenueDelta = Number(
    kpis.comparableRevenueDelta ?? amountDelta,
  );
  els.onecReconciliationTechnicalCount.textContent = documentCount
    ? `${number(documentCount)} документов`
    : "Нет документов";
  renderMetrics(els.onecReconciliationGrid, [
    ["Документов", number(documentCount)],
    ["ОК", number(okRows)],
    ["К проверке", number(issueRows)],
    ["Дельта количества", number(quantityDelta)],
    ["Дельта выручки комиссионера", money(comparableRevenueDelta)],
    ["Выкупы · розница WB", optionalMoney(kpis.buyoutRetailWb)],
    ["Выкупы · накладные 1С", optionalMoney(kpis.buyoutNetOnec)],
    [
      "Выкупы · первичка WB",
      kpis.buyoutPrimaryDocumentStatus === "verified"
        ? optionalMoney(kpis.buyoutPrimaryDocumentAmount)
        : "Не проверено",
    ],
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
  const isBuyout = normalize(item.documentType) === "уведомление о выкупе";
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
        isBuyout
          ? "Не сравнивается"
          : item.amountDelta || item.amountDelta === 0
          ? signedMoney(item.amountDelta)
          : "-",
      className: isBuyout
        ? "numeric muted"
        : `numeric delta ${valueTone(item.amountDelta, { zero: "muted" })}`,
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

function renderDrilldownRowsStatus(message, countText = "Ошибка") {
  renderDrilldownRowsHeader(state.drilldownPreset);
  els.drilldownCount.textContent = countText;
  if (state.drilldownPreset === "missingCost") {
    renderCostIssueGuidance({}, 0, message);
  }
  replaceTableBodyWithMessage(
    els.drilldownRows,
    state.drilldownPreset === "missingCost" ? 11 : 17,
    message,
  );
}

function renderDrilldownRows(rows, total, preset = "review", breakdown = {}) {
  const safeRows = asArray(rows);
  renderDrilldownRowsHeader(preset);
  els.drilldownCount.textContent = total ? `${total} строк` : "Нет строк";
  if (preset === "missingCost") {
    renderCostIssueGuidance(costIssueBreakdown(breakdown, safeRows, total), total);
    if (!safeRows.length) {
      replaceTableBodyWithMessage(
        els.drilldownRows,
        11,
        "Строк с проблемой себестоимости по выбранным фильтрам не найдено.",
      );
      return;
    }
    els.drilldownRows.replaceChildren(...safeRows.map(costIssueRowNode));
    return;
  }
  els.drilldownGuidance.hidden = true;
  els.drilldownGuidance.replaceChildren();
  renderReportRowsTable(els.drilldownRows, safeRows);
}

function costIssueBreakdown(breakdown = {}, rows = [], total = 0) {
  if (
    breakdown.totalRows !== undefined ||
    breakdown.requiresReviewRows !== undefined ||
    breakdown.absentRows !== undefined
  ) {
    return breakdown;
  }
  const safeRows = asArray(rows);
  if (safeRows.length < Number(total || 0)) {
    return { totalRows: Number(total || 0) };
  }
  const absentRows = safeRows.filter(
    (item) => normalize(item.status) === "нет себестоимости 1с",
  ).length;
  return {
    totalRows: Number(total || safeRows.length),
    requiresReviewRows: safeRows.length - absentRows,
    absentRows,
  };
}

function renderDrilldownRowsHeader(preset) {
  const labels = preset === "missingCost"
    ? [
        "Неделя продажи",
        "Кабинет",
        "Товар",
        "Артикул WB",
        "Артикул 1С",
        "Чистое количество",
        "Себестоимость в расчёте",
        "Выручка",
        "Статус",
        "Почему",
        "Что делать",
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
  labels.forEach((label) => {
    const cell = document.createElement("th");
    cell.textContent = label;
    row.append(cell);
  });
  els.drilldownRowsHead.replaceChildren(row);
}

function renderCostIssueGuidance(breakdown = {}, total = 0, statusMessage = "") {
  const requiresReview = Number(breakdown.requiresReviewRows || 0);
  const absent = Number(breakdown.absentRows || 0);
  const totalRows = Number(breakdown.totalRows ?? total ?? 0);
  const reviewCard = costGuidanceCard(
    "Себестоимость требует сверки",
    requiresReview,
    "В расчёте уже использована ближайшая доступная себестоимость. Загрузите точный недельный слой 1С и пересоберите отчёт.",
    "review",
  );
  const absentCard = costGuidanceCard(
    "Себестоимость не найдена",
    absent,
    "Добавьте или исправьте действующую себестоимость товара в 1С, затем обновите источники и пересоберите отчёт.",
    absent ? "blocked" : "ok",
  );
  const note = document.createElement("p");
  note.className = "cost-guidance-note";
  note.textContent = statusMessage || (
    totalRows
      ? `Всего ${number(totalRows)} строк. Этот экран работает только на чтение и не исправляет данные 1С.`
      : "По выбранным фильтрам проблем себестоимости нет."
  );
  els.drilldownGuidance.hidden = false;
  els.drilldownGuidance.replaceChildren(reviewCard, absentCard, note);
}

function costGuidanceCard(title, count, copy, tone) {
  const card = document.createElement("article");
  card.className = `cost-guidance-card is-${tone}`;
  const heading = document.createElement("strong");
  heading.textContent = `${title}: ${number(count)}`;
  const description = document.createElement("p");
  description.textContent = copy;
  card.append(heading, description);
  return card;
}

function costIssueRowNode(item) {
  const row = document.createElement("tr");
  row.className = tableRowClass(item);
  appendTableCells(row, [
    { value: item.week || item.month || "-", className: "text-nowrap" },
    { value: item.cabinet || "-", className: "text-wide" },
    { value: item.product || "-", className: "text-wide text-strong" },
    { value: item.articleWb || "-", className: "text-code" },
    { value: item.article1c || "-", className: "text-code" },
    { value: number(item.netQty || 0), className: "numeric" },
    { value: money(item.cost || 0), className: "numeric" },
    { value: money(item.revenue || 0), className: "numeric" },
    {
      value: statusLabel(item.status),
      badge: true,
      tone: statusTone(item.status, item.statusReason),
      title: statusExplanation(item.status, item.statusReason),
    },
    { value: item.statusReason || item.status || "-", className: "text-wide" },
    { value: costIssueAction(item), className: "text-wide cost-next-action" },
  ]);
  return row;
}

function costIssueAction(item) {
  return normalize(item.status) === "нет себестоимости 1с"
    ? "Исправить себестоимость товара в 1С → обновить источники → пересобрать отчёт."
    : "Загрузить точную себестоимость 1С за неделю продажи → пересобрать отчёт.";
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
  const card = sourceCard("Последнее обновление источников", refresh.status);
  const message = document.createElement("p");
  message.className = "source-load-message";
  message.textContent = localizedOperationalMessage(
    refresh.safeMessage || sourceStatusHint(refresh.status),
  );
  const meta = sourceMetaList([
    ["Статус", sourceStatusText(refresh.status)],
    ["Режим", sourceRefreshModeText(refresh.mode)],
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
  const title = sourceLabelText(item);
  const card = sourceCard(title, item.status);
  const message = document.createElement("p");
  message.className = "source-load-message";
  message.textContent = sourceStatusHint(item.status, item.required);
  const meta = sourceMetaList([
    ["Тип", sourceTypeText(item.sourceType)],
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
    ? "Последнее обновление данных есть, но наборы источников не записаны."
    : "По текущему отчёту нет истории загрузки источников.";
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

function sourceRefreshModeText(mode) {
  const value = normalize(mode);
  return {
    daily: "ежедневный",
    full: "полный",
    "onec-only": "только 1С",
    "ozon-only": "диагностика Ozon",
    manual: "ручной",
  }[value] || (value ? "другой" : "-");
}

function sourceLabelText(item = {}) {
  const label = String(item.sourceLabel || "").trim();
  const labels = {
    "Marketplace ↔ 1C mapping service": "Сервис сопоставления маркетплейса ↔ 1С",
    "WB Finance sales report details": "Детализация отчёта о продажах WB",
    "WB Finance sales report list": "Список отчётов о продажах WB",
    "WB product cards": "Карточки товаров WB",
    "WB daily stock history": "Ежедневная история остатков WB",
    "1С OData metadata": "Метаданные 1С OData",
    "Ozon financial cash-flow statement": "Движение денежных средств Ozon",
    "Ozon realization report": "Отчёт Ozon о реализации",
    "Ozon mutual settlement report": "Отчёт Ozon о взаиморасчётах",
    "Ozon realization posting report": "Документы реализации Ozon",
    "Ozon products buyout report": "Отчёт Ozon о выкупах",
    "Ozon B2B sales JSON": "Продажи Ozon для бизнеса",
    "Ozon products report": "Отчёт Ozon по товарам",
    "Ozon stock on warehouses": "Остатки Ozon на складах",
    "Ozon returns report": "Отчёт Ozon по возвратам",
  };
  return labels[label] || label || sourceTypeText(item.sourceType);
}

function sourceTypeText(sourceType) {
  const value = normalize(sourceType);
  return {
    sku_mapping: "сопоставление товаров",
    wb_finance_detail: "детализация продаж WB",
    wb_sales_report_list: "список отчётов WB",
    wb_product_cards: "карточки товаров WB",
    wb_stock_history_daily: "ежедневная история остатков WB",
    onec_odata: "данные 1С OData",
    onec_odata_metadata: "метаданные 1С OData",
    ozon_finance_cash_flow: "движение денежных средств Ozon",
    ozon_realization: "реализация Ozon",
    ozon_mutual_settlement: "взаиморасчёты Ozon",
    ozon_realization_posting: "документы реализации Ozon",
    ozon_products_buyout: "выкупы Ozon",
    ozon_b2b_sales_json: "продажи Ozon для бизнеса",
    ozon_products_report: "товары Ozon",
    ozon_stock_on_warehouses: "остатки Ozon",
    ozon_returns_report: "возвраты Ozon",
  }[value] || (value.startsWith("onec_") ? "данные 1С" : "другой источник");
}

function localizedOperationalMessage(message = "") {
  return String(message || "")
    .replaceAll("Refresh не запущен", "Обновление данных не запущено")
    .replaceAll("Последний refresh", "Последнее обновление данных")
    .replaceAll("последний refresh", "последнее обновление данных")
    .replaceAll("Refresh", "Обновление данных")
    .replaceAll("refresh", "обновление данных")
    .replaceAll("Read-only", "Только для чтения")
    .replaceAll("read-only", "только для чтения")
    .replaceAll("readiness", "готовность отчёта")
    .replaceAll("source snapshots", "снимки источников")
    .replaceAll("snapshot", "снимок данных")
    .replaceAll("lineage", "история загрузки")
    .replaceAll("Mapping", "Сопоставление")
    .replaceAll("mapping", "сопоставление")
    .replaceAll("Fallback", "Резервный вариант")
    .replaceAll("fallback", "резервный вариант")
    .replaceAll("daily", "ежедневный")
    .replaceAll("mutual settlement", "отчёт о взаиморасчётах")
    .replaceAll("cash-flow", "движение денежных средств")
    .replaceAll("preview", "предварительный просмотр")
    .replaceAll("detail", "детализация")
    .replaceAll("metadata", "метаданные")
    .replaceAll("hash-only", "контрольная метка")
    .replaceAll("encrypted", "зашифрованное хранение")
    .replaceAll("live check", "проверка подключения")
    .replaceAll("P&L", "прибыли и убытки");
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
    return "Обновление уже выполняется";
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
  if (value === "partial_source") {
    return "Данные загружены частично";
  }
  if (value === "stale") {
    return "Данные устарели";
  }
  if (value === "skipped_large_snapshot") {
    return "Сохранено отдельным файлом";
  }
  return "Неизвестный статус";
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
    return "Идёт чтение WB, 1С и сопоставления без изменения данных. Страница остаётся доступной.";
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
    return "Источник не принял ключ только для чтения. Нужно проверить права доступа.";
  }
  if (value === "rate_limited") {
    return "Провайдер ограничил частоту запросов. Повторите позже.";
  }
  if (value === "blocked_low_disk") {
    return "Обновление данных не запущено: недостаточно места для снимка данных.";
  }
  if (value === "needs_configuration") {
    return "Нужно заново проверить настройку подключения только для чтения.";
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
  return "Проверьте последнюю загрузку и при необходимости повторите обновление данных.";
}

function sourceRefreshAdvice(status) {
  const value = normalize(status);
  if (value === "blocked_low_disk") {
    return "Что сделать: удалить старые снимки источников или расширить диск, затем повторить обновление данных.";
  }
  if (value === "needs_configuration") {
    return "Что сделать: открыть интеграции, проверить доступы WB и 1С только для чтения и повторить проверку.";
  }
  if (value === "needs_review") {
    return "Что сделать: посмотреть коллекции ниже, исправить источник или принять ограничение периода.";
  }
  if (value.includes("fail") || value.includes("error")) {
    return "Что сделать: проверить обязательный источник и повторить обновление данных после исправления.";
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
  const isBuyout = normalize(item.documentType) === "уведомление о выкупе";
  const comparedDeltas = isBuyout ? [item.quantityDelta] : [
    item.quantityDelta,
    item.amountDelta,
    item.settlementDelta,
    item.salesQuantityDelta,
    item.returnQuantityDelta,
    item.netQuantityDelta,
  ];
  const hasDelta = comparedDeltas.some(
    (value) => Math.abs(Number(value || 0)) > 0.0001,
  );
  const statusText = normalize(item.status);
  const documentText = normalize(item.onecDocuments);
  if (hasDelta) {
    classes.push("has-delta");
  }
  if (
    statusText &&
    !["ok", "ок", "документ найден", "сверено по количеству"].includes(statusText)
  ) {
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
  if (["ok", "ок", "документ найден", "сверено по количеству"].includes(value)) {
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

function renderLostSales(rows, coverage = {}) {
  if (coverage.calculated !== true) {
    els.lostSalesCount.textContent = "Не рассчитано";
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 10;
    cell.textContent =
      coverage.message || "Не рассчитано: полная история остатков не получена.";
    row.append(cell);
    els.lostSalesRows.replaceChildren(row);
    return;
  }
  const sorted = [...asArray(rows)]
    .filter(
      (row) =>
        Number(row.lostContributionMargin ?? row.lostProfit ?? 0) > 0 ||
        Number(row.preventedLoss || 0) > 0 ||
        Number(row.zeroStockDays || 0) > 0,
    )
    .sort(
      (left, right) =>
        Number(right.lostContributionMargin ?? right.lostProfit ?? 0) -
          Number(left.lostContributionMargin ?? left.lostProfit ?? 0) ||
        Number(right.lostRevenue || 0) - Number(left.lostRevenue || 0),
    )
    .slice(0, 30);
  const coveragePeriod = lostSalesCoveragePeriodText(coverage);
  els.lostSalesCount.textContent = sorted.length
    ? `${sorted.length} строк${coveragePeriod ? ` · ${coveragePeriod}` : ""}`
    : coveragePeriod
      ? `Нет строк · ${coveragePeriod}`
      : "Нет строк";
  if (!sorted.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 10;
    cell.textContent = "Нет строк для предварительной оценки недополученного дохода.";
    row.append(cell);
    els.lostSalesRows.replaceChildren(row);
    return;
  }
  els.lostSalesRows.replaceChildren(
    ...sorted.map((item) => {
      const row = document.createElement("tr");
      const lostContribution = Number(
        item.lostContributionMargin ?? item.lostProfit ?? 0,
      );
      row.className = lostContribution > 0 ? "is-opportunity" : "is-review";
      appendTableCells(row, [
        { value: item.cabinet || "-", className: "text-wide" },
        { value: item.product || "-", className: "text-wide text-strong" },
        { value: item.article1c || "-", className: "text-code" },
        { value: item.barcode || "-", className: "text-code" },
        { value: number(item.zeroStockDays || 0), className: "numeric warning" },
        { value: number(item.onecStock || 0), className: "numeric" },
        { value: item.onecWarehouses || "-", className: "text-wide" },
        { value: number(item.lostUnits || 0), className: "numeric warning" },
        {
          value: item.estimateType === "prevented_loss"
            ? `Предотвращён ${money(item.preventedLoss || 0)}`
            : money(lostContribution),
          className: "numeric warning",
        },
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
    control_type: els.onecFilterControlType.value,
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
      els.onecFilterControlType.value ||
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
  params.set("limit", preset === "missingCost" ? "1000" : "50");
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
  state.rowsRequestKey = "";
  state.drilldownRequestKey = "";
  state.drilldownPreset = "review";
  state.cogsReconciliationRequestKey = "";
  state.marketplaceExpenseReconciliationRequestKey = "";
  state.onecReconciliationRequestKey = "";
  state.summary = null;
  state.freshness = null;
  state.integrationProviders = [];
  state.integrationItems = [];
  state.editingIntegrationKey = "";
  state.latestSourceRefresh = null;
  state.latestSourceRefreshAttempt = null;
  state.activeSourceRefresh = null;
  state.latestOzonDiagnostics = null;
  state.ozonDiagnosticsParams = "";
  state.mappingItemsRequestKey = "";
  updateReportBuildButton(null);
  state.aiThreadId = null;
  state.onecReconciliationLoaded = false;
  state.rowPreset = "";
  els.topbarCabinetSelect.replaceChildren();
  els.reportLoadRetryButton.hidden = true;
  els.reportLoadRetryButton.disabled = false;
  els.topbarPeriodStart.value = "";
  els.topbarPeriodEnd.value = "";
  els.rowsFilterForm.reset();
  els.onecReconciliationFilterForm.reset();
  syncRowsPresetButtons();
  resetAiPanel();
  resetSourceRefreshPanel({ hide: true });
  resetMappingServicePanel({ hide: true });
  els.integrationsPanel.hidden = true;
  syncIntegrationsEntryPoint();
  els.draftPanel.hidden = true;
  renderMetrics(els.kpiGrid, []);
  renderMetrics(els.onecKpiGrid, []);
  renderMetrics(els.qualityGrid, []);
  renderReviewRows([], 0);
  renderAnalytics({});
  renderLostSales([]);
  renderLiquidity([]);
  renderOzonPreview(null, null);
}

function syncIntegrationsEntryPoint() {
  els.integrationsOpenButton.hidden = !(state.clientId && isStaffUser());
  updateReportBuildButton(state.latestSourceRefresh);
}

function setEmptyCabinet(title = "Нет доступных отчетов", subtitle = "После импорта отчета здесь появится расчетная витрина.") {
  setTopbarNotice(title, subtitle);
  renderMetrics(els.kpiGrid, []);
  renderMetrics(els.onecKpiGrid, []);
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
  const seenIds = new Set();
  const seenLabels = new Set();
  const result = [];
  [...asArray(fallback), ...asArray(primary)].forEach((item) => {
    const id = optionValue(item);
    const labelKey = normalize(optionLabel(item));
    if ((id && seenIds.has(id)) || (labelKey && seenLabels.has(labelKey))) {
      return;
    }
    if (id) {
      seenIds.add(id);
    }
    if (labelKey) {
      seenLabels.add(labelKey);
    }
    result.push(item);
  });
  return result;
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

function financialCheckFailed(readiness = {}) {
  const financialCodes = new Set([
    "pnl_method_mismatch",
    "profit_semantics_mismatch",
    "vat_input_unconfirmed",
    "cogs_reconciliation_failed",
    "source_lineage_failed",
    "required_wb_expense_source_missing",
    "monthly_reconciliation_unresolved",
    "document_reconciliation_unresolved",
  ]);
  return asArray(readiness.blockingReasons).some((reason) =>
    financialCodes.has(reason.code),
  );
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

function isPenaltyOnlyEconomics(row = {}) {
  const classification = normalize(
    [row.lossClass, row.liquidityStatus, row.statusReason]
      .filter(Boolean)
      .join(" "),
  );
  return classification.includes("штрафной инцидент без продаж");
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
