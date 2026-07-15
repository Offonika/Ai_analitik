(() => {
  const registry = window.MultiReportScenarios;
  if (!registry) return;
  const { metricGrid, node, table, title, value } = registry.helpers;

  registry.register("month_close_control", (payload, panels) => {
    const meta = payload.meta || {};
    const osv = payload.osvSummary || {};
    panels.overview.append(
      title("Контроль закрытия месяца", payload.businessRecommendation),
      node(
        "p",
        "scenario-description",
        `Организация: ${value(meta.organizationId)} · период ${value(meta.periodStart)} — ${value(meta.periodEnd)}. ` +
          "Статус носит рекомендательный характер.",
      ),
      metricGrid([
        ["Рекомендация", payload.businessRecommendation],
        ["Покрытие источников", (payload.sourceCoverage || []).length],
        ["Расхождения ОСВ", osv.mismatchCount],
        ["Версия методики", meta.methodologyVersion],
      ]),
    );
    panels.checks.append(
      title("Проверки и подтверждения"),
      table(payload.controls || []),
      title("Риски и дозапросы"),
      table(payload.issues || []),
    );
    const summaries = [
      { section: "ОСВ", ...(payload.osvSummary || {}) },
      { section: "ЕНС", ...(payload.ensSummary || {}) },
      { section: "Налоги", ...(payload.taxSummary || {}) },
      { section: "НДС", ...(payload.vatSummary || {}) },
      { section: "Банк", ...(payload.bankSummary || {}) },
      { section: "Ручные операции", ...(payload.manualOperationsSummary || {}) },
    ];
    panels.tables.append(title("Сводные таблицы"), table(summaries));
    panels.tables.append(
      title("ОСВ и дельты"),
      table(payload.osvRows || []),
      title("Подтверждения"),
      table(payload.confirmations || []),
      title("Источники и статус"),
      table(payload.sourceCoverage || []),
    );
  });
})();
