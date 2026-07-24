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
    review_required: "Требуется проверка",
    reference_only: "Справочно, до годового расчёта",
    minimum_tax_applied: "Применён минимальный налог 1%",
    regular_tax_applied: "Применён обычный налог",
    warning: "Нужно проверить",
  };

  const SOURCE_LABELS = {
    manual_tax_load_draft_reference: "Локальный черновик графика платежей",
    onec_accounting: "Бухгалтерские данные 1С",
    onec_accounting_balance_and_turnovers: "Оборотно-сальдовая ведомость 1С",
    onec_tax: "Налоговый учёт 1С",
    onec_osv: "ОСВ 1С",
    onec_official_financial_results: "Отчёт о финансовых результатах 1С",
    onec_bank: "Банк в 1С",
    onec_accounting_bank_in: "Банковские поступления 1С",
    onec_accounting_bank_out: "Банковские списания 1С",
    onec_accounting_chart: "План счетов 1С",
    onec_accounting_counterparties: "Справочник контрагентов 1С",
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
    onec_financial_results: "Финансовые результаты 1С",
    onec_kudir: "Книга учёта доходов и расходов 1С",
    onec_operations: "Операции 1С",
    onec_organizations: "Организации 1С",
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
    accountant_confirmation: "Подтверждение бухгалтера",
  };

  const TAX_SYSTEM_LABELS = {
    osno: "ОСНО",
    usn_income: "УСН «Доходы»",
    usn_income_expense: "УСН «Доходы минус расходы»",
    usn_income_expenses: "УСН «Доходы минус расходы»",
    patent: "ПСН",
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

  function sourceGapNotice(payload) {
    const summary = payload.taxLoadSummary || {};
    if (isPresent(summary.fnsTaxBurdenRatio)) return null;
    const issues = Array.isArray(payload.issues) ? payload.issues : [];
    const nextActions = [...new Set(
      issues.map((item) => userText(item?.nextAction || "").trim()).filter(Boolean),
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

  registry.register("tax_load", (payload, panels, context = {}) => {
    const meta = payload.meta || {};
    const profile = payload.taxProfile || {};
    const summary = payload.taxLoadSummary || {};
    const usnDetail = payload.usnDetail || {};
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
    const usnIncomeExpenses = usnDetail.calculationMode === "income_expenses";
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
    } else if (usnIncomeExpenses) {
      overviewMetrics.push(
        ["Признанные доходы УСН по КУДиР", formatMoney(usnDetail.incomeYtd)],
        ["Признанные расходы УСН по КУДиР", formatMoney(usnDetail.kudirExpenseYtd)],
        ["Налоговая база УСН с начала года", formatMoney(usnDetail.taxBaseYtd)],
        ["Ставка УСН", formatRatio(usnDetail.taxRate)],
        ["Обычный налог УСН", formatMoney(usnDetail.regularTaxYtd)],
        ["Минимальный налог 1% (справочно)", formatMoney(usnDetail.minimumTaxReferenceYtd)],
        ["Применяемый налог УСН", formatMoney(usnDetail.calculatedTaxYtd)],
        ["К доплате / переплата УСН", formatMoney(usnDetail.taxPayable)],
      );
    }

    panels.overview.append(
      title("Обзор расчёта", statusLabel(payload.businessStatus)),
      node(
        "p",
        "scenario-description",
        `Организация: ${value(
          context.organizationLabel || meta.organizationName,
          "Название организации не найдено",
        )}. Отчётный месяц: ${formatDate(meta.periodStart)} — ${formatDate(meta.periodEnd)}. `
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
    } else if (usnIncomeExpenses) {
      panels.overview.append(
        node(
          "p",
          "scenario-note",
          `Расчёт «Доходы минус расходы» выполнен по признанным ресурсам КУДиР. `
            + `Минимальный налог: ${statusLabel(usnDetail.minimumTaxApplicationStatus)}.`,
        ),
      );
    }
    const gapNotice = sourceGapNotice(payload);
    if (gapNotice) panels.overview.append(gapNotice);

    const issueBlock = issues.length
      ? table(issues, {
        ariaLabel: "Открытые проверки и дозапросы",
        mobileCards: true,
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
        ariaLabel: "Покрытие источников налогового отчёта",
        mobileCards: true,
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
      node(
        "p",
        "scenario-table-intro",
        "Черновые суммы показаны для проверки. Они не подтверждают начисление или уплату и не участвуют в коэффициенте ФНС.",
      ),
      title("Налоги"),
      mobileTableHint(),
      table(payload.taxRows || [], {
        ariaLabel: "Начисления, платежи и сальдо по налогам",
        className: "scenario-tax-table",
        mobileCards: true,
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
        mobileColumns: [
          { key: "taxName", label: "Налог" },
          {
            key: "amount",
            label: "Сумма",
            value: (row) => row.balance ?? row.paid ?? row.accrued,
            format: formatMoney,
          },
          { key: "dueDate", label: "Срок", format: formatDate },
          { key: "evidenceStatus", label: "Статус", format: statusLabel },
        ],
      }),
      title("График платежей — справочно"),
      mobileTableHint(),
      table(payload.paymentSchedule || [], {
        ariaLabel: "Информационный график налоговых платежей",
        className: "scenario-schedule-table",
        mobileCards: true,
        emptyText: "Нет дат для информационного графика платежей.",
        columns: [
          { key: "taxName", label: "Налог" },
          { key: "dueDate", label: "Срок", format: formatDate },
          { key: "amount", label: "Черновая сумма", format: formatMoney },
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
