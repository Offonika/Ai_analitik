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
      return node(
        "p",
        "analytics-empty",
        options.emptyText || "Нет подтверждённых данных.",
      );
    }
    const keys = [];
    source.forEach((row) => Object.keys(row || {}).forEach((key) => {
      if (!keys.includes(key)) keys.push(key);
    }));
    const columns = Array.isArray(options.columns) && options.columns.length
      ? options.columns
      : keys.map((key) => ({ key, label: key }));
    const wrapper = node("div", "table-wrap scenario-table-wrap");
    wrapper.tabIndex = 0;
    if (options.label) wrapper.setAttribute("aria-label", options.label);
    const element = node("table", "data-table scenario-table");
    const head = node("thead");
    const headRow = node("tr");
    columns.forEach((column) => {
      const header = node("th", "", column.label || column.key);
      header.scope = "col";
      headRow.append(header);
    });
    head.append(headRow);
    const body = node("tbody");
    source.forEach((row) => {
      const line = node("tr");
      columns.forEach((column) => {
        const rawValue = row?.[column.key];
        const displayValue = typeof column.format === "function"
          ? column.format(rawValue, row)
          : value(rawValue, "—");
        const cell = node("td", "", value(displayValue, "—"));
        cell.dataset.label = column.label || column.key;
        line.append(cell);
      });
      body.append(line);
    });
    element.append(head, body);
    wrapper.append(element);
    return wrapper;
  }

  function title(text, status = "") {
    const header = node("div", "scenario-heading");
    header.append(node("h2", "", text));
    if (status) header.append(node("span", "status-pill", status));
    return header;
  }

  window.MultiReportScenarios = {
    helpers: { metricGrid, node, table, title, value },
    register(kind, renderer) {
      renderers.set(kind, renderer);
    },
    clear(panels) {
      Object.values(panels).forEach((panel) => panel?.replaceChildren());
    },
    render(kind, payload, panels) {
      this.clear(panels);
      const renderer = renderers.get(kind);
      if (!renderer) throw new Error(`Unsupported report scenario: ${kind}`);
      renderer(payload || {}, panels);
    },
  };
})();
