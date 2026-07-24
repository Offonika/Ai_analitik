(() => {
  const renderers = new Map();

  function node(tag, className = "", text = "") {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== "") item.textContent = String(text);
    return item;
  }

  function value(value, fallback = "Не подтверждено") {
    return value === null || value === undefined || value === "" ? fallback : String(value);
  }

  const STATUS_LABELS = {
    preliminary: "Предварительный",
    accountant_review_required: "Требуется проверка бухгалтера",
    accountant_confirmed: "Подтверждено бухгалтером",
    review_required: "Требуется проверка",
    cannot_confirm: "Нельзя подтвердить",
    partial_source: "Неполный источник",
    source_coverage_gap: "Не хватает источников",
    loaded: "Загружено",
    confirmed: "Подтверждено",
    ready: "Готово",
    warning: "Требует внимания",
    failed: "Ошибка источника",
    missing: "Не получено",
    not_confirmed: "Не подтверждено",
    empty_expected: "Нет данных — допустимо",
    draft_reference: "Черновик для проверки",
    informational: "Информационно",
    not_checked: "Не проверено",
  };

  function localizeStatus(rawValue, fallback = "Не подтверждено") {
    const normalized = String(rawValue || "").trim().toLowerCase();
    return normalized ? (STATUS_LABELS[normalized] || normalized.replaceAll("_", " ")) : fallback;
  }

  function formatDate(rawValue, fallback = "Не указан") {
    const normalized = String(rawValue || "").trim();
    const match = normalized.match(/^(\d{4})-(\d{2})-(\d{2})/);
    return match ? `${match[3]}.${match[2]}.${match[1]}` : value(rawValue, fallback);
  }

  function formatMoney(rawValue, fallback = "Не подтверждено") {
    if (rawValue === null || rawValue === undefined || rawValue === "") return fallback;
    const parsed = Number(String(rawValue).replace(",", "."));
    if (!Number.isFinite(parsed)) return value(rawValue, fallback);
    return `${new Intl.NumberFormat("ru-RU", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }).format(parsed)} ₽`;
  }

  function metricGrid(items) {
    const grid = node("div", "scenario-metric-grid");
    items.forEach(([label, rawValue, tone = ""]) => {
      const card = node("article", `scenario-metric ${tone}`.trim());
      card.append(node("span", "scenario-metric-label", label));
      card.append(node("strong", "scenario-metric-value", value(rawValue)));
      grid.append(card);
    });
    return grid;
  }

  function table(rows, options = {}) {
    const source = Array.isArray(rows) ? rows : [];
    if (!source.length) {
      return node("p", "analytics-empty", options.emptyText || "Нет подтверждённых данных.");
    }
    const rawHeaders = [];
    source.forEach((row) => Object.keys(row || {}).forEach((key) => {
      if (!rawHeaders.includes(key)) rawHeaders.push(key);
    }));
    const columns = Array.isArray(options.columns) && options.columns.length
      ? options.columns
      : rawHeaders.map((key) => ({ key, label: key }));
    const mobileColumns = Array.isArray(options.mobileColumns) && options.mobileColumns.length
      ? options.mobileColumns
      : columns;
    const label = options.ariaLabel || options.caption || "Таблица данных";
    const wrapper = node(
      "div",
      `table-wrap scenario-table-wrap ${options.mobileCards ? "has-mobile-cards" : ""}`.trim(),
    );
    wrapper.tabIndex = 0;
    wrapper.setAttribute("role", "region");
    wrapper.setAttribute("aria-label", label);
    const element = node(
      "table",
      `data-table scenario-table ${options.className || ""}`.trim(),
    );
    const caption = node("caption", "scenario-table-caption", label);
    const head = node("thead");
    const headRow = node("tr");
    columns.forEach((column) => {
      const cell = node("th", column.className || "", column.label || column.key);
      cell.scope = "col";
      headRow.append(cell);
    });
    head.append(headRow);
    const body = node("tbody");
    source.forEach((row) => {
      const line = node("tr");
      columns.forEach((column) => {
        const rawValue = typeof column.value === "function"
          ? column.value(row || {})
          : row?.[column.key];
        const formatted = typeof column.format === "function"
          ? column.format(rawValue)
          : value(rawValue, column.fallback || "—");
        line.append(node("td", column.className || "", formatted));
      });
      body.append(line);
    });
    element.append(caption, head, body);
    wrapper.append(element);
    if (options.mobileCards) {
      const cards = node("div", "scenario-mobile-cards");
      source.forEach((row) => {
        const card = node("article", "scenario-mobile-card");
        const details = node("dl");
        mobileColumns.forEach((column) => {
          const rawValue = typeof column.value === "function"
            ? column.value(row || {})
            : row?.[column.key];
          const formatted = typeof column.format === "function"
            ? column.format(rawValue)
            : value(rawValue, column.fallback || "—");
          details.append(
            node("dt", "", column.label || column.key),
            node("dd", column.className || "", formatted),
          );
        });
        card.append(details);
        cards.append(card);
      });
      wrapper.append(cards);
    }
    return wrapper;
  }

  function title(text, status = "") {
    const header = node("div", "scenario-heading");
    header.append(node("h2", "", text));
    if (status) header.append(node("span", "status-pill", localizeStatus(status)));
    return header;
  }

  window.MultiReportScenarios = {
    helpers: {
      formatDate,
      formatMoney,
      localizeStatus,
      metricGrid,
      node,
      table,
      title,
      value,
    },
    register(kind, renderer) {
      renderers.set(kind, renderer);
    },
    clear(panels) {
      Object.values(panels).forEach((panel) => panel?.replaceChildren());
    },
    render(kind, payload, panels, context = {}) {
      this.clear(panels);
      const renderer = renderers.get(kind);
      if (!renderer) throw new Error(`Unsupported report scenario: ${kind}`);
      renderer(payload || {}, panels, context);
    },
  };
})();
