---
title: "FastAPI route inventory"
doc_type: generated_reference
status: active
audience: ["engineering", "operations"]
source_of_truth: false
source_spec: "docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md"
last_reconciled_with: "docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md @ 2026-07-17"
updated_at: "2026-07-17"
---

# FastAPI route inventory

> Этот файл сгенерирован из текущего OpenAPI приложения. Не редактируйте
> список маршрутов вручную; используйте
> `python scripts/generate_web_api_reference.py`.

Бизнес-права, роли и ограничения описаны в accepted web-spec. Этот файл
фиксирует только фактически объявленные HTTP-маршруты.

| Метод | Маршрут | Operation ID | OpenAPI summary |
|---|---|---|---|
| `GET` | `/` | `cabinet_index__get` | Cabinet Index |
| `GET` | `/accounting-workflows` | `accounting_workflows_page_accounting_workflows_get` | Accounting Workflows Page |
| `GET` | `/ai` | `ai_page_ai_get` | Ai Page |
| `GET` | `/api/accounting-workflows` | `accounting_workflow_cards_api_accounting_workflows_get` | Accounting Workflow Cards |
| `GET` | `/api/accounting-workflows/config` | `accounting_workflow_config_api_accounting_workflows_config_get` | Accounting Workflow Config |
| `POST` | `/api/accounting-workflows/corrections` | `accounting_workflow_correction_api_accounting_workflows_corrections_post` | Accounting Workflow Correction |
| `GET` | `/api/accounting-workflows/evidence/{attachment_id}` | `accounting_workflow_evidence_download_api_accounting_workflows_evidence__attachment_id__get` | Accounting Workflow Evidence Download |
| `POST` | `/api/accounting-workflows/followups/run-due` | `accounting_workflow_followups_run_due_api_accounting_workflows_followups_run_due_post` | Accounting Workflow Followups Run Due |
| `POST` | `/api/accounting-workflows/monthly-runs` | `accounting_workflow_monthly_run_api_accounting_workflows_monthly_runs_post` | Accounting Workflow Monthly Run |
| `GET` | `/api/accounting-workflows/supervisors` | `accounting_workflow_supervisors_api_accounting_workflows_supervisors_get` | Accounting Workflow Supervisors |
| `POST` | `/api/accounting-workflows/supervisors` | `accounting_workflow_supervisor_save_api_accounting_workflows_supervisors_post` | Accounting Workflow Supervisor Save |
| `GET` | `/api/accounting-workflows/{card_id}` | `accounting_workflow_card_api_accounting_workflows__card_id__get` | Accounting Workflow Card |
| `POST` | `/api/accounting-workflows/{card_id}/comments` | `accounting_workflow_comment_api_accounting_workflows__card_id__comments_post` | Accounting Workflow Comment |
| `POST` | `/api/accounting-workflows/{card_id}/deliveries` | `accounting_workflow_delivery_api_accounting_workflows__card_id__deliveries_post` | Accounting Workflow Delivery |
| `POST` | `/api/accounting-workflows/{card_id}/evidence` | `accounting_workflow_evidence_upload_api_accounting_workflows__card_id__evidence_post` | Accounting Workflow Evidence Upload |
| `POST` | `/api/accounting-workflows/{card_id}/followups/{followup_id}/actions` | `accounting_workflow_followup_action_api_accounting_workflows__card_id__followups__followup_id__actions_post` | Accounting Workflow Followup Action |
| `POST` | `/api/accounting-workflows/{card_id}/tasks/{task_id}/actions` | `accounting_workflow_task_action_api_accounting_workflows__card_id__tasks__task_id__actions_post` | Accounting Workflow Task Action |
| `POST` | `/api/accounting-workflows/{card_id}/transitions` | `accounting_workflow_transition_api_accounting_workflows__card_id__transitions_post` | Accounting Workflow Transition |
| `GET` | `/api/admin/audit` | `admin_audit_api_admin_audit_get` | Admin Audit |
| `POST` | `/api/admin/reports/import` | `admin_import_report_api_admin_reports_import_post` | Admin Import Report |
| `GET` | `/api/admin/users` | `admin_users_api_admin_users_get` | Admin Users |
| `POST` | `/api/admin/users` | `admin_create_user_api_admin_users_post` | Admin Create User |
| `PATCH` | `/api/admin/users/{user_id}` | `admin_update_user_api_admin_users__user_id__patch` | Admin Update User |
| `POST` | `/api/admin/users/{user_id}/reset-password` | `admin_reset_password_api_admin_users__user_id__reset_password_post` | Admin Reset Password |
| `GET` | `/api/ai/config` | `ai_config_api_ai_config_get` | Ai Config |
| `GET` | `/api/ai/threads` | `list_threads_api_ai_threads_get` | List Threads |
| `POST` | `/api/ai/threads` | `create_thread_api_ai_threads_post` | Create Thread |
| `GET` | `/api/ai/threads/{thread_id}` | `get_thread_api_ai_threads__thread_id__get` | Get Thread |
| `GET` | `/api/ai/threads/{thread_id}/events` | `get_thread_events_api_ai_threads__thread_id__events_get` | Get Thread Events |
| `POST` | `/api/ai/threads/{thread_id}/messages` | `send_message_api_ai_threads__thread_id__messages_post` | Send Message |
| `POST` | `/api/ai/threads/{thread_id}/messages/stream` | `stream_message_api_ai_threads__thread_id__messages_stream_post` | Stream Message |
| `POST` | `/api/auth/login` | `login_api_auth_login_post` | Login |
| `POST` | `/api/auth/logout` | `logout_api_auth_logout_post` | Logout |
| `POST` | `/api/chatkit` | `chatkit_protocol_api_chatkit_post` | Chatkit Protocol |
| `GET` | `/api/clients` | `list_clients_api_clients_get` | List Clients |
| `POST` | `/api/clients` | `create_client_api_clients_post` | Create Client |
| `POST` | `/api/clients/{client_id}/cabinets` | `create_client_cabinet_api_clients__client_id__cabinets_post` | Create Client Cabinet |
| `PATCH` | `/api/clients/{client_id}/cabinets/{cabinet_id}` | `update_client_cabinet_api_clients__client_id__cabinets__cabinet_id__patch` | Update Client Cabinet |
| `GET` | `/api/clients/{client_id}/companies/{company_id}/input-vat-policies` | `list_client_company_input_vat_policies_api_clients__client_id__companies__company_id__input_vat_policies_get` | List Client Company Input Vat Policies |
| `POST` | `/api/clients/{client_id}/companies/{company_id}/input-vat-policies` | `create_client_company_input_vat_policy_api_clients__client_id__companies__company_id__input_vat_policies_post` | Create Client Company Input Vat Policy |
| `PATCH` | `/api/clients/{client_id}/companies/{company_id}/input-vat-policies/{policy_id}/disable` | `disable_client_company_input_vat_policy_api_clients__client_id__companies__company_id__input_vat_policies__policy_id__disable_patch` | Disable Client Company Input Vat Policy |
| `PATCH` | `/api/clients/{client_id}/companies/{company_id}/onec-organization` | `update_client_company_onec_organization_api_clients__client_id__companies__company_id__onec_organization_patch` | Update Client Company Onec Organization |
| `POST` | `/api/clients/{client_id}/companies/{company_id}/tax-profile-overrides` | `create_client_company_tax_profile_override_api_clients__client_id__companies__company_id__tax_profile_overrides_post` | Create Client Company Tax Profile Override |
| `PATCH` | `/api/clients/{client_id}/companies/{company_id}/tax-profile-overrides/{override_id}/disable` | `disable_client_company_tax_profile_override_api_clients__client_id__companies__company_id__tax_profile_overrides__override_id__disable_patch` | Disable Client Company Tax Profile Override |
| `PATCH` | `/api/clients/{client_id}/companies/{company_id}/tax-profile-overrides/{override_id}/rate-basis` | `confirm_client_company_tax_rate_basis_api_clients__client_id__companies__company_id__tax_profile_overrides__override_id__rate_basis_patch` | Confirm Client Company Tax Rate Basis |
| `GET` | `/api/clients/{client_id}/integrations` | `list_client_integrations_api_clients__client_id__integrations_get` | List Client Integrations |
| `POST` | `/api/clients/{client_id}/mapping-file` | `upload_client_mapping_file_api_clients__client_id__mapping_file_post` | Upload Client Mapping File |
| `GET` | `/api/clients/{client_id}/mapping/export/sku-mapping` | `client_mapping_export_sku_mapping_api_clients__client_id__mapping_export_sku_mapping_get` | Client Mapping Export Sku Mapping |
| `GET` | `/api/clients/{client_id}/mapping/items` | `client_mapping_items_api_clients__client_id__mapping_items_get` | Client Mapping Items |
| `POST` | `/api/clients/{client_id}/mapping/items/{item_id}/accept` | `client_mapping_accept_api_clients__client_id__mapping_items__item_id__accept_post` | Client Mapping Accept |
| `GET` | `/api/clients/{client_id}/mapping/items/{item_id}/candidates` | `client_mapping_candidates_api_clients__client_id__mapping_items__item_id__candidates_get` | Client Mapping Candidates |
| `POST` | `/api/clients/{client_id}/mapping/items/{item_id}/exclude` | `client_mapping_exclude_api_clients__client_id__mapping_items__item_id__exclude_post` | Client Mapping Exclude |
| `GET` | `/api/clients/{client_id}/mapping/items/{item_id}/history` | `client_mapping_history_api_clients__client_id__mapping_items__item_id__history_get` | Client Mapping History |
| `POST` | `/api/clients/{client_id}/mapping/items/{item_id}/reject` | `client_mapping_reject_api_clients__client_id__mapping_items__item_id__reject_post` | Client Mapping Reject |
| `POST` | `/api/clients/{client_id}/mapping/items/{item_id}/revoke` | `client_mapping_revoke_api_clients__client_id__mapping_items__item_id__revoke_post` | Client Mapping Revoke |
| `GET` | `/api/clients/{client_id}/mapping/onec-search` | `client_mapping_onec_search_api_clients__client_id__mapping_onec_search_get` | Client Mapping Onec Search |
| `POST` | `/api/clients/{client_id}/mapping/rebuild-candidates` | `client_mapping_rebuild_candidates_api_clients__client_id__mapping_rebuild_candidates_post` | Client Mapping Rebuild Candidates |
| `GET` | `/api/clients/{client_id}/onec-organizations` | `list_client_onec_organizations_api_clients__client_id__onec_organizations_get` | List Client Onec Organizations |
| `GET` | `/api/clients/{client_id}/ozon-diagnostics` | `client_ozon_diagnostics_api_clients__client_id__ozon_diagnostics_get` | Client Ozon Diagnostics |
| `GET` | `/api/clients/{client_id}/ozon-diagnostics/export.xlsx` | `client_ozon_diagnostics_export_api_clients__client_id__ozon_diagnostics_export_xlsx_get` | Client Ozon Diagnostics Export |
| `GET` | `/api/clients/{client_id}/report-kinds` | `list_client_report_kinds_api_clients__client_id__report_kinds_get` | List Client Report Kinds |
| `GET` | `/api/clients/{client_id}/reports` | `list_client_reports_api_clients__client_id__reports_get` | List Client Reports |
| `POST` | `/api/clients/{client_id}/reports/generate` | `generate_client_report_api_clients__client_id__reports_generate_post` | Generate Client Report |
| `POST` | `/api/clients/{client_id}/source-refresh` | `run_client_source_refresh_api_clients__client_id__source_refresh_post` | Run Client Source Refresh |
| `GET` | `/api/clients/{client_id}/source-refresh/latest` | `client_source_refresh_latest_api_clients__client_id__source_refresh_latest_get` | Client Source Refresh Latest |
| `GET` | `/api/health` | `health_api_health_get` | Health |
| `GET` | `/api/integrations` | `list_integrations_api_integrations_get` | List Integrations |
| `POST` | `/api/integrations` | `create_integration_api_integrations_post` | Create Integration |
| `PUT` | `/api/integrations/{provider}` | `save_integration_api_integrations__provider__put` | Save Integration |
| `POST` | `/api/integrations/{provider}/check` | `check_integration_api_integrations__provider__check_post` | Check Integration |
| `POST` | `/api/integrations/{provider}/disable` | `disable_integration_api_integrations__provider__disable_post` | Disable Integration |
| `GET` | `/api/me` | `me_api_me_get` | Me |
| `GET` | `/api/report-generations/{generation_run_id}` | `report_generation_status_api_report_generations__generation_run_id__get` | Report Generation Status |
| `GET` | `/api/reports` | `list_reports_api_reports_get` | List Reports |
| `GET` | `/api/reports/latest/summary` | `latest_summary_api_reports_latest_summary_get` | Latest Summary |
| `POST` | `/api/reports/{report_id}/analytical-report` | `build_analytical_report_api_reports__report_id__analytical_report_post` | Build Analytical Report |
| `GET` | `/api/reports/{report_id}/analytical-report.{extension}` | `download_analytical_report_api_reports__report_id__analytical_report__extension__get` | Download Analytical Report |
| `GET` | `/api/reports/{report_id}/buyout-reconciliation` | `report_buyout_reconciliation_api_reports__report_id__buyout_reconciliation_get` | Report Buyout Reconciliation |
| `GET` | `/api/reports/{report_id}/client-draft` | `report_client_draft_api_reports__report_id__client_draft_get` | Report Client Draft |
| `PUT` | `/api/reports/{report_id}/client-draft` | `save_client_draft_api_reports__report_id__client_draft_put` | Save Client Draft |
| `POST` | `/api/reports/{report_id}/client-draft/finalize` | `finalize_client_draft_api_reports__report_id__client_draft_finalize_post` | Finalize Client Draft |
| `POST` | `/api/reports/{report_id}/client-draft/refine` | `refine_client_draft_api_reports__report_id__client_draft_refine_post` | Refine Client Draft |
| `GET` | `/api/reports/{report_id}/cogs-reconciliation` | `report_cogs_reconciliation_api_reports__report_id__cogs_reconciliation_get` | Report Cogs Reconciliation |
| `GET` | `/api/reports/{report_id}/document-reconciliation` | `report_document_reconciliation_api_reports__report_id__document_reconciliation_get` | Report Document Reconciliation |
| `GET` | `/api/reports/{report_id}/export.xlsx` | `export_excel_api_reports__report_id__export_xlsx_get` | Export Excel |
| `GET` | `/api/reports/{report_id}/financial-document-reconciliation` | `report_financial_document_reconciliation_api_reports__report_id__financial_document_reconciliation_get` | Report Financial Document Reconciliation |
| `GET` | `/api/reports/{report_id}/freshness` | `report_freshness_api_reports__report_id__freshness_get` | Report Freshness |
| `POST` | `/api/reports/{report_id}/live-checks/onec-cost` | `live_check_onec_cost_api_reports__report_id__live_checks_onec_cost_post` | Live Check Onec Cost |
| `POST` | `/api/reports/{report_id}/live-checks/wb-card` | `live_check_wb_card_api_reports__report_id__live_checks_wb_card_post` | Live Check Wb Card |
| `POST` | `/api/reports/{report_id}/live-checks/wb-stock` | `live_check_wb_stock_api_reports__report_id__live_checks_wb_stock_post` | Live Check Wb Stock |
| `GET` | `/api/reports/{report_id}/logistics/dimensions` | `report_logistics_dimensions_api_reports__report_id__logistics_dimensions_get` | Report Logistics Dimensions |
| `GET` | `/api/reports/{report_id}/logistics/orders` | `report_logistics_orders_api_reports__report_id__logistics_orders_get` | Report Logistics Orders |
| `GET` | `/api/reports/{report_id}/logistics/products` | `report_logistics_products_api_reports__report_id__logistics_products_get` | Report Logistics Products |
| `GET` | `/api/reports/{report_id}/logistics/summary` | `report_logistics_summary_api_reports__report_id__logistics_summary_get` | Report Logistics Summary |
| `GET` | `/api/reports/{report_id}/logistics/tariffs` | `report_logistics_tariffs_api_reports__report_id__logistics_tariffs_get` | Report Logistics Tariffs |
| `GET` | `/api/reports/{report_id}/management-report` | `report_management_report_api_reports__report_id__management_report_get` | Report Management Report |
| `POST` | `/api/reports/{report_id}/mapping-file` | `upload_mapping_file_api_reports__report_id__mapping_file_post` | Upload Mapping File |
| `GET` | `/api/reports/{report_id}/marketplace-expense-reconciliation` | `report_marketplace_expense_reconciliation_api_reports__report_id__marketplace_expense_reconciliation_get` | Report Marketplace Expense Reconciliation |
| `GET` | `/api/reports/{report_id}/ozon-diagnostics` | `report_ozon_diagnostics_api_reports__report_id__ozon_diagnostics_get` | Report Ozon Diagnostics |
| `POST` | `/api/reports/{report_id}/publish-with-tasks` | `publish_report_with_tasks_api_reports__report_id__publish_with_tasks_post` | Publish Report With Tasks |
| `GET` | `/api/reports/{report_id}/refresh-jobs/{job_id}` | `get_refresh_job_api_reports__report_id__refresh_jobs__job_id__get` | Get Refresh Job |
| `POST` | `/api/reports/{report_id}/refresh/onec-auto` | `refresh_onec_auto_api_reports__report_id__refresh_onec_auto_post` | Refresh Onec Auto |
| `GET` | `/api/reports/{report_id}/rows` | `report_rows_api_reports__report_id__rows_get` | Report Rows |
| `GET` | `/api/reports/{report_id}/scenario` | `report_scenario_api_reports__report_id__scenario_get` | Report Scenario |
| `GET` | `/api/reports/{report_id}/sku/{sku}` | `sku_card_api_reports__report_id__sku__sku__get` | Sku Card |
| `GET` | `/api/reports/{report_id}/summary` | `report_summary_api_reports__report_id__summary_get` | Report Summary |
| `GET` | `/cabinet` | `cabinet_cabinet_get` | Cabinet |
| `GET` | `/integrations` | `integrations_page_integrations_get` | Integrations Page |

Всего маршрутов: **108**.
