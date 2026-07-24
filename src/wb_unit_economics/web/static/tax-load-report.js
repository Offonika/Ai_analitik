(() => {
  const registry = window.MultiReportScenarios;
  if (!registry) return;
  const {
    formatDate,
    formatMoney,
    localizeStatus,
    metricGrid,
    node,
    table,
    title,
    value,
  } = registry.helpers;

  const SOURCE_LABELS = {
    manual_tax_load_draft_reference: "Локальный черновик графика платежей",
    onec_accounting: "Бухгалтерские данные 1С",
    onec_accounting_balance_and_turnovers: "Оборотно-сальдовая ведомость 1С",
    onec_accounting_bank_in: "Поступления на банковский счёт 1С",
    onec_accounting_bank_out: "Списания с банковского счёта 1С",
    onec_accounting_chart: "План счетов 1С",
    onec_accounting_ens: "Единый налоговый счёт 1С",
    onec_accounting_ens_sanctions: "Санкции на едином налоговом счёте 1С",
    onec_accounting_manual_operations: "Ручные операции 1С",
    onec_accounting_month_close_docs: "Документы закрытия месяца 1С",
    onec_accounting_purchase_corrections: "Корректировки поступлений 1С",
    onec_accounting_register_balances: "Остатки регистров 1С",
    onec_accounting_register_corrections: "Корректировки регистров 1С",
    onec_accounting_register_records: "Записи регистров 1С",
    onec_accounting_sales_corrections: "Корректировки реализаций 1С",
    onec_accounting_taxes: "Начисления налогов 1С",
    onec_accounting_taxes_on_ens: "Налоги на ЕНС 1С",
    onec_bank: "Банковские операции 1С",
    onec_financial_results: "Финансовые результаты 1С",
    onec_kudir: "Книга учёта доходов и расходов 1С",
    onec_official_financial_results: "Официальные финансовые результаты 1С",
    onec_operations: "Операции 1С",
    onec_organizations: "Организации 1С",
    onec_osv: "Оборотно-сальдовая ведомость 1С",
    onec_tax: "Налоговые данные 1С",
    onec_tax_accrual_lines: "Строки начислений налогов 1С",
    onec_tax_accruals: "Начисления налогов 1С",
    onec_tax_kinds: "Виды налогов 1С",
    onec_tax_profiles: "Налоговые профили 1С",
    onec_tax_register: "Налоговый регистр 1С",
    onec_tax_registrations: "Регистрации в налоговых органах 1С",
    onec_tax_special_regime_notifications: "Уведомления о специальных режимах 1С",
    onec_vat: "Данные НДС 1С",
    onec_vat_books: "Книги НДС 1С",
    onec_vat_purchase_book: "Книга покупок 1С",
    onec_vat_sales_book: "Книга продаж 1С",
  };

  function sourceLabel(rawValue) {
    return SOURCE_LABELS[String(rawValue || "").trim()] || "Дополнительный источник данных";
  }

  function localizeIssueText(rawValue) {
    return value(rawValue, "Требуется уточнение").replace(
      /onec_[a-z0-9_]+/gi,
      (sourceKind) => sourceLabel(sourceKind),
    );
  }

  function taxSystemLabel(rawValue) {
    const labels = {
      osno: "ОСНО",
      осно: "ОСНО",
      usn: "УСН",
      усн: "УСН",
      usn_income: "УСН «Доходы»",
      usn_income_expenses: "УСН «Доходы минус расходы»",
      patent: "ПСН",
    };
    const normalized = String(rawValue || "").trim().toLowerCase();
    return normalized ? (labels[normalized] || "Требует уточнения") : "Не подтверждён";
  }

  function periodLabel(row) {
    const start = formatDate(row.periodStart, "");
    const end = formatDate(row.periodEnd, "");
    if (start && end) return `${start} — ${end}`;
    return start || end || "Не указан";
  }

  function taxRowStatus(row) {
    return localizeStatus(row.valueStatus || row.evidenceStatus);
  }

  function taxRowAmount(row) {
    return row.balance ?? row.paid ?? row.accrued;
  }

  function fnsClassification(row) {
    if (row.includedInFnsTaxBurden === true) return "Включать после подтверждения";
    if (row.includedInFnsTaxBurden === false) return "Не включается";
    return "Требует классификации";
  }

  function sourceGapNotice(payload) {
    const summary = payload.taxLoadSummary || {};
    if (summary.fnsTaxBurdenRatio !== null && summary.fnsTaxBurdenRatio !== undefined) {
      return null;
    }
    const issues = Array.isArray(payload.issues) ? payload.issues : [];
    const nextActions = [...new Set(
      issues.map((item) => String(item?.nextAction || "").trim()).filter(Boolean),
    )].slice(0, 3);
    const notice = node("section", "scenario-gap-notice");
    notice.append(
      node("strong", "", "Почему отчёт пока не рассчитан"),
      node(
        "p",
        "",
        "Нет подтверждённых фактически уплаченных собственных налогов и официального доходного знаменателя. Доступные черновые строки показаны только для проверки и не участвуют в коэффициенте ФНС.",
      ),
    );
    if (nextActions.length) {
      const list = node("ul", "scenario-gap-actions");
      nextActions.forEach((action) => list.append(node("li", "", action)));
      notice.append(list);
    }
    return notice;
  }

  const issueColumns = [
    { key: "section", label: "Раздел", fallback: "Общая проверка" },
    { key: "message", label: "Что проверить", format: localizeIssueText },
    { key: "nextAction", label: "Следующее действие", format: localizeIssueText },
    { key: "severity", label: "Статус", format: localizeStatus },
  ];

  const coverageColumns = [
    { key: "sourceKind", label: "Источник", format: sourceLabel },
    { key: "period", label: "Период", value: periodLabel },
    { key: "status", label: "Статус", format: localizeStatus },
  ];

  const taxColumns = [
    { key: "taxName", label: "Налог", fallback: "Без названия" },
    { key: "accrued", label: "Начислено", format: formatMoney },
    { key: "paid", label: "Уплачено", format: formatMoney },
    { key: "balance", label: "Остаток / черновая сумма", format: formatMoney },
    { key: "dueDate", label: "Срок", format: formatDate },
    {
      key: "fnsClassification",
      label: "Учёт по методике ФНС",
      value: fnsClassification,
    },
    { key: "evidenceStatus", label: "Статус", format: localizeStatus },
  ];

  const taxMobileColumns = [
    { key: "taxName", label: "Налог", fallback: "Без названия" },
    { key: "amount", label: "Сумма", value: taxRowAmount, format: formatMoney },
    { key: "dueDate", label: "Срок", format: formatDate },
    { key: "status", label: "Статус", value: taxRowStatus },
  ];

  const scheduleColumns = [
    { key: "taxName", label: "Налог", fallback: "Без названия" },
    { key: "amount", label: "Черновая сумма", format: formatMoney },
    { key: "dueDate", label: "Срок", format: formatDate },
    {
      key: "confirmationStatus",
      label: "Статус",
      format: localizeStatus,
    },
  ];

  registry.register("tax_load", (payload, panels, context = {}) => {
    const meta = payload.meta || {};
    const profile = payload.taxProfile || {};
    const summary = payload.taxLoadSummary || {};
    const ratioAvailable = summary.fnsTaxBurdenRatio !== null
      && summary.fnsTaxBurdenRatio !== undefined;
    const ratio = ratioAvailable ? `${summary.fnsTaxBurdenRatio}%` : "Не рассчитана";
    const organizationLabel = value(
      context.organizationLabel || meta.organizationName,
      "Название организации не найдено",
    );
    const overviewNodes = [
      title("Налоговая нагрузка", payload.businessStatus),
      node(
        "p",
        "scenario-description",
        `Организация: ${organizationLabel} · месяц ${formatDate(meta.periodStart)} — ${formatDate(meta.periodEnd)} · ` +
          `с начала года ${formatDate(payload.ytdStart)} — ${formatDate(payload.ytdEnd)}.`,
      ),
      metricGrid([
        ["Нагрузка по ФНС", ratio, ratioAvailable ? "" : "is-warning"],
        ["Уплаченные собственные налоги", formatMoney(summary.numeratorValue)],
        ["Доходный знаменатель", formatMoney(summary.denominatorValue)],
        ["Налоговый режим", taxSystemLabel(profile.taxSystem)],
      ]),
      node(
        "p",
        "scenario-note",
        "Сравнение со среднеотраслевой таблицей отключено до подтверждения сопоставимости методик.",
      ),
    ];
    const gapNotice = sourceGapNotice(payload);
    if (gapNotice) overviewNodes.push(gapNotice);
    panels.overview.append(...overviewNodes);
    panels.checks.append(
      title("Проверки и дозапросы"),
      table(payload.issues || [], {
        ariaLabel: "Проверки и дозапросы налоговой нагрузки",
        columns: issueColumns,
        mobileCards: true,
      }),
      title("Покрытие источников"),
      table(payload.sourceCoverage || [], {
        ariaLabel: "Покрытие источников налоговой нагрузки",
        columns: coverageColumns,
        mobileCards: true,
      }),
    );
    panels.tables.append(
      node(
        "p",
        "scenario-table-intro",
        "Черновые суммы показаны для проверки. Они не подтверждают начисление или уплату и не участвуют в коэффициенте ФНС.",
      ),
      title("Налоги"),
      table(payload.taxRows || [], {
        ariaLabel: "Налоги и подтверждение данных",
        className: "scenario-tax-table",
        columns: taxColumns,
        mobileCards: true,
        mobileColumns: taxMobileColumns,
      }),
      title("График платежей — информационный"),
      table(payload.paymentSchedule || [], {
        ariaLabel: "Информационный график налоговых платежей",
        className: "scenario-schedule-table",
        columns: scheduleColumns,
        mobileCards: true,
      }),
      title("НДС"),
      table([{ ...(payload.vatSummary || {}) }], {
        ariaLabel: "Сводка по НДС",
        columns: [
          { key: "status", label: "Статус", format: localizeStatus },
          { key: "outputVat", label: "Исходящий НДС", format: formatMoney },
          { key: "inputVat", label: "Входящий НДС", format: formatMoney },
          { key: "payableVat", label: "НДС к уплате", format: formatMoney },
        ],
        mobileCards: true,
      }),
      title("ЕНС"),
      table([{ ...(payload.ensSummary || {}) }], {
        ariaLabel: "Сводка по единому налоговому счёту",
        columns: [
          { key: "status", label: "Статус", format: localizeStatus },
          { key: "balance", label: "Сальдо ЕНС", format: formatMoney },
          { key: "asOfDate", label: "По состоянию на", format: formatDate },
        ],
        mobileCards: true,
      }),
    );
  });
})();
