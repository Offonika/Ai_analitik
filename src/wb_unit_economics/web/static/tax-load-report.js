(() => {
  const registry = window.MultiReportScenarios;
  if (!registry) return;
  const { metricGrid, node, table, title, value } = registry.helpers;

  const STATUS_LABELS = {
    accountant_review_required: "Нужна проверка бухгалтера",
    preliminary: "Предварительный",
    confirmed: "Подтверждено",
    loaded: "Загружено",
    missing: "Нет данных",
    partial: "Загружено частично",
    partial_source: "Источник неполный",
    source_gap: "Недостаточно данных",
    informational: "Справочно",
    ready: "Готово",
    warning: "Нужно проверить",
  };

  const SOURCE_LABELS = {
    onec_tax: "Налоговый учёт 1С",
    onec_osv: "ОСВ 1С",
    onec_official_financial_results: "Отчёт о финансовых результатах 1С",
    onec_bank: "Банк в 1С",
    onec_accounting_bank_in: "Банковские поступления 1С",
    onec_accounting_counterparties: "Справочник контрагентов 1С",
    accountant_confirmation: "Подтверждение бухгалтера",
  };

  const TAX_SYSTEM_LABELS = {
    osno: "ОСНО",
    usn_income: "УСН «Доходы»",
    usn_income_expense: "УСН «Доходы минус расходы»",
  };

  const moneyFormatter = new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 0,
  });
  const ratioFormatter = new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: 2,
  });
  const dateFormatter = new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });

  function isPresent(rawValue) {
    return rawValue !== null && rawValue !== undefined && rawValue !== "";
  }

  function numericValue(rawValue) {
    if (!isPresent(rawValue)) return null;
    const result = Number(String(rawValue).replace(",", "."));
    return Number.isFinite(result) ? result : null;
  }

  function formatMoney(rawValue) {
    const result = numericValue(rawValue);
    return result === null ? "Не подтверждено" : moneyFormatter.format(result);
  }

  function formatRatio(rawValue) {
    const result = numericValue(rawValue);
    return result === null ? "Нужны данные" : `${ratioFormatter.format(result)} %`;
  }

  function formatDate(rawValue) {
    const match = String(rawValue || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!match) return value(rawValue, "Не подтверждена");
    const result = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
    return dateFormatter.format(result);
  }

  function statusLabel(rawValue) {
    const normalized = String(rawValue || "").trim().toLowerCase();
    return STATUS_LABELS[normalized] || value(rawValue, "Не подтверждено");
  }

  function sourceKindLabel(rawValue) {
    const normalized = String(rawValue || "").trim().toLowerCase();
    return SOURCE_LABELS[normalized] || value(rawValue, "Источник не указан");
  }

  function userText(rawValue) {
    let result = value(rawValue, "—");
    Object.entries(SOURCE_LABELS).forEach(([sourceKind, label]) => {
      result = result.split(sourceKind).join(label);
    });
    return result
      .replace(/read-only/gi, "только для чтения")
      .replace(/RecordType\s+fallback/gi, "резервный источник");
  }

  function taxSystemLabel(rawValue) {
    const normalized = String(rawValue || "").trim().toLowerCase();
    return TAX_SYSTEM_LABELS[normalized] || value(rawValue, "Не подтверждён");
  }

  function periodKindLabel(rawValue) {
    const normalized = String(rawValue || "").trim().toLowerCase();
    if (["month", "monthly", "report_month"].includes(normalized)) return "За месяц";
    if (["ytd", "year_to_date", "preliminary_ytd"].includes(normalized)) {
      return "С начала года";
    }
    return value(rawValue, "—");
  }

  function exclusionReasonLabel(rawValue) {
    const normalized = String(rawValue || "").trim().toLowerCase();
    if (normalized === "agent_payment") return "агентский платёж";
    if (normalized === "insurance_contribution") return "страховые взносы";
    return value(rawValue, "по методике ФНС");
  }

  function fnsInclusionLabel(rawValue, row) {
    if (rawValue === true) return "Да";
    if (rawValue === false) return `Нет — ${exclusionReasonLabel(row?.exclusionReason)}`;
    return "Нужно классифицировать";
  }

  function emptyState(heading, description) {
    const item = node("div", "scenario-empty-state");
    item.append(node("strong", "", heading), node("p", "", description));
    return item;
  }

  function summaryHasData(summary, fields) {
    return fields.some((field) => isPresent(summary?.[field]));
  }

  function mobileTableHint() {
    return node(
      "p",
      "scenario-table-hint",
      "Таблица прокручивается по горизонтали.",
    );
  }

  registry.register("tax_load", (payload, panels) => {
    const meta = payload.meta || {};
    const profile = payload.taxProfile || {};
    const summary = payload.taxLoadSummary || {};
    const issues = Array.isArray(payload.issues) ? payload.issues : [];
    const ratioReady = isPresent(summary.fnsTaxBurdenRatio);
    const issueNextAction = issues.find((item) => item?.nextAction)?.nextAction;
    const nextAction = isPresent(issueNextAction)
      ? userText(issueNextAction)
      : (ratioReady
        ? "Подтвердите налоговые факты и отдельно утвердите клиентский вывод."
        : "Подтвердите уплаченные налоги и официальный доходный знаменатель.");

    const nextActionBlock = node("div", "scenario-callout is-info");
    nextActionBlock.append(
      node("strong", "", "Следующий шаг"),
      node("p", "", nextAction),
    );

    const usnManagement = isPresent(summary.usnIncomeStatus);
    const overviewMetrics = [
      ["Нагрузка по методике ФНС", formatRatio(summary.fnsTaxBurdenRatio), ratioReady ? "" : "is-warning"],
      ["Уплаченные собственные налоги", formatMoney(summary.numeratorValue)],
      ["Доход для расчёта", formatMoney(summary.denominatorValue)],
      ["Налоговый режим", taxSystemLabel(profile.taxSystem), profile.profileStatus === "missing" ? "is-warning" : ""],
    ];
    if (usnManagement) {
      overviewMetrics.push(
        ["Управленческая нагрузка (УСН, от поступлений)", formatRatio(summary.usnIncomeTaxBurden), isPresent(summary.usnIncomeTaxBurden) ? "" : "is-warning"],
        ["Доход УСН без НДС (поступления)", formatMoney(summary.usnIncomeValue)],
      );
    }

    panels.overview.append(
      title("Обзор расчёта", statusLabel(payload.businessStatus)),
      node(
        "p",
        "scenario-description",
        `Отчётный месяц: ${formatDate(meta.periodStart)} — ${formatDate(meta.periodEnd)}. `
          + `С начала года: ${formatDate(payload.ytdStart)} — ${formatDate(payload.ytdEnd)}.`,
      ),
      metricGrid(overviewMetrics),
      nextActionBlock,
      node(
        "p",
        "scenario-note",
        "Сравнение со среднеотраслевым показателем пока не используется: сопоставимость методик ещё не подтверждена.",
      ),
    );

    if (usnManagement) {
      panels.overview.append(
        node(
          "p",
          "scenario-note",
          "Управленческая нагрузка по УСН считается от дохода из поступлений без НДС и служит ориентиром для ИП, а не официальным коэффициентом ФНС организации.",
        ),
      );
    }

    const issueBlock = issues.length
      ? table(issues, {
        label: "Открытые проверки и дозапросы",
        columns: [
          { key: "severity", label: "Важность", format: statusLabel },
          { key: "section", label: "Раздел" },
          { key: "message", label: "Что найдено", format: userText },
          { key: "nextAction", label: "Что сделать", format: userText },
        ],
      })
      : emptyState(
        "Открытых дозапросов нет",
        "По сохранённому отчёту нет нерешённых вопросов к источникам.",
      );
    panels.checks.append(
      title("Проверки и дозапросы"),
      issueBlock,
      title("Покрытие источников"),
      mobileTableHint(),
      table(payload.sourceCoverage || [], {
        label: "Покрытие источников налогового отчёта",
        emptyText: "Источники ещё не подтверждены.",
        columns: [
          { key: "sourceKind", label: "Источник", format: sourceKindLabel },
          {
            key: "periodStart",
            label: "Период",
            format: (rawValue, row) => `${formatDate(rawValue)} — ${formatDate(row?.periodEnd)}`,
          },
          { key: "status", label: "Статус", format: statusLabel },
        ],
      }),
    );

    panels.tables.append(
      title("Налоги"),
      mobileTableHint(),
      table(payload.taxRows || [], {
        label: "Начисления, платежи и сальдо по налогам",
        emptyText: "Нет подтверждённых строк по налогам.",
        columns: [
          { key: "taxName", label: "Налог" },
          { key: "periodKind", label: "Период", format: periodKindLabel },
          { key: "accrued", label: "Начислено", format: formatMoney },
          { key: "paid", label: "Уплачено", format: formatMoney },
          { key: "balance", label: "Сальдо", format: formatMoney },
          { key: "dueDate", label: "Срок", format: formatDate },
          { key: "includedInFnsTaxBurden", label: "В нагрузке ФНС", format: fnsInclusionLabel },
          { key: "evidenceStatus", label: "Данные", format: statusLabel },
        ],
      }),
      title("График платежей — справочно"),
      mobileTableHint(),
      table(payload.paymentSchedule || [], {
        label: "Информационный график налоговых платежей",
        emptyText: "Нет дат для информационного графика платежей.",
        columns: [
          { key: "taxName", label: "Налог" },
          { key: "dueDate", label: "Срок", format: formatDate },
          { key: "amount", label: "Сумма", format: formatMoney },
          { key: "confirmationStatus", label: "Статус", format: statusLabel },
        ],
      }),
      title("НДС"),
      summaryHasData(payload.vatSummary, ["status", "outputVat", "inputVat", "payableVat"])
        ? metricGrid([
          ["Начисленный НДС", formatMoney(payload.vatSummary?.outputVat)],
          ["Входящий НДС", formatMoney(payload.vatSummary?.inputVat)],
          ["НДС к уплате", formatMoney(payload.vatSummary?.payableVat)],
          ["Статус", statusLabel(payload.vatSummary?.status)],
        ])
        : emptyState("НДС не подтверждён", "Запросите источник НДС и его статус у бухгалтера."),
      title("ЕНС"),
      summaryHasData(payload.ensSummary, ["status", "balance", "asOfDate"])
        ? metricGrid([
          ["Сальдо ЕНС", formatMoney(payload.ensSummary?.balance)],
          ["Дата состояния", formatDate(payload.ensSummary?.asOfDate)],
          ["Статус", statusLabel(payload.ensSummary?.status)],
        ])
        : emptyState("ЕНС не подтверждён", "Запросите подтверждённое сальдо и дату состояния ЕНС."),
    );
  });
})();
