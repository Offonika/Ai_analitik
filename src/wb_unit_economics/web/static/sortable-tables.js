(function sortableTablesModule() {
  "use strict";

  const HEADER_SELECTOR = "table thead th";
  const INTERACTIVE_SELECTOR = "a, button, input, select, textarea, [role='button']";
  const EMPTY_VALUES = new Set(["", "-", "–", "—", "n/a", "null"]);
  const tableState = new WeakMap();
  const scheduledTables = new WeakSet();
  const collator = new Intl.Collator("ru", {
    numeric: true,
    sensitivity: "base",
  });

  function normalizedText(value) {
    return String(value ?? "")
      .replace(/[\u00a0\u202f]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function validUtcTimestamp(year, month, day, hour = 0, minute = 0) {
    const timestamp = Date.UTC(year, month - 1, day, hour, minute);
    const date = new Date(timestamp);
    if (
      date.getUTCFullYear() !== year ||
      date.getUTCMonth() !== month - 1 ||
      date.getUTCDate() !== day ||
      date.getUTCHours() !== hour ||
      date.getUTCMinutes() !== minute
    ) {
      return null;
    }
    return timestamp;
  }

  function dateValue(text) {
    const russianDate = text.match(
      /^(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})(?:,?\s+(\d{1,2}):(\d{2}))?$/,
    );
    if (russianDate) {
      let year = Number(russianDate[3]);
      if (year < 100) {
        year += 2000;
      }
      return validUtcTimestamp(
        year,
        Number(russianDate[2]),
        Number(russianDate[1]),
        Number(russianDate[4] || 0),
        Number(russianDate[5] || 0),
      );
    }

    const isoDate = text.match(
      /^(\d{4})-(\d{2})(?:-(\d{2}))?(?:[T\s](\d{2}):(\d{2})(?::\d{2})?)?$/,
    );
    if (!isoDate) {
      return null;
    }
    return validUtcTimestamp(
      Number(isoDate[1]),
      Number(isoDate[2]),
      Number(isoDate[3] || 1),
      Number(isoDate[4] || 0),
      Number(isoDate[5] || 0),
    );
  }

  function numericValue(text) {
    let candidate = text.replace(/−/g, "-").trim();
    const negativeInParentheses = /^\(.*\)$/.test(candidate);
    if (negativeInParentheses) {
      candidate = candidate.slice(1, -1);
    }
    candidate = candidate
      .replace(/[₽$€%]/g, "")
      .replace(/\s+/g, "")
      .replace(",", ".");
    if (!/^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$/.test(candidate)) {
      return null;
    }
    const value = Number(candidate);
    if (!Number.isFinite(value)) {
      return null;
    }
    return negativeInParentheses ? -Math.abs(value) : value;
  }

  function parseSortValue(value) {
    const text = normalizedText(value);
    if (EMPTY_VALUES.has(text.toLocaleLowerCase("ru"))) {
      return { kind: "empty", raw: text, value: null };
    }

    const date = dateValue(text);
    if (date !== null) {
      return { kind: "date", raw: text, value: date };
    }

    const numeric = numericValue(text);
    if (numeric !== null) {
      return { kind: "number", raw: text, value: numeric };
    }

    return { kind: "string", raw: text, value: text };
  }

  function logicalColumnIndex(header) {
    let index = 0;
    for (const cell of header.parentElement?.cells || []) {
      if (cell === header) {
        return index;
      }
      index += Math.max(1, Number(cell.colSpan) || 1);
    }
    return Math.max(0, header.cellIndex);
  }

  function cellAtColumn(row, columnIndex) {
    let index = 0;
    for (const cell of row.cells) {
      const span = Math.max(1, Number(cell.colSpan) || 1);
      if (columnIndex >= index && columnIndex < index + span) {
        return cell;
      }
      index += span;
    }
    return null;
  }

  function rowSortValue(row, columnIndex) {
    const cell = cellAtColumn(row, columnIndex);
    if (!cell || (row.cells.length === 1 && Number(cell.colSpan) > 1)) {
      return parseSortValue("");
    }
    const value = Object.hasOwn(cell.dataset, "sortValue")
      ? cell.dataset.sortValue
      : cell.textContent;
    return parseSortValue(value);
  }

  function compareValues(left, right, direction) {
    if (left.kind === "empty" || right.kind === "empty") {
      if (left.kind === right.kind) {
        return 0;
      }
      return left.kind === "empty" ? 1 : -1;
    }

    let result;
    if (left.kind === right.kind && left.kind !== "string") {
      result = left.value - right.value;
    } else {
      result = collator.compare(left.raw, right.raw);
    }
    return direction === "descending" ? -result : result;
  }

  function sortBody(tbody, columnIndex, direction) {
    const rows = Array.from(tbody.rows);
    const sorted = rows
      .map((row, originalIndex) => ({
        originalIndex,
        row,
        value: rowSortValue(row, columnIndex),
      }))
      .sort((left, right) => {
        const compared = compareValues(left.value, right.value, direction);
        return compared || left.originalIndex - right.originalIndex;
      });

    if (sorted.every((item, index) => item.row === rows[index])) {
      return;
    }
    const fragment = document.createDocumentFragment();
    sorted.forEach((item) => fragment.append(item.row));
    tbody.append(fragment);
  }

  function headerLabel(header) {
    let indicator = Array.from(header.children).find((child) =>
      child.classList.contains("table-sort-indicator"),
    );
    if (!indicator) {
      header.dataset.sortLabel = normalizedText(header.textContent) || "Колонка";
      indicator = document.createElement("span");
      indicator.className = "table-sort-indicator";
      indicator.setAttribute("aria-hidden", "true");
      header.append(indicator);
    }
    return header.dataset.sortLabel || "Колонка";
  }

  function updateHeaderState(table) {
    const state = tableState.get(table);
    table.querySelectorAll("thead th").forEach((header) => {
      const label = headerLabel(header);
      const indicator = header.querySelector(":scope > .table-sort-indicator");
      const isActive = state?.columnIndex === logicalColumnIndex(header);
      header.classList.add("sortable-table-header");
      header.tabIndex = 0;
      if (isActive) {
        header.setAttribute("aria-sort", state.direction);
        indicator.textContent = state.direction === "ascending" ? "▲" : "▼";
        header.setAttribute(
          "aria-label",
          `${label}. Отсортировано ${
            state.direction === "ascending" ? "по возрастанию" : "по убыванию"
          }. Сортировать ${
            state.direction === "ascending" ? "по убыванию" : "по возрастанию"
          }`,
        );
      } else {
        header.removeAttribute("aria-sort");
        indicator.textContent = "↕";
        header.setAttribute("aria-label", `${label}. Сортировать по возрастанию`);
      }
    });
  }

  function sortTable(table, columnIndex, direction) {
    tableState.set(table, { columnIndex, direction });
    Array.from(table.tBodies).forEach((tbody) =>
      sortBody(tbody, columnIndex, direction),
    );
    updateHeaderState(table);
  }

  function activateHeader(header) {
    if (header.dataset.sortDisabled === "true") {
      return;
    }
    const table = header.closest("table");
    if (!table) {
      return;
    }
    const columnIndex = logicalColumnIndex(header);
    const current = tableState.get(table);
    const direction =
      current?.columnIndex === columnIndex && current.direction === "ascending"
        ? "descending"
        : "ascending";
    sortTable(table, columnIndex, direction);
  }

  function enhanceTable(table) {
    updateHeaderState(table);
  }

  function enhanceTables(root) {
    if (root instanceof Element && root.matches("table")) {
      enhanceTable(root);
    }
    root.querySelectorAll?.("table").forEach(enhanceTable);
  }

  function scheduleActiveSort(table) {
    if (!tableState.has(table) || scheduledTables.has(table)) {
      return;
    }
    scheduledTables.add(table);
    queueMicrotask(() => {
      scheduledTables.delete(table);
      const state = tableState.get(table);
      if (state && table.isConnected) {
        sortTable(table, state.columnIndex, state.direction);
      }
    });
  }

  function handleMutations(mutations) {
    mutations.forEach((mutation) => {
      const target =
        mutation.target instanceof Element
          ? mutation.target
          : mutation.target.parentElement;
      const table = target?.closest("table");
      if (table) {
        enhanceTable(table);
        if (target.closest("tbody")) {
          scheduleActiveSort(table);
        }
      }
      mutation.addedNodes.forEach((node) => {
        if (node instanceof Element) {
          enhanceTables(node);
        }
      });
    });
  }

  function start() {
    enhanceTables(document);
    document.addEventListener("click", (event) => {
      if (!(event.target instanceof Element)) {
        return;
      }
      const header = event.target.closest(HEADER_SELECTOR);
      if (!header || event.target.closest(INTERACTIVE_SELECTOR)) {
        return;
      }
      activateHeader(header);
    });
    document.addEventListener("keydown", (event) => {
      if (!(event.target instanceof Element)) {
        return;
      }
      const header = event.target.closest(HEADER_SELECTOR);
      if (
        !header ||
        event.target !== header ||
        (event.key !== "Enter" && event.key !== " ")
      ) {
        return;
      }
      event.preventDefault();
      activateHeader(header);
    });
    new MutationObserver(handleMutations).observe(document.body, {
      childList: true,
      subtree: true,
    });
  }

  window.SortableTables = Object.freeze({
    compareValues,
    parseSortValue,
    sortTable,
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
