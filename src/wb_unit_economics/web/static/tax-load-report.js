(() => {
  const registry = window.MultiReportScenarios;
  if (!registry) return;
  const { metricGrid, node, table, title, value } = registry.helpers;

  registry.register("tax_load", (payload, panels) => {
    const meta = payload.meta || {};
    const profile = payload.taxProfile || {};
    const summary = payload.taxLoadSummary || {};
    const ratio = summary.fnsTaxBurdenRatio === null || summary.fnsTaxBurdenRatio === undefined
      ? "Не рассчитана"
      : `${summary.fnsTaxBurdenRatio}%`;
    panels.overview.append(
      title("Налоговая нагрузка", payload.businessStatus),
      node(
        "p",
        "scenario-description",
        `Организация: ${value(meta.organizationId)} · месяц ${value(meta.periodStart)} — ${value(meta.periodEnd)} · ` +
          `YTD ${value(payload.ytdStart)} — ${value(payload.ytdEnd)}.`,
      ),
      metricGrid([
        ["Нагрузка по ФНС", ratio, summary.fnsTaxBurdenRatio ? "" : "is-warning"],
        ["Уплаченные собственные налоги", summary.numeratorValue],
        ["Доходный знаменатель", summary.denominatorValue],
        ["Налоговый режим", profile.taxSystem],
      ]),
      node(
        "p",
        "scenario-note",
        "Сравнение со среднеотраслевой таблицей отключено до подтверждения сопоставимости методик.",
      ),
    );
    panels.checks.append(
      title("Проверки и дозапросы"),
      table(payload.issues || []),
      title("Покрытие источников"),
      table(payload.sourceCoverage || []),
    );
    panels.tables.append(
      title("Налоги"),
      table(payload.taxRows || []),
      title("График платежей — информационный"),
      table(payload.paymentSchedule || []),
      title("НДС"),
      table([{ ...(payload.vatSummary || {}) }]),
      title("ЕНС"),
      table([{ ...(payload.ensSummary || {}) }]),
    );
  });
})();
