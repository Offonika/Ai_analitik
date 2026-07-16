const STAGE_ORDER = [
  "new",
  "data_collection",
  "reports_in_progress",
  "internal_review",
  "ready_to_send",
  "sent_to_client",
  "ready_for_payroll_close",
  "rework",
  "blocked",
  "closed_payroll",
  "cancelled",
];

const STAGE_LABELS = {
  new: "Новая",
  data_collection: "Сбор данных",
  reports_in_progress: "Отчёты в работе",
  internal_review: "На проверке",
  ready_to_send: "Готово к отправке",
  sent_to_client: "Отправлено клиенту",
  ready_for_payroll_close: "Готово к закрытию",
  rework: "На доработке",
  blocked: "Заблокировано",
  closed_payroll: "Закрыто — учтено к ЗП",
  cancelled: "Отменено",
};

const TASK_LABELS = {
  month_close_control: "Контроль закрытия месяца",
  tax_load: "Налоговая нагрузка",
};

const STATUS_LABELS = {
  pending: "Ожидает",
  in_progress: "В работе",
  in_review: "На проверке",
  completed: "Завершена",
  rework: "На доработке",
  blocked: "Заблокирована",
};

const TRANSITIONS = {
  new: ["data_collection", "blocked", "cancelled"],
  data_collection: ["reports_in_progress", "blocked", "cancelled"],
  reports_in_progress: ["internal_review", "rework", "blocked", "cancelled"],
  internal_review: ["ready_to_send", "rework", "blocked", "cancelled"],
  ready_to_send: ["rework", "blocked", "cancelled"],
  sent_to_client: ["rework", "blocked", "cancelled"],
  ready_for_payroll_close: ["closed_payroll", "rework", "blocked"],
  rework: ["reports_in_progress", "blocked", "cancelled"],
  blocked: ["data_collection", "reports_in_progress", "rework", "cancelled"],
  closed_payroll: [],
  cancelled: [],
};

const state = {
  config: null,
  cards: [],
  card: null,
  view: "board",
  attachmentId: "",
  filterOptionsLoaded: false,
};

const els = {
  alert: document.querySelector("#workflow-alert"),
  filters: document.querySelector("#workflow-filters"),
  filterPeriod: document.querySelector("#filter-period"),
  filterStage: document.querySelector("#filter-stage"),
  filterClient: document.querySelector("#filter-client"),
  filterOrganization: document.querySelector("#filter-organization"),
  filterResponsible: document.querySelector("#filter-responsible"),
  filterSupervisor: document.querySelector("#filter-supervisor"),
  filterOverdue: document.querySelector("#filter-overdue"),
  refresh: document.querySelector("#workflow-refresh"),
  viewButtons: document.querySelectorAll("[data-view]"),
  board: document.querySelector("#workflow-board"),
  table: document.querySelector("#workflow-table"),
  tableRows: document.querySelector("#workflow-table-rows"),
  detail: document.querySelector("#workflow-detail"),
  detailTemplate: document.querySelector("#workflow-detail-template"),
  monthlyPanel: document.querySelector("#monthly-run-panel"),
  monthlyForm: document.querySelector("#monthly-run-form"),
  monthlyPeriod: document.querySelector("#monthly-period"),
  monthlyResponsible: document.querySelector("#monthly-responsible"),
  monthlySupervisor: document.querySelector("#monthly-supervisor"),
};

document.addEventListener("DOMContentLoaded", boot);

async function boot() {
  bindEvents();
  const currentMonth = new Date().toISOString().slice(0, 7);
  els.monthlyPeriod.value = currentMonth;
  try {
    state.config = await api("/api/accounting-workflows/config");
    renderConfig();
    await loadCards();
  } catch (error) {
    if (error.status === 401) {
      window.location.assign("/cabinet");
      return;
    }
    showAlert(error.message || "Смарт-процесс недоступен.", true);
  }
}

function bindEvents() {
  els.filters.addEventListener("submit", (event) => {
    event.preventDefault();
    loadCards();
  });
  els.refresh.addEventListener("click", loadCards);
  els.monthlyForm.addEventListener("submit", createMonthlyRun);
  els.viewButtons.forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view || "board"));
  });
  els.board.addEventListener("click", onCardClick);
  els.tableRows.addEventListener("click", onCardClick);
}

function renderConfig() {
  const users = state.config.staffUsers || [];
  const consultants = users.filter((item) => item.role === "consultant");
  const supervisors = users.filter((item) => item.workflowSupervisor);
  fillSelect(
    els.filterResponsible,
    consultants,
    "Все сотрудники",
  );
  fillSelect(els.monthlyResponsible, consultants, "Выберите ответственного");
  fillSelect(els.monthlySupervisor, supervisors, "Выберите руководителя");
  fillSelect(els.filterSupervisor, supervisors, "Все руководители");
  STAGE_ORDER.forEach((stage) => {
    const option = document.createElement("option");
    option.value = stage;
    option.textContent = STAGE_LABELS[stage];
    els.filterStage.append(option);
  });
  els.monthlyPanel.hidden = !state.config.isSupervisor;
}

function fillSelect(select, users, emptyLabel) {
  select.replaceChildren();
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = emptyLabel;
  select.append(empty);
  users.forEach((user) => {
    const option = document.createElement("option");
    option.value = user.id;
    option.textContent = user.name || user.email;
    select.append(option);
  });
}

async function loadCards() {
  const params = new URLSearchParams({ tenantId: state.config.tenantId });
  if (els.filterPeriod.value) params.set("periodMonth", els.filterPeriod.value);
  if (els.filterStage.value) params.set("stage", els.filterStage.value);
  if (els.filterClient.value) params.set("clientId", els.filterClient.value);
  if (els.filterOrganization.value) {
    params.set("organizationId", els.filterOrganization.value);
  }
  if (els.filterResponsible.value) {
    params.set("responsibleUserId", els.filterResponsible.value);
  }
  if (els.filterSupervisor.value) {
    params.set("supervisorUserId", els.filterSupervisor.value);
  }
  if (els.filterOverdue.checked) params.set("overdue", "true");
  try {
    const payload = await api(`/api/accounting-workflows?${params}`);
    state.cards = payload.items || [];
    if (!state.filterOptionsLoaded && state.cards.length) {
      fillEntitySelect(
        els.filterClient,
        state.cards,
        "clientId",
        "clientName",
        "Все клиенты",
      );
      fillEntitySelect(
        els.filterOrganization,
        state.cards,
        "organizationId",
        "organizationName",
        "Все организации",
      );
      state.filterOptionsLoaded = true;
    }
    renderCards();
    showAlert(`Карточек: ${state.cards.length}`);
  } catch (error) {
    showAlert(error.message || "Не удалось загрузить карточки.", true);
  }
}

function fillEntitySelect(select, cards, idField, labelField, emptyLabel) {
  const options = new Map();
  cards.forEach((card) => {
    if (card[idField]) options.set(card[idField], card[labelField] || card[idField]);
  });
  select.replaceChildren();
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = emptyLabel;
  select.append(empty);
  [...options.entries()]
    .sort((left, right) => left[1].localeCompare(right[1], "ru"))
    .forEach(([id, label]) => {
      const option = document.createElement("option");
      option.value = id;
      option.textContent = label;
      select.append(option);
    });
}

function renderCards() {
  renderBoard();
  renderTable();
}

function renderBoard() {
  els.board.replaceChildren();
  const stages = els.filterStage.value ? [els.filterStage.value] : STAGE_ORDER;
  stages.forEach((stage) => {
    const items = state.cards.filter((card) => card.stage === stage);
    const column = document.createElement("section");
    column.className = "kanban-column";
    column.innerHTML = `
      <div class="kanban-column-heading">
        <span>${escapeHtml(STAGE_LABELS[stage] || stage)}</span>
        <span class="kanban-count">${items.length}</span>
      </div>
      <div class="kanban-cards"></div>
    `;
    const list = column.querySelector(".kanban-cards");
    items.forEach((card) => list.append(buildCardButton(card)));
    els.board.append(column);
  });
}

function buildCardButton(card) {
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.cardId = card.id;
  button.className = [
    "workflow-card",
    card.overdue ? "overdue" : "",
    card.hardOverdue ? "hard-overdue" : "",
  ].filter(Boolean).join(" ");
  const taskStatuses = (card.tasks || []).map(
    (task) => `<span class="task-chip">${escapeHtml(shortTask(task.reportKind))}: ${escapeHtml(STATUS_LABELS[task.status] || task.status)}</span>`,
  ).join("");
  button.innerHTML = `
    <span class="card-title">${escapeHtml(card.clientName)}</span>
    <span>${escapeHtml(card.organizationName)}</span>
    <span class="card-meta">${escapeHtml(card.periodMonth)} · ${escapeHtml(card.responsibleName || "не назначен")}</span>
    <span class="card-meta">Срок: ${escapeHtml(formatDate(card.targetDueAt))}</span>
    <span class="task-statuses">${taskStatuses}</span>
  `;
  return button;
}

function renderTable() {
  els.tableRows.replaceChildren();
  state.cards.forEach((card) => {
    const row = document.createElement("tr");
    row.dataset.cardId = card.id;
    row.tabIndex = 0;
    row.innerHTML = `
      <td>${escapeHtml(card.clientName)}</td>
      <td>${escapeHtml(card.organizationName)}</td>
      <td>${escapeHtml(card.periodMonth)}</td>
      <td>${escapeHtml(STAGE_LABELS[card.stage] || card.stage)}</td>
      <td>${escapeHtml(card.responsibleName || "Не назначен")}</td>
      <td>${escapeHtml(formatDate(card.targetDueAt))}</td>
      <td>${(card.tasks || []).map((task) => escapeHtml(`${shortTask(task.reportKind)}: ${STATUS_LABELS[task.status] || task.status}`)).join("<br>")}</td>
    `;
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openCard(card.id);
      }
    });
    els.tableRows.append(row);
  });
}

function setView(view) {
  state.view = view;
  els.board.hidden = view !== "board";
  els.table.hidden = view !== "table";
  els.viewButtons.forEach((button) => {
    button.setAttribute("aria-pressed", button.dataset.view === view ? "true" : "false");
  });
}

function onCardClick(event) {
  const target = event.target.closest("[data-card-id]");
  if (target) openCard(target.dataset.cardId || "");
}

async function openCard(cardId) {
  if (!cardId) return;
  try {
    const payload = await api(`/api/accounting-workflows/${encodeURIComponent(cardId)}`);
    state.card = payload.item;
    state.attachmentId = "";
    renderDetail();
  } catch (error) {
    showAlert(error.message || "Не удалось открыть карточку.", true);
  }
}

function renderDetail() {
  const card = state.card;
  if (!card) {
    els.detail.innerHTML = `<div class="empty-state"><h2>Карточка не выбрана</h2><p>Откройте карточку в Канбане или таблице.</p></div>`;
    return;
  }
  const fragment = els.detailTemplate.content.cloneNode(true);
  setField(fragment, "period", card.periodMonth);
  setField(fragment, "title", `${card.clientName} · ${card.organizationName}`);
  setField(fragment, "stage", STAGE_LABELS[card.stage] || card.stage);
  setField(fragment, "responsible", card.responsibleName || "Не назначен");
  setField(fragment, "supervisor", card.supervisorName || "Не назначен");
  setField(fragment, "target-due", formatDateTime(card.targetDueAt));
  setField(fragment, "hard-due", formatDateTime(card.hardDueAt));
  renderTransitionForm(fragment, card);
  renderTasks(fragment, card);
  renderDeliveries(fragment, card.deliveries || []);
  renderFollowups(fragment, card.followups || []);
  renderComments(fragment, card.comments || []);
  renderAudit(fragment, card.auditEvents || []);
  bindDetailEvents(fragment, card);
  els.detail.replaceChildren(fragment);
}

function renderTransitionForm(root, card) {
  const form = root.querySelector('[data-form="transition"]');
  const stageSelect = form.elements.targetStage;
  stageSelect.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Выберите следующую стадию";
  stageSelect.append(placeholder);
  (TRANSITIONS[card.stage] || []).forEach((stage) => {
    const option = document.createElement("option");
    option.value = stage;
    option.textContent = STAGE_LABELS[stage] || stage;
    stageSelect.append(option);
  });
  const users = state.config.staffUsers || [];
  appendUsers(
    form.elements.responsibleUserId,
    users.filter((item) => item.role === "consultant"),
    card.responsibleUserId,
  );
  appendUsers(
    form.elements.supervisorUserId,
    users.filter((item) => item.workflowSupervisor),
    card.supervisorUserId,
  );
  if (!(TRANSITIONS[card.stage] || []).length) form.hidden = true;
}

function appendUsers(select, users, selectedId) {
  users.forEach((user) => {
    const option = document.createElement("option");
    option.value = user.id;
    option.textContent = user.name || user.email;
    option.selected = user.id === selectedId;
    select.append(option);
  });
}

function renderTasks(root, card) {
  const container = root.querySelector('[data-field="tasks"]');
  (card.tasks || []).forEach((task) => {
    const item = document.createElement("article");
    item.className = "task-item";
    item.dataset.taskId = task.id;
    const taxActions = task.reportKind === "tax_load"
      ? `
        <button type="button" data-task-action="confirm_facts">Подтвердить факты</button>
        <button type="button" data-task-action="approve_text">Утвердить текст</button>
        <button type="button" data-task-action="mark_final">Отметить финальным</button>
      `
      : "";
    item.innerHTML = `
      <strong>${escapeHtml(TASK_LABELS[task.reportKind] || task.reportKind)}</strong>
      <p class="muted">${escapeHtml(STATUS_LABELS[task.status] || task.status)} · ${task.reportId ? `report_id ${escapeHtml(task.reportId)}` : "ревизия не привязана"}</p>
      <div class="stack-form">
        <input name="reportId" placeholder="report_id" value="${escapeAttribute(task.reportId || "")}" />
        <input name="payloadSha256" placeholder="payloadSha256 — необязательно" value="${escapeAttribute(task.payloadSha256 || "")}" />
        <button type="button" class="secondary" data-task-action="attach_revision">Привязать ревизию</button>
      </div>
      <div class="task-actions">
        <button type="button" data-task-action="start">В работу</button>
        <button type="button" data-task-action="submit_review">На проверку</button>
        ${taxActions}
        <button type="button" data-task-action="complete">Завершить</button>
        <button type="button" class="secondary" data-task-action="rework">Доработать</button>
        <button type="button" class="secondary" data-task-action="block">Заблокировать</button>
      </div>
    `;
    container.append(item);
  });
}

function renderDeliveries(root, items) {
  const container = root.querySelector('[data-field="deliveries"]');
  if (!items.length) {
    container.innerHTML = '<p class="muted">Отправки ещё не зафиксированы.</p>';
    return;
  }
  items.forEach((item) => {
    const node = document.createElement("div");
    node.className = "timeline-item";
    const attachment = item.attachment
      ? `<a href="/api/accounting-workflows/evidence/${encodeURIComponent(item.attachment.id)}">${escapeHtml(item.attachment.name)}</a>`
      : "нет файла";
    node.innerHTML = `
      <strong>${item.preliminary ? "Предварительная" : "Финальная"} отправка</strong>
      <div>${escapeHtml(formatDateTime(item.sentAt))} · ${escapeHtml(item.channel)}</div>
      <div>${escapeHtml(item.maskedRecipient)} · ${attachment}</div>
      ${item.invalidatedAt ? `<div class="muted">Аннулировано: ${escapeHtml(item.invalidationReason)}</div>` : ""}
    `;
    container.append(node);
  });
}

function renderFollowups(root, items) {
  const container = root.querySelector('[data-field="followups"]');
  if (!items.length) {
    container.innerHTML = '<p class="muted">Контрольных контактов нет.</p>';
    return;
  }
  items.forEach((item) => {
    const node = document.createElement("div");
    node.className = "timeline-item";
    node.dataset.followupId = item.id;
    node.innerHTML = `
      <strong>${escapeHtml(item.status)}</strong>
      <div>Срок: ${escapeHtml(formatDateTime(item.dueAt))}</div>
      <div>${escapeHtml(item.result || "Результат ещё не внесён")}</div>
      ${item.status !== "completed" ? `
        <div class="task-actions">
          <button type="button" data-followup-action="repeat">Повторный контакт</button>
          <button type="button" data-followup-action="complete">Завершить</button>
        </div>
      ` : ""}
    `;
    container.append(node);
  });
}

function renderComments(root, items) {
  const container = root.querySelector('[data-field="comments"]');
  if (!items.length) {
    container.innerHTML = '<p class="muted">Комментариев нет.</p>';
    return;
  }
  items.forEach((item) => {
    const node = document.createElement("div");
    node.className = "timeline-item";
    node.innerHTML = `<strong>${escapeHtml(item.userName || "Сотрудник")}</strong><div>${escapeHtml(item.body)}</div><div class="muted">${escapeHtml(formatDateTime(item.createdAt))}</div>`;
    container.append(node);
  });
}

function renderAudit(root, items) {
  const container = root.querySelector('[data-field="audit"]');
  items.slice().reverse().forEach((item) => {
    const node = document.createElement("div");
    node.className = "timeline-item";
    node.innerHTML = `<strong>${escapeHtml(item.action)}</strong><div>${escapeHtml(item.userName)} · ${escapeHtml(formatDateTime(item.createdAt))}</div>`;
    container.append(node);
  });
}

function bindDetailEvents(root, card) {
  root.querySelector('[data-action="close-detail"]').addEventListener("click", () => {
    state.card = null;
    renderDetail();
  });
  root.querySelector('[data-form="transition"]').addEventListener("submit", transitionCard);
  root.querySelector('[data-field="tasks"]').addEventListener("click", onTaskAction);
  root.querySelector('[data-form="evidence"]').addEventListener("submit", uploadEvidence);
  root.querySelector('[data-form="delivery"]').addEventListener("submit", recordDelivery);
  root.querySelector('[data-form="comment"]').addEventListener("submit", addComment);
  root.querySelector('[data-field="followups"]').addEventListener("click", onFollowupAction);
  const deliveryForm = root.querySelector('[data-form="delivery"]');
  deliveryForm.elements.sentAt.value = toLocalDateTime(new Date());
  deliveryForm.elements.attachmentId.value = state.attachmentId;
  if (["closed_payroll", "cancelled"].includes(card.stage)) {
    root.querySelector('[data-form="transition"]').hidden = true;
  }
}

async function createMonthlyRun(event) {
  event.preventDefault();
  await mutate("/api/accounting-workflows/monthly-runs", {
    periodMonth: els.monthlyPeriod.value,
    tenantId: state.config.tenantId,
    responsibleUserId: els.monthlyResponsible.value,
    supervisorUserId: els.monthlySupervisor.value,
  }, "Карточки месяца созданы без дублей.");
  await loadCards();
}

async function transitionCard(event) {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  await mutate(`/api/accounting-workflows/${encodeURIComponent(state.card.id)}/transitions`, {
    targetStage: data.get("targetStage"),
    reason: data.get("reason"),
    responsibleUserId: data.get("responsibleUserId") || null,
    supervisorUserId: data.get("supervisorUserId") || null,
  }, "Стадия обновлена.");
  await refreshSelectedCard();
}

async function onTaskAction(event) {
  const button = event.target.closest("[data-task-action]");
  if (!button) return;
  const task = button.closest("[data-task-id]");
  const action = button.dataset.taskAction;
  const reason = ["rework", "block"].includes(action)
    ? window.prompt("Укажите причину") || ""
    : "";
  if (["rework", "block"].includes(action) && !reason) return;
  await mutate(
    `/api/accounting-workflows/${encodeURIComponent(state.card.id)}/tasks/${encodeURIComponent(task.dataset.taskId)}/actions`,
    {
      action,
      reportId: task.querySelector('[name="reportId"]').value || null,
      payloadSha256: task.querySelector('[name="payloadSha256"]').value || null,
      reason,
    },
    "Задача обновлена.",
  );
  await refreshSelectedCard();
}

async function uploadEvidence(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const file = form.elements.evidence.files[0];
  if (!file) return;
  const body = new FormData();
  body.append("evidence", file);
  try {
    const payload = await api(
      `/api/accounting-workflows/${encodeURIComponent(state.card.id)}/evidence`,
      { method: "POST", body, csrf: true },
    );
    state.attachmentId = payload.attachment.id;
    form.querySelector('[data-field="attachment-status"]').textContent = `Загружено: ${payload.attachment.name}`;
    els.detail.querySelector('[data-form="delivery"] [name="attachmentId"]').value = state.attachmentId;
    showAlert("Доказательство загружено.");
  } catch (error) {
    showAlert(error.message || "Не удалось загрузить доказательство.", true);
  }
}

async function recordDelivery(event) {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  if (!data.get("attachmentId")) {
    showAlert("Сначала загрузите доказательство отправки.", true);
    return;
  }
  await mutate(`/api/accounting-workflows/${encodeURIComponent(state.card.id)}/deliveries`, {
    sentAt: new Date(data.get("sentAt")).toISOString(),
    channel: data.get("channel"),
    channelDetail: data.get("channelDetail"),
    maskedRecipient: data.get("maskedRecipient"),
    attachmentId: data.get("attachmentId"),
    contactResult: data.get("contactResult"),
    preliminary: data.get("preliminary") === "on",
  }, "Отправка зафиксирована.");
  await refreshSelectedCard();
}

async function addComment(event) {
  event.preventDefault();
  const form = event.currentTarget;
  await mutate(`/api/accounting-workflows/${encodeURIComponent(state.card.id)}/comments`, {
    body: new FormData(form).get("body"),
  }, "Комментарий добавлен.");
  await refreshSelectedCard();
}

async function onFollowupAction(event) {
  const button = event.target.closest("[data-followup-action]");
  if (!button) return;
  const item = button.closest("[data-followup-id]");
  const result = window.prompt("Результат контрольного контакта") || "";
  if (!result) return;
  await mutate(
    `/api/accounting-workflows/${encodeURIComponent(state.card.id)}/followups/${encodeURIComponent(item.dataset.followupId)}/actions`,
    { action: button.dataset.followupAction, result },
    "Контрольный контакт обновлён.",
  );
  await refreshSelectedCard();
}

async function refreshSelectedCard() {
  const cardId = state.card?.id;
  await loadCards();
  if (cardId) await openCard(cardId);
}

async function mutate(url, payload, successMessage) {
  try {
    await api(url, {
      method: "POST",
      body: JSON.stringify(payload),
      csrf: true,
    });
    showAlert(successMessage);
  } catch (error) {
    showAlert(error.message || "Операция не выполнена.", true);
    throw error;
  }
}

async function api(url, options = {}) {
  const isForm = options.body instanceof FormData;
  const headers = { ...(options.headers || {}) };
  if (!isForm) headers["Content-Type"] = "application/json";
  if (options.csrf) headers["X-CSRF-Token"] = state.config?.csrfToken || "";
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
    headers,
  });
  if (!response.ok) {
    const detail = await readError(response);
    const error = new Error(detail || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

async function readError(response) {
  try {
    const payload = await response.json();
    return typeof payload.detail === "string" ? payload.detail : "";
  } catch (error) {
    return "";
  }
}

function setField(root, name, value) {
  const node = root.querySelector(`[data-field="${name}"]`);
  if (node) node.textContent = value || "—";
}

function showAlert(message, isError = false) {
  els.alert.hidden = false;
  els.alert.classList.toggle("error", isError);
  els.alert.textContent = message;
}

function shortTask(reportKind) {
  return reportKind === "tax_load" ? "Налоги" : "Закрытие";
}

function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "short" }).format(new Date(value));
}

function formatDateTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

function toLocalDateTime(value) {
  const offset = value.getTimezoneOffset() * 60000;
  return new Date(value.getTime() - offset).toISOString().slice(0, 16);
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value);
}
