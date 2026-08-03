from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from wb_unit_economics.web import repository
from wb_unit_economics.web.models import AiThread, ReportRun, User
from wb_unit_economics.web.prompt_loader import load_prompt, render_prompt
from wb_unit_economics.web.refresh import (
    AutoRefreshBusyError,
    AutoRefreshDisabledError,
    AutoRefreshUnavailableError,
)
from wb_unit_economics.web.settings import WebSettings

LIMITATIONS = [
    "Причины возврата не передаются текущими источниками.",
    "Упущенные продажи являются управленческой оценкой, не финальным прогнозом.",
    "AI не меняет себестоимость, маппинг и данные WB/1C.",
]

CONVERSATIONAL_MESSAGES = frozenset(
    {
        "благодарю",
        "доброе утро",
        "добрый вечер",
        "добрый день",
        "до свидания",
        "здравствуй",
        "здравствуйте",
        "как тобой пользоваться",
        "пока",
        "привет",
        "приветствую",
        "спасибо",
        "что ты умеешь",
        "чем можешь помочь",
        "hello",
        "hi",
    }
)


@dataclass(frozen=True)
class AiAnswer:
    content: str
    answer_source: str
    model: str
    fallback_reason: str = ""
    tool_names: tuple[str, ...] = ()
    citations: tuple[dict[str, Any], ...] = ()


class AiAnalyst:
    def __init__(
        self,
        settings: WebSettings,
        *,
        auto_refresh_service: Any | None = None,
    ) -> None:
        self.settings = settings
        self.auto_refresh_service = auto_refresh_service

    def answer(
        self, db: Session, *, user: User, thread: AiThread, question: str
    ) -> AiAnswer:
        report = self._thread_report(db, user, thread)
        fallback_outputs: dict[str, Any] = {}
        tool_names: tuple[str, ...] = ()
        if self.settings.resolved_openai_api_key:
            result = self._openai_answer(
                db, user, thread, report, question
            )
            response, fallback_reason = result[:2]
            if len(result) >= 3:
                tool_names = tuple(result[2])
            if len(result) >= 4:
                fallback_outputs = dict(result[3])
            if response:
                citations = self._citations(
                    report=report,
                    thread=thread,
                    tool_outputs=fallback_outputs,
                )
                self._add_answer_source_event(
                    db,
                    user=user,
                    thread=thread,
                    answer_source="openai",
                    tool_names=tool_names,
                )
                return AiAnswer(
                    content=response,
                    answer_source="openai",
                    model=self.settings.openai_model,
                    tool_names=tool_names,
                    citations=citations,
                )
        else:
            fallback_reason = "no_openai_key"
        fallback_outputs = self._fallback_tool_outputs(
            db,
            user,
            thread,
            report,
            question,
            existing=fallback_outputs,
        )
        tool_names = tuple(fallback_outputs.keys())
        self._add_answer_source_event(
            db,
            user=user,
            thread=thread,
            answer_source="fallback",
            fallback_reason=fallback_reason,
            tool_names=tool_names,
        )
        return AiAnswer(
            content=self._fallback_answer(fallback_outputs, question),
            answer_source="fallback",
            model=self.settings.openai_model,
            fallback_reason=fallback_reason,
            tool_names=tool_names,
            citations=self._citations(
                report=report,
                thread=thread,
                tool_outputs=fallback_outputs,
            ),
        )

    def _citations(
        self,
        *,
        report: ReportRun,
        thread: AiThread,
        tool_outputs: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        if not tool_outputs:
            return ()
        citations: list[dict[str, Any]] = [
            {
                "type": "report",
                "reportId": report.id,
                "clientId": report.client_id,
                "scopeHash": thread.scope_hash,
                "tool": "get_report_summary",
            }
        ]
        for tool_name in ("search_sku", "get_loss_drivers"):
            output = tool_outputs.get(tool_name) or {}
            items = output.get("items") or output.get("top_losses") or []
            for item in items[:5]:
                citations.append(
                    {
                        "type": "report_row",
                        "reportId": report.id,
                        "tool": tool_name,
                        "product": item.get("product"),
                        "article1c": item.get("article_1c"),
                        "barcode": item.get("barcode"),
                        "nmId": item.get("nm_id"),
                    }
                )
        return tuple(citations)

    def _add_answer_source_event(
        self,
        db: Session,
        *,
        user: User,
        thread: AiThread,
        answer_source: str,
        tool_names: tuple[str, ...],
        fallback_reason: str = "",
    ) -> None:
        if answer_source == "openai":
            title = "OpenAI ответил"
            message = (
                "Ответ собран AI-аналитиком по расчетной витрине."
                if tool_names
                else "Ответ подготовлен без обращения к данным отчёта."
            )
            status = "ok"
        else:
            title = "Ответ собран локально"
            message = "Ответ собран по расчетной витрине. Внешние системы не менялись."
            status = "fallback"
        repository.add_ai_event(
            db,
            thread=thread,
            user=user,
            event_type="answer_source",
            title=title,
            message=message,
            status=status,
            payload={
                "answerSource": answer_source,
                "model": self.settings.openai_model,
                "fallbackReason": fallback_reason,
                "toolNames": list(tool_names),
                "limitations": self._limitations(
                    repository.report_summary_payload(
                        db, self._thread_report(db, user, thread)
                    )
                ),
            },
        )

    def refine_client_draft(
        self,
        db: Session,
        *,
        user: User,
        report: ReportRun,
        instruction: str,
        latest_draft: str = "",
    ) -> dict[str, Any]:
        summary = repository.report_full_payload(db, report)
        evidence = repository.client_draft_evidence_payload(summary)
        limitations = repository.client_draft_limitations(summary)
        current_text = latest_draft.strip()
        if not self.settings.resolved_openai_api_key:
            if current_text:
                return {
                    "changed": False,
                    "source": "unavailable",
                    "content": current_text,
                    "message": "AI недоступен, черновик не изменен.",
                    "evidence": evidence,
                    "limitations": limitations,
                }
            return {
                "changed": True,
                "source": "deterministic_base",
                "content": self._base_client_draft(summary),
                "message": "Первый черновик собран из управленческой записки.",
                "evidence": evidence,
                "limitations": limitations,
            }
        refined = self._openai_client_draft(
            summary=summary,
            evidence=evidence,
            limitations=limitations,
            latest_draft=current_text,
            instruction=instruction,
        )
        if not refined:
            if current_text:
                return {
                    "changed": False,
                    "source": "unavailable",
                    "content": current_text,
                    "message": "AI недоступен, черновик не изменен.",
                    "evidence": evidence,
                    "limitations": limitations,
                }
            return {
                "changed": True,
                "source": "deterministic_base",
                "content": self._base_client_draft(summary),
                "message": "Первый черновик собран из управленческой записки.",
                "evidence": evidence,
                "limitations": limitations,
            }
        return {
            "changed": True,
            "source": "ai",
            "content": self._normalize_client_draft(refined, summary),
            "message": "Черновик доработан по замечанию аналитика.",
            "evidence": evidence,
            "limitations": limitations,
        }

    def _thread_report(self, db: Session, user: User, thread: AiThread) -> ReportRun:
        if not thread.report_run_id:
            raise ValueError("Диалог AI не привязан к расчету отчета")
        report = repository.require_report(db, user, thread.report_run_id)
        if thread.client_id and thread.client_id != report.client_id:
            raise PermissionError("thread/report scope mismatch")
        return report

    def _fallback_tool_outputs(
        self,
        db: Session,
        user: User,
        thread: AiThread,
        report: ReportRun,
        question: str,
        *,
        existing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        outputs = dict(existing or {})
        if "get_report_summary" not in outputs:
            outputs["get_report_summary"] = self._run_tool(
                db, user, thread, report, "get_report_summary", {}, question
            )
        for tool_name in self._planned_tool_names(question):
            if tool_name in outputs:
                continue
            outputs[tool_name] = self._run_tool(
                db,
                user,
                thread,
                report,
                tool_name,
                {"query": question, "lookup": question},
                question,
            )
        return outputs

    def _openai_answer(
        self,
        db: Session,
        user: User,
        thread: AiThread,
        report: ReportRun,
        question: str,
    ) -> tuple[str | None, str, tuple[str, ...], dict[str, Any]]:
        try:
            from openai import OpenAI
        except ImportError:
            return None, "openai_sdk_missing", (), {}
        try:
            client = OpenAI(
                api_key=self.settings.resolved_openai_api_key,
                timeout=self.settings.openai_timeout_seconds,
            )
            history = repository.thread_messages(db, thread, limit=20)
            history_items = [
                {"role": item.role, "content": item.content}
                for item in history
                if item.role in {"user", "assistant"}
            ]
            while sum(len(str(item["content"])) for item in history_items) > 32000:
                history_items.pop(0)
            limitations = self._limitations(
                repository.report_summary_payload(db, report)
            )
            input_items: list[Any] = [
                {
                    "role": "developer",
                    "content": render_prompt(
                        "ai_analyst",
                        LIMITATIONS="\n".join(f"- {item}" for item in limitations),
                    ),
                },
                *history_items,
            ]
            current_item = {"role": "user", "content": question}
            if not history_items or history_items[-1] != current_item:
                input_items.append({"role": "user", "content": question})
            executed: dict[str, Any] = {}
            response = client.responses.create(
                model=self.settings.openai_model,
                input=input_items,
                tools=self._tool_specs(),
                tool_choice=(
                    "none" if self._is_conversational_message(question) else "required"
                ),
                parallel_tool_calls=False,
                store=False,
                include=["reasoning.encrypted_content"],
                safety_identifier=self._safety_identifier(user),
            )
            for _ in range(3):
                calls = self._function_calls(response)
                if not calls:
                    return (
                        getattr(response, "output_text", None),
                        "",
                        tuple(executed),
                        executed,
                    )
                input_items.extend(self._response_output_items(response))
                for call in calls:
                    tool_output = self._run_tool(
                        db,
                        user,
                        thread,
                        report,
                        call["name"],
                        call["arguments"],
                        question,
                    )
                    executed[call["name"]] = tool_output
                    input_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": call["call_id"],
                            "output": json.dumps(tool_output, ensure_ascii=False),
                        }
                    )
                response = client.responses.create(
                    model=self.settings.openai_model,
                    input=input_items,
                    tools=self._tool_specs(),
                    parallel_tool_calls=False,
                    store=False,
                    include=["reasoning.encrypted_content"],
                    safety_identifier=self._safety_identifier(user),
                )
            return (
                getattr(response, "output_text", None),
                "tool_loop_limit",
                tuple(executed),
                executed,
            )
        except Exception as exc:
            completed = locals().get("executed", {})
            return None, exc.__class__.__name__, tuple(completed), completed

    def _safety_identifier(self, user: User) -> str:
        digest = hashlib.sha256(user.id.encode("utf-8")).hexdigest()[:32]
        return f"cabinet-user-{digest}"

    def _run_tool(
        self,
        db: Session,
        user: User,
        thread: AiThread,
        report: ReportRun,
        tool_name: str,
        arguments: dict[str, Any],
        question: str,
    ) -> dict[str, Any]:
        repository.add_ai_event(
            db,
            thread=thread,
            user=user,
            event_type="tool_started",
            title=self._tool_title(tool_name),
            message=self._tool_start_message(tool_name),
            status="running",
            tool_name=tool_name,
            payload=self._tool_input_payload(tool_name, arguments, question),
        )
        staff = repository.has_role(
            user,
            repository.STAFF_ROLES,
            report.tenant_id,
        )
        logistics_analysis = None
        if self.settings.logistics_analysis_enabled and staff:
            logistics_analysis = self._thread_logistics_analysis(
                db,
                thread=thread,
                report=report,
            )
        summary = self._thread_report_summary(
            db,
            thread=thread,
            report=report,
            include_staff_readiness=staff,
            logistics_analysis=logistics_analysis,
        )
        if logistics_analysis is not None:
            summary["logisticsAnalysis"] = logistics_analysis
        analysis_period = self._logistics_analysis_period(logistics_analysis)
        logistics_surface = (
            isinstance(thread.scope, dict)
            and thread.scope.get("analysisSurface") == "logistics"
        )
        if tool_name == "get_report_summary":
            output = self._summary_digest(summary, question)
        elif tool_name == "search_sku":
            if logistics_surface and analysis_period is None:
                output = self._empty_scoped_tool_output(summary, tool_name)
            else:
                output = self._search_sku(
                    db,
                    report,
                    arguments.get("query") or question,
                    period=analysis_period,
                )
        elif tool_name == "get_loss_drivers":
            if logistics_surface and analysis_period is None:
                output = self._empty_scoped_tool_output(summary, tool_name)
            else:
                output = self._loss_drivers(
                    db,
                    report,
                    summary,
                    period=analysis_period,
                )
        elif tool_name == "get_data_quality_issues":
            if logistics_surface and analysis_period is None:
                output = self._empty_scoped_tool_output(summary, tool_name)
            else:
                output = self._data_quality(
                    db,
                    report,
                    summary,
                    period=analysis_period,
                )
        elif tool_name == "compare_periods":
            output = self._period_comparison(summary)
        elif tool_name == "draft_management_report":
            output = {"markdown": repository.management_report_summary_text(summary)}
        elif tool_name == "verify_onec_cost":
            output = repository.live_check_payload(
                db,
                user=user,
                report=report,
                source_type="1c",
                check_type="onec_cost",
                lookup_key=arguments.get("lookup") or question,
                enabled=(
                    self.settings.external_integrations_enabled
                    and self.settings.live_checks_enabled
                ),
                cache_ttl_minutes=self.settings.live_check_cache_ttl_minutes,
            )
        elif tool_name == "verify_wb_card":
            output = repository.live_check_payload(
                db,
                user=user,
                report=report,
                source_type="wb",
                check_type="wb_card",
                lookup_key=arguments.get("lookup") or question,
                enabled=(
                    self.settings.external_integrations_enabled
                    and self.settings.live_checks_enabled
                ),
                cache_ttl_minutes=self.settings.live_check_cache_ttl_minutes,
            )
        elif tool_name == "verify_wb_stock":
            output = repository.live_check_payload(
                db,
                user=user,
                report=report,
                source_type="wb",
                check_type="wb_stock",
                lookup_key=arguments.get("lookup") or question,
                enabled=(
                    self.settings.external_integrations_enabled
                    and self.settings.live_checks_enabled
                ),
                cache_ttl_minutes=self.settings.live_check_cache_ttl_minutes,
            )
        elif tool_name == "refresh_onec_and_rebuild_report":
            output = self._refresh_onec_and_rebuild_report(
                db,
                user=user,
                thread=thread,
                report=report,
                reason=str(arguments.get("reason") or question),
            )
        else:
            output = {
                "status": "blocked",
                "message": "Инструмент не разрешен в этом кабинете.",
            }
        repository.add_ai_tool_call(
            db,
            thread=thread,
            user=user,
            tool_name=tool_name,
            input_payload={"question": question, "arguments": arguments},
            output_payload=output,
            status=output.get("status", "ok"),
        )
        repository.add_ai_event(
            db,
            thread=thread,
            user=user,
            event_type="tool_completed",
            title=self._tool_title(tool_name),
            message=self._tool_done_message(tool_name, output),
            status=output.get("status", "ok"),
            tool_name=tool_name,
            payload=self._tool_event_payload(tool_name, output),
        )
        return output

    def _summary_digest(self, summary: dict[str, Any], question: str) -> dict[str, Any]:
        kpis = summary.get("kpis") or {}
        row_count = kpis.get("rowCount")
        loss_rows = kpis.get("lossRows")
        return {
            "question": question,
            "period": summary["meta"]["period"],
            "period_status": summary["meta"]["periodStatus"],
            "methodology_version": summary["meta"]["methodologyVersion"],
            "revenue": kpis.get("revenue"),
            "profit": kpis.get("profit"),
            "profit_before_tax": kpis.get("profitBeforeTax"),
            "margin": kpis.get("margin"),
            "margin_management": kpis.get("marginManagement"),
            "rows": int(row_count) if row_count is not None else None,
            "loss_rows": int(loss_rows) if loss_rows is not None else None,
            "quality": summary.get("quality") or {},
            "readiness": summary.get("readiness") or {},
            "logistics_analysis": self._logistics_digest(
                summary.get("logisticsAnalysis")
            ),
            "limitations": self._limitations(summary),
        }

    def _thread_report_summary(
        self,
        db: Session,
        *,
        thread: AiThread,
        report: ReportRun,
        include_staff_readiness: bool,
        logistics_analysis: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base = repository.report_summary_payload(
            db,
            report,
            include_staff_readiness=include_staff_readiness,
        )
        scope = thread.scope if isinstance(thread.scope, dict) else {}
        if scope.get("analysisSurface") != "logistics":
            return base
        period = self._logistics_analysis_period(logistics_analysis)
        if period is None:
            return self._summary_without_closed_period(base, logistics_analysis)
        period_start, period_end = period
        page = repository.query_report_rows(
            db,
            report,
            period_start=period_start,
            period_end=period_end,
            limit=1,
        )
        if int(page.get("total") or 0) == 0:
            return self._summary_without_closed_period(base, logistics_analysis)
        period_label = f"{period_start:%d.%m.%Y} - {period_end:%d.%m.%Y}"
        return {
            **base,
            **(page.get("analytics") or {}),
            "meta": {
                **(base.get("meta") or {}),
                "period": period_label,
                "reportPeriod": period_label,
                "periodStart": period_start.isoformat(),
                "periodEnd": period_end.isoformat(),
                "periodStatus": "полные закрытые недели",
                "analysisScope": "logistics_closed_weeks",
            },
        }

    def _summary_without_closed_period(
        self,
        base: dict[str, Any],
        logistics_analysis: dict[str, Any] | None,
    ) -> dict[str, Any]:
        period_context = (logistics_analysis or {}).get("periodContext") or {}
        requested = period_context.get("requestedPeriod") or {}
        start = str(requested.get("periodStart") or "")
        end = str(requested.get("periodEnd") or "")
        period_label = f"{start} - {end}" if start and end else "не указан"
        return {
            **base,
            "meta": {
                **(base.get("meta") or {}),
                "period": period_label,
                "reportPeriod": period_label,
                "periodStart": start or None,
                "periodEnd": end or None,
                "periodStatus": "нет полной закрытой недели",
                "analysisScope": "logistics_no_closed_week",
            },
            "kpis": {key: None for key in (base.get("kpis") or {})},
            "quality": {},
            "monthly": [],
            "expenses": [],
            "unitRows": [],
            "returns": [],
            "lostSales": [],
        }

    def _logistics_analysis_period(
        self,
        logistics_analysis: dict[str, Any] | None,
    ) -> tuple[date, date] | None:
        context = (logistics_analysis or {}).get("periodContext") or {}
        period = context.get("analysisPeriod") or {}
        try:
            return (
                date.fromisoformat(str(period.get("periodStart") or "")),
                date.fromisoformat(str(period.get("periodEnd") or "")),
            )
        except ValueError:
            return None

    def _empty_scoped_tool_output(
        self,
        summary: dict[str, Any],
        tool_name: str,
    ) -> dict[str, Any]:
        common = {
            "status": "partial",
            "limitations": self._limitations(summary),
        }
        if tool_name == "search_sku":
            return {**common, "query": "", "total": None, "items": []}
        if tool_name == "get_loss_drivers":
            return {
                **common,
                "loss_rows": None,
                "drivers": [],
                "top_losses": [],
            }
        return {
            **common,
            "total_rows": None,
            "review_rows": None,
            "quality": {},
            "statuses": [],
        }

    def _thread_logistics_analysis(
        self,
        db: Session,
        *,
        thread: AiThread,
        report: ReportRun,
    ) -> dict[str, Any]:
        scope = thread.scope if isinstance(thread.scope, dict) else {}
        period_start = report.period_start
        period_end = report.period_end
        if scope.get("analysisSurface") == "logistics":
            try:
                candidate_start = date.fromisoformat(
                    str(scope.get("logisticsRequestedPeriodStart") or "")
                )
                candidate_end = date.fromisoformat(
                    str(scope.get("logisticsRequestedPeriodEnd") or "")
                )
            except ValueError:
                candidate_start = report.period_start
                candidate_end = report.period_end
            if (
                report.period_start <= candidate_start <= candidate_end
                and candidate_end <= report.period_end
            ):
                period_start = candidate_start
                period_end = candidate_end
        return repository.report_logistics_analysis_payload(
            db,
            report,
            period_start=period_start,
            period_end=period_end,
            period_mode="closed_weeks",
            wb_cabinet_id=str(scope.get("logisticsWbCabinetId") or "")[:160],
            scheme=str(scope.get("logisticsScheme") or "")[:80],
            product_query=str(scope.get("logisticsProductQuery") or "")[:240],
        )

    def _logistics_digest(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        rankings = value.get("rankings") or {}
        recommendations = []
        for item in (value.get("recommendations") or [])[:5]:
            if not isinstance(item, dict):
                continue
            evidence = item.get("evidence") or {}
            recommendations.append(
                {
                    "code": item.get("code"),
                    "title": item.get("title"),
                    "message": item.get("message"),
                    "value_type": item.get("valueType"),
                    "evidence": {
                        key: evidence.get(key)
                        for key in (
                            "product",
                            "reverseLogistics",
                            "returnQuantity",
                            "logisticsSharePct",
                            "lowSample",
                            "classificationCoveragePct",
                            "keyCoveragePct",
                            "productCoveragePct",
                            "crossCabinetCollisions",
                            "invalidSourcePayloadShapes",
                            "sourceIdentityErrors",
                            "sourceRevisionConflicts",
                            "scopeMismatches",
                            "dataStatus",
                        )
                        if key in evidence
                    },
                }
            )
        top_products = []
        for item in (rankings.get("byTotal") or [])[:5]:
            if not isinstance(item, dict):
                continue
            top_products.append(
                {
                    "product": item.get("product"),
                    "logistics_total": item.get("logisticsTotal"),
                    "logistics_reverse": item.get("logisticsReverse"),
                    "logistics_share_pct": item.get("logisticsSharePct"),
                    "profit_effect_amount": item.get("profitEffectAmount"),
                    "order_count": item.get("orderCount"),
                    "return_quantity": item.get("returnQuantity"),
                    "low_sample": item.get("lowSample"),
                }
            )
        return {
            "data_status": value.get("dataStatus"),
            "slice_status": value.get("sliceStatus"),
            "financial_metric_status": value.get("financialMetricStatus"),
            "methodology_version": value.get("methodologyVersion"),
            "coverage": value.get("coverage") or {},
            "report_coverage": value.get("reportCoverage"),
            "period_context": value.get("periodContext") or {},
            "kpis": value.get("kpis") or {},
            "components": value.get("components") or {},
            "partial_periods": [
                {
                    "period_start": item.get("periodStart"),
                    "period_end": item.get("periodEnd"),
                    "financial_metric_status": item.get("financialMetricStatus"),
                    "kpis": item.get("kpis") or {},
                    "components": item.get("components") or {},
                }
                for item in (value.get("partialPeriods") or [])[:2]
                if isinstance(item, dict)
            ],
            "insight": value.get("insight") or {},
            "factor_states": [
                {
                    "code": item.get("code"),
                    "label": item.get("label"),
                    "status": item.get("status"),
                    "message": item.get("message"),
                }
                for item in (value.get("factorStates") or [])[:5]
                if isinstance(item, dict)
            ],
            "top_products": top_products,
            "recommendations": recommendations,
            "boundary": (
                "Only calculated aggregates and evidence. Return causes are "
                "not established by this data. Null financial KPIs are unavailable "
                "and must not be explained or treated as zero."
            ),
        }

    def _search_sku(
        self,
        db: Session,
        report: ReportRun,
        query: str,
        *,
        period: tuple[date, date] | None = None,
    ) -> dict[str, Any]:
        result = repository.query_report_rows(
            db,
            report,
            query=query[:120],
            period_start=period[0] if period else None,
            period_end=period[1] if period else None,
            limit=8,
        )
        return {
            "query": query[:120],
            "total": result["total"],
            "items": [
                {
                    "product": row.get("product"),
                    "article_1c": row.get("article1c"),
                    "article_wb": row.get("articleWb"),
                    "barcode": row.get("barcode"),
                    "nm_id": row.get("nmId"),
                    "profit": row.get("profit"),
                    "status": row.get("status"),
                    "loss_driver": row.get("lossDriver"),
                }
                for row in result["items"]
            ],
            "limitations": self._limitations(
                repository.report_summary_payload(db, report)
            ),
        }

    def _loss_drivers(
        self,
        db: Session,
        report: ReportRun,
        summary: dict[str, Any],
        *,
        period: tuple[date, date] | None = None,
    ) -> dict[str, Any]:
        result = repository.query_report_rows(
            db,
            report,
            preset="losses",
            period_start=period[0] if period else None,
            period_end=period[1] if period else None,
            limit=25,
        )
        losses = result["items"]
        driver_totals: dict[str, dict[str, Any]] = {}
        for row in losses:
            driver = row.get("lossDriver") or "Нужно уточнить"
            bucket = driver_totals.setdefault(
                driver,
                {"driver": driver, "rows": 0, "profit": 0.0},
            )
            bucket["rows"] += 1
            bucket["profit"] += float(row.get("profit") or 0)
        return {
            "loss_rows": int(result["total"]),
            "drivers": sorted(
                driver_totals.values(), key=lambda item: float(item["profit"])
            )[:10],
            "top_losses": [
                {
                    "product": row.get("product"),
                    "article_1c": row.get("article1c"),
                    "barcode": row.get("barcode"),
                    "profit": row.get("profit"),
                    "loss_driver": row.get("lossDriver"),
                    "status": row.get("status"),
                }
                for row in losses[:10]
            ],
            "limitations": self._limitations(summary),
        }

    def _data_quality(
        self,
        db: Session,
        report: ReportRun,
        summary: dict[str, Any],
        *,
        period: tuple[date, date] | None = None,
    ) -> dict[str, Any]:
        result = repository.query_report_rows(
            db,
            report,
            preset="review",
            period_start=period[0] if period else None,
            period_end=period[1] if period else None,
            limit=25,
        )
        rows = result["items"]
        buckets: dict[str, dict[str, Any]] = {}
        for row in rows:
            status = row.get("status") or "Не указан"
            bucket = buckets.setdefault(
                status,
                {
                    "status": status,
                    "rows": 0,
                    "examples": [],
                },
            )
            bucket["rows"] += 1
            if len(bucket["examples"]) < 5:
                bucket["examples"].append(
                    {
                        "product": row.get("product"),
                        "article_1c": row.get("article1c"),
                        "barcode": row.get("barcode"),
                        "reason": row.get("statusReason"),
                    }
                )
        return {
            "total_rows": int((summary.get("kpis") or {}).get("rowCount") or 0),
            "review_rows": int(result["total"]),
            "quality": summary.get("quality") or {},
            "statuses": sorted(
                buckets.values(), key=lambda item: int(item["rows"]), reverse=True
            ),
            "limitations": self._limitations(summary),
        }

    def _period_comparison(self, summary: dict[str, Any]) -> dict[str, Any]:
        return {
            "period": summary["meta"]["period"],
            "monthly": summary.get("monthly", []),
            "note": (
                "Сравнение сейчас выполняется внутри одного расчёта отчёта по месяцам. "
                "Между разными расчетами сравнение появится после накопления истории."
            ),
            "limitations": self._limitations(summary),
        }

    def _fallback_answer(
        self, tool_outputs: dict[str, Any], question: str
    ) -> str:
        summary = tool_outputs["get_report_summary"]
        intent = self._question_intent(question)
        period = str(summary.get("period") or "текущий период")
        conclusion = self._summary_result_conclusion(summary)
        facts: list[str] = [
            f"Выручка после СПП: {self._money_or_na(summary.get('revenue'))}",
            (
                f"Убыточных строк: {int(summary.get('loss_rows') or 0)} "
                f"из {int(summary.get('rows') or 0)}"
            ),
        ]
        next_step = "Откройте сводку и начните с показателя с наибольшим влиянием."

        loss_output = tool_outputs.get("get_loss_drivers") or {}
        top_losses = loss_output.get("top_losses", [])
        quality = tool_outputs.get("get_data_quality_issues") or {}

        if intent == "refresh":
            refresh = tool_outputs.get("refresh_onec_and_rebuild_report") or {}
            if refresh.get("newReportRunId"):
                conclusion = (
                    f"Обновление только для чтения завершено: создан расчёт "
                    f"{refresh['newReportRunId']}"
                )
                next_step = (
                    "Откройте новый расчёт "
                    f"{refresh['newReportRunId']} после дозагрузки 1С "
                    "только для чтения и "
                    "сравните готовность со старым отчётом."
                )
            else:
                refresh_reason = (
                    refresh.get("message") or refresh.get("status") or "нужна проверка"
                )
                conclusion = f"Новый расчёт не создан: {refresh_reason}"
                next_step = (
                    "Проверьте причину, по которой новый расчёт не создан: "
                    f"{refresh_reason}."
                )
            facts = [
                f"Исходный период: {period}",
                str(refresh.get("message") or "Текущий отчёт не изменялся"),
            ]
        elif intent == "readiness":
            readiness = summary.get("readiness") or {}
            score = readiness.get("score")
            score_text = (
                f"{int(score)}/100" if isinstance(score, (int, float)) else "без оценки"
            )
            conclusion = (
                f"{readiness.get('label') or 'Готовность ещё не рассчитана'}: "
                f"{score_text}"
            )
            reasons = [
                *list(readiness.get("blockingReasons") or []),
                *list(readiness.get("reviewReasons") or []),
            ]
            facts = [
                self._readiness_reason_text(reason)
                for reason in reasons
                if self._readiness_reason_text(reason)
            ] or ["Блокирующих или контрольных причин не найдено"]
            next_step = str(
                readiness.get("nextAction")
                or "Откройте сводку и проверьте статус отправки отчёта."
            )
        elif intent == "cost_quality":
            summary_quality = summary.get("quality") or {}
            missing_cost = int(summary_quality.get("missingCostRows") or 0)
            review_rows = int(quality.get("review_rows") or 0)
            conclusion = (
                f"Строк с себестоимостью, требующей проверки: {missing_cost}"
                if missing_cost
                else "Строк без подтверждённой себестоимости не найдено"
            )
            facts = []
            verification = tool_outputs.get("verify_onec_cost") or {}
            if verification.get("message"):
                facts.append(f"Проверка 1С: {verification['message']}")
            if review_rows:
                facts.append(f"Всего строк к проверке качества: {review_rows}")
            facts.extend(
                f"{item.get('status') or 'Статус не указан'} — "
                f"строк: {int(item.get('rows') or 0)}"
                for item in list(quality.get("statuses") or [])[:3]
            )
            if not facts:
                facts.append("Дополнительных статусов качества данных не найдено")
            next_step = (
                "Откройте проверку себестоимости и разберите проблемные строки."
                if missing_cost or review_rows
                else "Откройте сводку и продолжите проверку отчёта."
            )
        elif intent == "loss":
            loss_rows = int(loss_output.get("loss_rows") or 0)
            if top_losses:
                first = top_losses[0]
                conclusion = (
                    f"Главная убыточная позиция — "
                    f"{first.get('product') or 'товар без названия'}: "
                    f"{self._money_or_na(first.get('profit'))}; драйвер — "
                    f"{first.get('loss_driver') or 'нужно уточнить'}"
                )
                facts = [
                    f"Убыточных строк в текущем отборе: {loss_rows}",
                    *[
                        f"{item.get('product') or 'Товар без названия'}: "
                        f"{self._money_or_na(item.get('profit'))}; драйвер — "
                        f"{item.get('loss_driver') or 'нужно уточнить'}"
                        for item in top_losses[1:3]
                    ],
                ]
                next_step = (
                    "Откройте убыточные продажи и проверьте позиции "
                    "с наибольшим отрицательным результатом."
                )
            else:
                conclusion = "В текущем отборе убыточных строк нет"
                facts = [
                    f"Проверено строк: {int(summary.get('rows') or 0)}",
                    "Прибыль до налогов: "
                    + self._money_or_na(
                        summary.get("profit"), missing="не рассчитана"
                    ),
                ]
                next_step = "Откройте сводку и проверьте остальные зоны риска."
        elif intent == "margin":
            margin = summary.get("margin")
            profit = summary.get("profit")
            if margin is None and profit is None:
                conclusion = f"За {period} прибыль и маржа пока не рассчитаны"
            elif margin is None:
                conclusion = (
                    f"За {period} прибыль до налогов — "
                    f"{self._money_or_na(profit)}, маржа пока не рассчитана"
                )
            else:
                conclusion = f"Маржа за {period} составляет {float(margin):.1%}"
            summary_quality = summary.get("quality") or {}
            facts = [
                f"Выручка после СПП: {self._money_or_na(summary.get('revenue'))}",
                "Прибыль до налогов: "
                + self._money_or_na(profit, missing="не рассчитана"),
            ]
            missing_cost = int(summary_quality.get("missingCostRows") or 0)
            if missing_cost:
                facts.append(
                    f"Без подтверждённой себестоимости: {missing_cost} строк"
                )
            next_step = (
                "Откройте проверку себестоимости: без неё маржу нельзя считать полной."
                if margin is None or missing_cost
                else "Откройте сводку и сравните маржу с динамикой периода."
            )
        elif intent == "sku":
            search = tool_outputs.get("search_sku") or {}
            items = list(search.get("items") or [])
            if items:
                conclusion = (
                    f"По запросу найдено строк: {int(search.get('total') or 0)}"
                )
                facts = [
                    f"{item.get('product') or item.get('article_1c') or 'Товар'}: "
                    f"результат {self._money_or_na(item.get('profit'))}; "
                    f"статус — {item.get('status') or 'не указан'}"
                    for item in items[:3]
                ]
                next_step = "Откройте найденный товар и проверьте его расчётную строку."
            else:
                conclusion = "По запросу товар или SKU не найден"
                facts = [
                    f"Поисковый запрос: {search.get('query') or question}",
                    "Поиск выполнялся только в текущем report scope",
                ]
                next_step = "Уточните артикул, штрихкод, nmId или название товара."
        elif intent == "period":
            comparison = tool_outputs.get("compare_periods") or {}
            monthly = list(comparison.get("monthly") or [])
            if len(monthly) >= 2:
                first = monthly[0]
                last = monthly[-1]
                conclusion = (
                    f"Прибыль изменилась с {self._money_or_na(first.get('profit'))} "
                    f"в {first.get('month') or 'первом месяце'} до "
                    f"{self._money_or_na(last.get('profit'))} "
                    f"в {last.get('month') or 'последнем месяце'}"
                )
            elif monthly:
                conclusion = "Для сравнения доступен только один месяц"
            else:
                conclusion = "В текущем расчёте нет месячной динамики для сравнения"
            facts = [
                f"{item.get('month') or 'Месяц'}: выручка "
                f"{self._money_or_na(item.get('revenue'))}, прибыль "
                f"{self._money_or_na(item.get('profit'))}, маржа "
                f"{self._margin_or_na(item.get('margin'))}"
                for item in monthly[-3:]
            ] or [f"Доступный период отчёта: {period}"]
            next_step = "Откройте сводку и сопоставьте месяцы с качеством данных."
        else:
            if top_losses:
                first = top_losses[0]
                facts.append(
                    f"Главная убыточная позиция — "
                    f"{first.get('product') or 'товар без названия'}: "
                    f"{self._money_or_na(first.get('profit'))}"
                )
            elif quality.get("statuses"):
                first_status = quality["statuses"][0]
                facts.append(
                    f"Главная проверка качества — "
                    f"{first_status.get('status') or 'статус не указан'}: "
                    f"{int(first_status.get('rows') or 0)} строк"
                )

        return self._format_fallback_answer(
            conclusion=conclusion,
            facts=facts,
            next_step=next_step,
            limitations=list(summary.get("limitations") or LIMITATIONS),
        )

    def _summary_result_conclusion(self, summary: dict[str, Any]) -> str:
        period = str(summary.get("period") or "текущий период")
        profit = summary.get("profit")
        margin = summary.get("margin")
        if profit is None and margin is None:
            return f"За {period} прибыль и маржа пока не рассчитаны"
        if profit is None:
            return (
                f"За {period} прибыль пока не рассчитана, "
                f"маржа составляет {float(margin):.1%}"
            )
        if margin is None:
            return (
                f"За {period} прибыль до налогов — {self._money_or_na(profit)}, "
                "маржа пока не рассчитана"
            )
        return (
            f"За {period} прибыль до налогов — {self._money_or_na(profit)}, "
            f"маржа — {float(margin):.1%}"
        )

    def _format_fallback_answer(
        self,
        *,
        conclusion: str,
        facts: list[str],
        next_step: str,
        limitations: list[str],
    ) -> str:
        fact_lines = [
            f"- {self._sentence(item)}" for item in facts if str(item).strip()
        ][:3]
        if not fact_lines:
            fact_lines = ["- Дополнительных рассчитанных фактов нет."]
        limitation = (
            f"\n\nОграничение: {self._sentence(limitations[0])}"
            if limitations
            else ""
        )
        return (
            "Вывод\n"
            f"{self._sentence(conclusion)}\n\n"
            "Факты\n"
            f"{chr(10).join(fact_lines)}\n\n"
            "Следующий шаг\n"
            f"{self._sentence(next_step)}"
            f"{limitation}"
        )

    def _readiness_reason_text(self, reason: Any) -> str:
        if isinstance(reason, str):
            return reason.strip()
        if isinstance(reason, dict):
            return str(
                reason.get("message")
                or reason.get("label")
                or reason.get("title")
                or ""
            ).strip()
        return ""

    def _sentence(self, value: Any) -> str:
        text = str(value or "").strip()
        text = re.sub(r"\.{2,}$", ".", text)
        if not text:
            return ""
        return text if text.endswith((".", "!", "?", "…")) else f"{text}."

    def _money_or_na(self, value: Any, *, missing: str = "не рассчитано") -> str:
        return missing if value is None else f"{float(value):,.0f} ₽"

    def _margin_or_na(self, value: Any) -> str:
        return "не рассчитана" if value is None else f"{float(value):.1%}"

    def _base_client_draft(self, summary: dict[str, Any]) -> str:
        evidence = repository.client_draft_evidence_payload(summary)
        kpi = evidence["kpi"]
        margin = kpi["margin"]
        margin_text = "н/д" if margin is None else f"{margin:.1%}"
        quality = evidence["quality"]
        review_rows = sum(
            int(item["rows"]) for item in quality if item["status"] != "ОК"
        )
        top_loss = evidence["topLosses"][0] if evidence["topLosses"] else None
        check_lines = []
        if review_rows:
            check_lines.append(
                f"- Проверить строки со статусами качества данных: {review_rows} строк."
            )
        if top_loss:
            check_lines.append(
                "- Разобрать главный убыточный товар: "
                f"{top_loss['product']} ({float(top_loss['profit'] or 0):,.0f} ₽)."
            )
        if not check_lines:
            check_lines.append(
                "- Отдельных критичных статусов качества данных не найдено."
            )
        limitations = repository.client_draft_limitations(summary)
        return (
            "Ключевой вывод\n"
            f"За период {kpi['period']} расчет показывает выручку после СПП "
            f"{self._money_or_na(kpi.get('revenue'))} и прибыль до налогов "
            f"{self._money_or_na(kpi.get('profit'))}. Маржа по расчетной витрине: "
            f"{margin_text}.\n\n"
            "Факты\n"
            f"- В расчете {int(kpi['rows'])} строк товаров/SKU.\n"
            f"- Убыточных строк: {int(kpi['lossRows'])}.\n"
            f"- Методика: {kpi['methodologyVersion']}.\n\n"
            "Что требует проверки\n"
            f"{chr(10).join(check_lines)}\n\n"
            "Ограничения\n"
            f"{chr(10).join(f'- {item}' for item in limitations[:3])}\n\n"
            "Следующий шаг\n"
            "Проверить строки с неполной себестоимостью, маппингом или "
            "отрицательной маржинальностью и после сверки зафиксировать итоговый "
            "комментарий для клиента."
        )

    def _openai_client_draft(
        self,
        *,
        summary: dict[str, Any],
        evidence: dict[str, Any],
        limitations: list[str],
        latest_draft: str,
        instruction: str,
    ) -> str | None:
        try:
            from openai import OpenAI
        except ImportError:
            return None
        try:
            client = OpenAI(
                api_key=self.settings.resolved_openai_api_key,
                timeout=self.settings.openai_timeout_seconds,
            )
            response = client.responses.create(
                model=self.settings.openai_model,
                input=[
                    {
                        "role": "developer",
                        "content": load_prompt("client_draft"),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "instruction": instruction,
                                "latest_draft": latest_draft,
                                "safe_evidence": evidence,
                                "limitations": limitations,
                                "management_report": repository.management_report_text(
                                    summary
                                ),
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                store=False,
                include=["reasoning.encrypted_content"],
            )
            return getattr(response, "output_text", None)
        except Exception:
            return None

    def _is_conversational_message(self, question: str) -> bool:
        normalized = " ".join(question.casefold().split())
        normalized = re.sub(r"^[\s!?.,:;…—-]+|[\s!?.,:;…—-]+$", "", normalized)
        return normalized in CONVERSATIONAL_MESSAGES

    def _normalize_client_draft(self, content: str, summary: dict[str, Any]) -> str:
        lines = [
            line
            for line in content.splitlines()
            if not repository.client_draft_contains_forbidden_text(line)
        ]
        text = "\n".join(lines).strip()
        if not text:
            return self._base_client_draft(summary)
        if not all(
            section.lower() in text.lower()
            for section in repository.CLIENT_DRAFT_REQUIRED_SECTIONS
        ):
            return self._base_client_draft(summary)
        return text

    def _question_intent(self, question: str) -> str:
        text = self._normalized_question(question)
        if self._explicit_refresh_intent(text):
            return "refresh"
        if any(
            token in text
            for token in ("готов", "отправ", "блокир", "что мешает")
        ):
            return "readiness"
        if any(
            token in text
            for token in (
                "себестоим",
                "качест дан",
                "статус дан",
                "маппинг",
                "mapping",
                "неполные данные",
            )
        ):
            return "cost_quality"
        if any(
            token in text
            for token in ("убыт", "убыточ", "в минус", "отрицательн", "потер")
        ):
            return "loss"
        if any(token in text for token in ("марж", "рентабель")):
            return "margin"
        if any(
            token in text
            for token in (
                "артикул",
                "баркод",
                "штрихкод",
                "sku",
                "товар",
                "nm",
                "карточ",
                "остат",
            )
        ):
            return "sku"
        if any(
            token in text
            for token in ("сравн", "динамик", "месяц", "период", "тренд", "изменил")
        ):
            return "period"
        if any(
            token in text
            for token in (
                "управлен",
                "записк",
                "главн",
                "важн",
                "вывод",
                "итог",
                "резюм",
            )
        ):
            return "management"
        return "summary"

    def _normalized_question(self, question: str) -> str:
        return " ".join(question.casefold().replace("ё", "е").split())

    def _planned_tool_names(self, question: str) -> list[str]:
        text = self._normalized_question(question)
        intent = self._question_intent(text)
        names: list[str]
        if intent == "refresh":
            names = ["get_data_quality_issues", "refresh_onec_and_rebuild_report"]
        elif intent == "cost_quality":
            names = ["get_data_quality_issues"]
            if self._explicit_onec_verification_intent(text):
                names.append("verify_onec_cost")
        elif intent == "loss":
            names = ["get_loss_drivers"]
        elif intent == "sku":
            names = ["search_sku"]
            verify_words = ("проверь", "проверить", "сверь", "сверить")
            if any(word in text for word in verify_words):
                if "остат" in text:
                    names.append("verify_wb_stock")
                elif "карточ" in text or "wb" in text:
                    names.append("verify_wb_card")
        elif intent == "period":
            names = ["compare_periods"]
        elif intent in {"management", "summary"}:
            names = ["get_loss_drivers", "get_data_quality_issues"]
        else:
            names = []
        return list(dict.fromkeys(names))

    def _explicit_onec_verification_intent(self, text: str) -> bool:
        verify_words = ("проверь", "проверить", "сверь", "сверить")
        data_words = ("1с", "себестоим")
        return any(word in text for word in verify_words) and any(
            word in text for word in data_words
        )

    def _explicit_refresh_intent(self, text: str) -> bool:
        refresh_words = (
            "дозагрузи",
            "загрузи 1с",
            "обнови 1с",
            "пересобери",
            "пересчитать",
            "пересчитай",
            "refresh",
            "auto-refresh",
        )
        data_words = (
            "себестоим",
            "маппинг",
            "mapping",
            "1с",
            "остат",
            "опиу",
            "парт",
            "услуг",
            "упд",
        )
        return any(word in text for word in refresh_words) and any(
            word in text for word in data_words
        )

    def _refresh_onec_and_rebuild_report(
        self,
        db: Session,
        *,
        user: User,
        thread: AiThread,
        report: ReportRun,
        reason: str,
    ) -> dict[str, Any]:
        if not repository.has_role(user, repository.STAFF_ROLES, report.tenant_id):
            return {
                "status": "blocked",
                "reviewStatus": "needs_staff",
                "message": (
                    "Для дозагрузки 1С нужна проверка консультанта. "
                    "Клиентский доступ не запускает обновление данных."
                ),
                "limitations": LIMITATIONS,
            }
        if not self.auto_refresh_service:
            return {
                "status": "unavailable",
                "reviewStatus": "needs_configuration",
                "message": (
                    "Сервис автоматического обновления не подключён. "
                    "Данные не менялись."
                ),
                "limitations": LIMITATIONS,
            }
        repository.add_ai_event(
            db,
            thread=thread,
            user=user,
            event_type="tool_progress",
            title="Дозагружаю 1С без изменения данных",
            message="Запускаю чтение OData. Исходные данные не попадут в чат.",
            status="running",
            tool_name="refresh_onec_and_rebuild_report",
            visibility="staff",
            payload={"status": "running"},
        )
        try:
            job = self.auto_refresh_service.run(
                db,
                user=user,
                report=report,
                reason=reason,
                thread_id=thread.id,
            )
        except AutoRefreshDisabledError as exc:
            return {
                "status": "disabled",
                "reviewStatus": "needs_configuration",
                "message": str(exc),
                "limitations": LIMITATIONS,
            }
        except AutoRefreshBusyError as exc:
            return {
                "status": "busy",
                "reviewStatus": "needs_review",
                "message": str(exc),
                "limitations": LIMITATIONS,
            }
        except AutoRefreshUnavailableError as exc:
            return {
                "status": "unavailable",
                "reviewStatus": "needs_review",
                "message": str(exc),
                "limitations": LIMITATIONS,
            }
        repository.add_ai_event(
            db,
            thread=thread,
            user=user,
            event_type="tool_progress",
            title=(
                "Обновление поставлено в очередь"
                if job.get("status") == "queued"
                else "Пересчитываю отчет"
            ),
            message=(
                "Отдельный процесс обновит 1С и соберёт новый расчёт. "
                "Текущий отчёт остаётся без изменений."
                if job.get("status") == "queued"
                else "Собираю новый расчёт отчёта. "
                "Текущий отчёт остаётся без изменений."
            ),
            status="ok" if job.get("newReportRunId") else job.get("status", "ok"),
            tool_name="refresh_onec_and_rebuild_report",
            visibility="staff",
            payload=self._refresh_event_payload(job),
        )
        if job.get("newReportRunId"):
            repository.add_ai_event(
                db,
                thread=thread,
                user=user,
                event_type="tool_completed",
                title="Создан новый отчет",
                message=(
                    "Новый расчёт создан и доступен для выбора. "
                    "Старый расчёт отчёта не менялся."
                ),
                status=job.get("status", "ok"),
                tool_name="refresh_onec_and_rebuild_report",
                visibility="staff",
                payload=self._refresh_event_payload(job),
            )
            repository.audit(
                db,
                action="ai_onec_auto_refresh_completed",
                user=user,
                tenant_id=report.tenant_id,
                entity_type="source_refresh_run",
                entity_id=job["id"],
                payload={
                    "source_report_run_id": report.id,
                    "new_report_run_id": job.get("newReportRunId"),
                    "status": job.get("status"),
                },
            )
        return {
            "status": job.get("status", "ok"),
            "reviewStatus": "partial_source"
            if job.get("status") == "partial_source"
            else "ready"
            if job.get("newReportRunId")
            else "needs_review",
            "message": self._refresh_message(job),
            "jobId": job.get("id"),
            "newReportRunId": job.get("newReportRunId"),
            "sourceReportRunId": job.get("sourceReportRunId"),
            "collections": job.get("collections", []),
            "limitations": [
                "Дозагрузка 1С выполняется без изменения исходных данных.",
                "Старый расчёт отчёта не изменяется.",
                (
                    "Частичные 1С-коллекции помечаются partial_source, "
                    "без подстановки нулей."
                ),
            ],
        }

    def _refresh_message(self, job: dict[str, Any]) -> str:
        if job.get("newReportRunId"):
            return f"Создан новый отчет {job['newReportRunId']}."
        if job.get("status") == "failed":
            return (
                "Автоматическое обновление завершилось ошибкой. Данные не изменялись."
            )
        return (
            job.get("errorMessage")
            or "Автоматическое обновление не создало новый отчёт."
        )

    def _refresh_event_payload(self, job: dict[str, Any]) -> dict[str, Any]:
        collections = job.get("collections") or []
        loaded = sum(1 for item in collections if item.get("status") == "loaded")
        partial = sum(1 for item in collections if item.get("status") != "loaded")
        return {
            "status": job.get("status"),
            "jobId": job.get("id"),
            "sourceReportRunId": job.get("sourceReportRunId"),
            "newReportRunId": job.get("newReportRunId"),
            "message": self._refresh_message(job),
            "summary": {
                "loaded": loaded,
                "partial": partial,
                "newReport": job.get("newReportRunId"),
            },
            "limitations": [
                "Raw 1С payload не показывается в чате.",
                "Старый отчет не менялся.",
            ],
        }

    def _limitations(self, summary: dict[str, Any]) -> list[str]:
        limitations: list[str] = []
        period_status = str(summary.get("meta", {}).get("periodStatus") or "")
        if (
            "неполн" in period_status.casefold()
            or "предвар" in period_status.casefold()
        ):
            limitations.append(
                f"Период отчета имеет статус «{period_status}» "
                "и не должен читаться как полный."
            )
        limitations.extend(
            [
                summary.get("meta", {}).get("returnReasonLimitation")
                or LIMITATIONS[0],
                LIMITATIONS[1],
                LIMITATIONS[2],
            ]
        )
        return limitations

    def _tool_title(self, tool_name: str) -> str:
        return {
            "get_report_summary": "Смотрю KPI",
            "search_sku": "Ищу товар/SKU",
            "get_loss_drivers": "Разбираю убыточность",
            "get_data_quality_issues": "Проверяю качество данных",
            "compare_periods": "Сравниваю месяцы",
            "draft_management_report": "Готовлю управленческий отчет",
            "verify_onec_cost": "Проверяю себестоимость 1С",
            "verify_wb_card": "Проверяю карточку WB",
            "verify_wb_stock": "Проверяю остатки WB",
            "refresh_onec_and_rebuild_report": "Нашел нехватку 1С-данных",
        }.get(tool_name, "Проверяю данные")

    def _tool_start_message(self, tool_name: str) -> str:
        return {
            "get_report_summary": "Беру период, маржу, статусы и ограничения.",
            "search_sku": (
                "Ищу совпадения по товару, артикулу, штрихкоду или номеру WB."
            ),
            "get_loss_drivers": "Сортирую строки с отрицательной прибылью.",
            "get_data_quality_issues": (
                "Собираю строки с отсутствующими данными и требующие проверки."
            ),
            "compare_periods": "Сравниваю месяцы внутри текущего расчета.",
            "draft_management_report": "Собираю выводы из уже посчитанных фактов.",
            "verify_onec_cost": (
                "Запрашиваю проверку без изменения данных, если она включена."
            ),
            "verify_wb_card": (
                "Запрашиваю проверку без изменения данных, если она включена."
            ),
            "verify_wb_stock": (
                "Запрашиваю проверку без изменения данных, если она включена."
            ),
            "refresh_onec_and_rebuild_report": (
                "Проверяю роль, разрешение функции и запускаю отдельное чтение данных."
            ),
        }.get(tool_name, "Проверяю разрешенный источник.")

    def _tool_done_message(self, tool_name: str, output: dict[str, Any]) -> str:
        if tool_name == "search_sku":
            if output.get("total") is None:
                return "Поиск SKU ограничен: нет полной закрытой недели."
            return f"Найдено строк: {int(output.get('total') or 0)}."
        if tool_name == "get_loss_drivers":
            if output.get("loss_rows") is None:
                return "Убыточность не рассчитана: нет полной закрытой недели."
            return f"Убыточных строк: {int(output.get('loss_rows') or 0)}."
        if tool_name == "get_data_quality_issues":
            return f"Статусов качества: {len(output.get('statuses') or [])}."
        if tool_name.startswith("verify_"):
            return output.get("message") or "Проверка завершена."
        if tool_name == "refresh_onec_and_rebuild_report":
            return output.get("message") or "Автоматическое обновление завершено."
        if tool_name == "draft_management_report":
            return "Черновик отчета готов."
        return "Готово."

    def _tool_input_payload(
        self, tool_name: str, arguments: dict[str, Any], question: str
    ) -> dict[str, Any]:
        if tool_name == "search_sku":
            return {"query": str(arguments.get("query") or question)[:120]}
        if tool_name.startswith("verify_"):
            return {"lookup": str(arguments.get("lookup") or question)[:120]}
        if tool_name == "refresh_onec_and_rebuild_report":
            return {"reason": str(arguments.get("reason") or question)[:240]}
        return {}

    def _tool_event_payload(
        self, tool_name: str, output: dict[str, Any]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": output.get("status", "ok"),
            "limitations": output.get("limitations", []),
        }
        if tool_name == "get_report_summary":
            payload["summary"] = {
                "period": output.get("period"),
                "revenue": output.get("revenue"),
                "profit": output.get("profit"),
                "lossRows": output.get("loss_rows"),
                "rows": output.get("rows"),
            }
        elif tool_name == "search_sku":
            payload["summary"] = {"total": output.get("total", 0)}
            payload["evidence"] = [
                {
                    "label": item.get("product"),
                    "article1c": item.get("article_1c"),
                    "barcode": item.get("barcode"),
                    "profit": item.get("profit"),
                    "status": item.get("status"),
                }
                for item in output.get("items", [])[:5]
            ]
        elif tool_name == "get_loss_drivers":
            payload["summary"] = {"lossRows": output.get("loss_rows", 0)}
            payload["evidence"] = [
                {
                    "label": item.get("product"),
                    "barcode": item.get("barcode"),
                    "profit": item.get("profit"),
                    "driver": item.get("loss_driver"),
                    "status": item.get("status"),
                }
                for item in output.get("top_losses", [])[:5]
            ]
        elif tool_name == "get_data_quality_issues":
            payload["summary"] = {"totalRows": output.get("total_rows", 0)}
            payload["evidence"] = [
                {
                    "label": item.get("status"),
                    "rows": item.get("rows"),
                }
                for item in output.get("statuses", [])[:5]
            ]
        elif tool_name == "compare_periods":
            payload["summary"] = {"period": output.get("period")}
            payload["evidence"] = output.get("monthly", [])[:5]
        elif tool_name == "draft_management_report":
            payload["summary"] = {"report": "draft_ready"}
        elif tool_name.startswith("verify_"):
            payload.update(
                {
                    "reviewStatus": output.get("reviewStatus"),
                    "sourceType": output.get("sourceType"),
                    "checkType": output.get("checkType"),
                    "lookup": output.get("lookup"),
                    "message": output.get("message"),
                }
            )
        elif tool_name == "refresh_onec_and_rebuild_report":
            payload.update(
                {
                    "reviewStatus": output.get("reviewStatus"),
                    "message": output.get("message"),
                    "jobId": output.get("jobId"),
                    "sourceReportRunId": output.get("sourceReportRunId"),
                    "newReportRunId": output.get("newReportRunId"),
                    "summary": {
                        "newReport": output.get("newReportRunId"),
                        "collections": len(output.get("collections") or []),
                    },
                }
            )
        return payload

    def _function_calls(self, response: Any) -> list[dict[str, Any]]:
        calls = []
        for item in getattr(response, "output", []) or []:
            item_type = self._item_value(item, "type")
            if item_type != "function_call":
                continue
            name = self._item_value(item, "name")
            call_id = self._item_value(item, "call_id")
            arguments_raw = self._item_value(item, "arguments") or "{}"
            try:
                arguments = json.loads(arguments_raw)
            except json.JSONDecodeError:
                arguments = {}
            if name and call_id:
                calls.append({"name": name, "call_id": call_id, "arguments": arguments})
        return calls

    def _response_output_items(self, response: Any) -> list[Any]:
        # The Responses SDK output objects are valid follow-up input items as-is.
        # Serializing them with model_dump() leaks response-only fields such as
        # `status` and causes the API to reject the next tool-loop request.
        return list(getattr(response, "output", []) or [])

    def _item_value(self, item: Any, key: str) -> Any:
        if isinstance(item, dict):
            return item.get(key)
        return getattr(item, key, None)

    def _tool_specs(self) -> list[dict[str, Any]]:
        empty = {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }
        text_param = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Товар, артикул, штрихкод или номер WB для поиска в отчёте."
                    ),
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        }
        lookup_param = {
            "type": "object",
            "properties": {
                "lookup": {
                    "type": "string",
                    "description": (
                        "Артикул, штрихкод или номер WB для проверки "
                        "без изменения данных."
                    ),
                }
            },
            "required": ["lookup"],
            "additionalProperties": False,
        }
        refresh_param = {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": (
                        "Коротко, каких 1С-данных не хватает: себестоимость, "
                        "маппинг, ОПиУ, партии, услуги, остатки или сверка."
                    ),
                }
            },
            "required": ["reason"],
            "additionalProperties": False,
        }
        return [
            {
                "type": "function",
                "name": "get_report_summary",
                "description": (
                    "Вернуть краткую сводку показателей текущего расчёта отчёта."
                ),
                "parameters": empty,
                "strict": True,
            },
            {
                "type": "function",
                "name": "search_sku",
                "description": (
                    "Найти SKU или товары по названию, артикулу, штрихкоду "
                    "или номеру WB."
                ),
                "parameters": text_param,
                "strict": True,
            },
            {
                "type": "function",
                "name": "get_loss_drivers",
                "description": (
                    "Показать главные драйверы убыточности и топ убыточных строк."
                ),
                "parameters": empty,
                "strict": True,
            },
            {
                "type": "function",
                "name": "get_data_quality_issues",
                "description": (
                    "Показать статусы качества данных и примеры строк на проверку."
                ),
                "parameters": empty,
                "strict": True,
            },
            {
                "type": "function",
                "name": "compare_periods",
                "description": "Сравнить месяцы внутри текущего расчета.",
                "parameters": empty,
                "strict": True,
            },
            {
                "type": "function",
                "name": "draft_management_report",
                "description": (
                    "Сформировать черновик управленческого отчета по расчету."
                ),
                "parameters": empty,
                "strict": True,
            },
            {
                "type": "function",
                "name": "verify_onec_cost",
                "description": (
                    "Запросить проверку себестоимости 1С без изменения данных, если "
                    "проверки подключений включены."
                ),
                "parameters": lookup_param,
                "strict": True,
            },
            {
                "type": "function",
                "name": "verify_wb_card",
                "description": (
                    "Запросить проверку карточки WB без изменения данных, если "
                    "проверки подключений включены."
                ),
                "parameters": lookup_param,
                "strict": True,
            },
            {
                "type": "function",
                "name": "verify_wb_stock",
                "description": (
                    "Запросить проверку остатка WB без изменения данных, если "
                    "проверки подключений включены."
                ),
                "parameters": lookup_param,
                "strict": True,
            },
            {
                "type": "function",
                "name": "refresh_onec_and_rebuild_report",
                "description": (
                    "Staff-only tool: если включен SHUMEYKO_AUTO_REFRESH_ENABLED "
                    "и вопрос связан с missing_cost, missing_mapping, needs_review, "
                    "partial_source, себестоимостью, маппингом, 1С-сверкой, "
                    "ОПиУ, партиями, услугами или остатками, прочитать данные 1С "
                    "через OData, пересобрать рабочую книгу и создать новый "
                    "расчёт отчёта. Старый отчёт не изменять."
                ),
                "parameters": refresh_param,
                "strict": True,
            },
        ]
