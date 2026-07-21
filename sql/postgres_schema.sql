CREATE SCHEMA IF NOT EXISTS wb_unit_economics;

CREATE TABLE IF NOT EXISTS wb_unit_economics.wb_finance_snapshot_pages (
    snapshot_id text NOT NULL,
    client_id text NOT NULL,
    seller_account_id text NOT NULL,
    account_name text NOT NULL,
    page_index integer NOT NULL,
    ok boolean NOT NULL,
    status text NOT NULL,
    row_count integer NOT NULL,
    status_code integer,
    rrd_id_start bigint,
    rrd_id_next bigint,
    raw_payload_hash text NOT NULL DEFAULT '',
    output_file text,
    error text NOT NULL DEFAULT '',
    manifest_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    generated_at timestamptz NOT NULL,
    period_start date NOT NULL,
    period_end date NOT NULL,
    report_period text NOT NULL,
    endpoint text NOT NULL,
    source text NOT NULL,
    request_delay_seconds numeric,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_id, seller_account_id, page_index)
);

CREATE TABLE IF NOT EXISTS wb_unit_economics.wb_finance_detail_raw (
    id bigserial PRIMARY KEY,
    snapshot_id text NOT NULL,
    client_id text NOT NULL,
    seller_account_id text NOT NULL,
    account_name text NOT NULL,
    organization_id text NOT NULL,
    source_endpoint text NOT NULL,
    source_file text NOT NULL,
    page_index integer NOT NULL,
    row_number integer NOT NULL,
    loaded_at timestamptz NOT NULL,
    manifest_period_start date NOT NULL,
    manifest_period_end date NOT NULL,
    report_period text NOT NULL,
    row_date date NOT NULL,
    week_start date NOT NULL,
    week_end date NOT NULL,
    is_partial_source boolean NOT NULL,
    raw_payload_hash text NOT NULL,
    row_payload jsonb NOT NULL,
    wb_document_id text NOT NULL,
    report_id text,
    rrd_id bigint,
    rr_date date,
    sale_dt timestamptz,
    order_dt timestamptz,
    create_date date,
    date_from date,
    date_to date,
    order_uid text,
    order_id text,
    shk_id text,
    sticker_id text,
    trbx_id text,
    nm_id bigint,
    vendor_code text NOT NULL DEFAULT '',
    title text NOT NULL DEFAULT '',
    sku text NOT NULL DEFAULT '',
    doc_type_name text NOT NULL DEFAULT '',
    seller_oper_name text NOT NULL DEFAULT '',
    delivery_method text NOT NULL DEFAULT '',
    office_name text,
    ppvz_office_name text,
    ppvz_office_id text,
    country text,
    gi_box_type_name text,
    dlv_prc numeric,
    fix_tariff_date_from date,
    fix_tariff_date_to date,
    sales_model text NOT NULL,
    operation_type text NOT NULL DEFAULT '',
    quantity numeric NOT NULL DEFAULT 0,
    signed_quantity numeric NOT NULL DEFAULT 0,
    retail_amount numeric NOT NULL DEFAULT 0,
    net_revenue numeric NOT NULL DEFAULT 0,
    ppvz_sales_commission numeric NOT NULL DEFAULT 0,
    wb_commission numeric NOT NULL DEFAULT 0,
    delivery_service numeric NOT NULL DEFAULT 0,
    delivery_amount numeric,
    return_amount numeric,
    rebill_logistic_cost numeric,
    logistics numeric NOT NULL DEFAULT 0,
    paid_storage numeric NOT NULL DEFAULT 0,
    storage numeric NOT NULL DEFAULT 0,
    paid_acceptance numeric NOT NULL DEFAULT 0,
    acceptance numeric NOT NULL DEFAULT 0,
    penalty numeric NOT NULL DEFAULT 0,
    additional_payment numeric NOT NULL DEFAULT 0,
    deduction numeric NOT NULL DEFAULT 0,
    penalties_and_holdbacks numeric NOT NULL DEFAULT 0,
    acquiring_fee numeric NOT NULL DEFAULT 0,
    acquiring numeric NOT NULL DEFAULT 0,
    currency text NOT NULL DEFAULT 'RUB',
    srid text NOT NULL DEFAULT '',
    inserted_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE wb_unit_economics.wb_finance_detail_raw
    ADD COLUMN IF NOT EXISTS order_uid text,
    ADD COLUMN IF NOT EXISTS order_id text,
    ADD COLUMN IF NOT EXISTS shk_id text,
    ADD COLUMN IF NOT EXISTS sticker_id text,
    ADD COLUMN IF NOT EXISTS trbx_id text,
    ADD COLUMN IF NOT EXISTS office_name text,
    ADD COLUMN IF NOT EXISTS ppvz_office_name text,
    ADD COLUMN IF NOT EXISTS ppvz_office_id text,
    ADD COLUMN IF NOT EXISTS country text,
    ADD COLUMN IF NOT EXISTS gi_box_type_name text,
    ADD COLUMN IF NOT EXISTS dlv_prc numeric,
    ADD COLUMN IF NOT EXISTS fix_tariff_date_from date,
    ADD COLUMN IF NOT EXISTS fix_tariff_date_to date,
    ADD COLUMN IF NOT EXISTS delivery_amount numeric,
    ADD COLUMN IF NOT EXISTS return_amount numeric,
    ADD COLUMN IF NOT EXISTS rebill_logistic_cost numeric;

CREATE UNIQUE INDEX IF NOT EXISTS ux_wb_finance_detail_raw_snapshot_row
    ON wb_unit_economics.wb_finance_detail_raw (
        snapshot_id, seller_account_id, source_file, row_number, raw_payload_hash
    );

CREATE INDEX IF NOT EXISTS ix_wb_finance_detail_raw_week
    ON wb_unit_economics.wb_finance_detail_raw (
        client_id, seller_account_id, organization_id, week_start
    );

CREATE INDEX IF NOT EXISTS ix_wb_finance_detail_raw_product
    ON wb_unit_economics.wb_finance_detail_raw (
        client_id, seller_account_id, nm_id, vendor_code, sku
    );

CREATE INDEX IF NOT EXISTS ix_wb_finance_detail_raw_payload_gin
    ON wb_unit_economics.wb_finance_detail_raw USING gin (row_payload);

CREATE TABLE IF NOT EXISTS wb_unit_economics.sku_mapping_snapshot (
    snapshot_id text NOT NULL,
    mapping_key text NOT NULL,
    client_id text NOT NULL,
    seller_account_id text NOT NULL,
    organization_id text NOT NULL,
    nm_id bigint,
    vendor_code text NOT NULL DEFAULT '',
    barcode text NOT NULL DEFAULT '',
    onec_item_id text NOT NULL DEFAULT '',
    onec_article text NOT NULL DEFAULT '',
    onec_characteristic text NOT NULL DEFAULT '',
    match_method text NOT NULL,
    confidence numeric NOT NULL DEFAULT 0,
    status text NOT NULL,
    comment text NOT NULL DEFAULT '',
    updated_by text NOT NULL,
    updated_at timestamptz NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_id, mapping_key)
);

CREATE INDEX IF NOT EXISTS ix_sku_mapping_snapshot_product
    ON wb_unit_economics.sku_mapping_snapshot (
        client_id, seller_account_id, nm_id, vendor_code, barcode
    );

CREATE INDEX IF NOT EXISTS ix_sku_mapping_snapshot_onec_item
    ON wb_unit_economics.sku_mapping_snapshot (
        client_id, organization_id, onec_item_id, onec_article
    );

CREATE TABLE IF NOT EXISTS wb_unit_economics.onec_cost_snapshot (
    snapshot_id text NOT NULL,
    cost_key text NOT NULL,
    client_id text NOT NULL,
    organization_id text NOT NULL,
    loaded_at timestamptz NOT NULL,
    onec_item_id text NOT NULL,
    article text NOT NULL DEFAULT '',
    barcode text NOT NULL DEFAULT '',
    name text NOT NULL DEFAULT '',
    characteristic text NOT NULL DEFAULT '',
    cost_value numeric NOT NULL,
    extra_costs_value numeric NOT NULL DEFAULT 0,
    cost_currency text NOT NULL DEFAULT 'RUB',
    cost_method text NOT NULL,
    effective_from date NOT NULL,
    effective_to date,
    source_document text NOT NULL,
    raw_payload_hash text NOT NULL,
    inserted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_id, cost_key)
);

CREATE INDEX IF NOT EXISTS ix_onec_cost_snapshot_item
    ON wb_unit_economics.onec_cost_snapshot (
        client_id, organization_id, onec_item_id, characteristic
    );

CREATE INDEX IF NOT EXISTS ix_onec_cost_snapshot_article
    ON wb_unit_economics.onec_cost_snapshot (
        client_id, organization_id, article, barcode
    );

CREATE OR REPLACE VIEW wb_unit_economics.v_wb_finance_weekly_totals AS
SELECT
    client_id,
    seller_account_id,
    account_name,
    organization_id,
    week_start,
    week_end,
    nm_id,
    vendor_code,
    sku,
    title,
    sales_model,
    currency,
    sum(signed_quantity) AS quantity,
    sum(net_revenue) AS net_revenue,
    sum(wb_commission) AS wb_commission,
    sum(logistics) AS logistics,
    sum(storage) AS storage,
    sum(acceptance) AS acceptance,
    sum(penalties_and_holdbacks) AS penalties_and_holdbacks,
    sum(acquiring) AS acquiring,
    bool_or(is_partial_source) AS is_partial_source,
    count(*) AS source_row_count,
    min(row_date) AS first_row_date,
    max(row_date) AS last_row_date
FROM wb_unit_economics.wb_finance_detail_raw
GROUP BY
    client_id,
    seller_account_id,
    account_name,
    organization_id,
    week_start,
    week_end,
    nm_id,
    vendor_code,
    sku,
    title,
    sales_model,
    currency;

CREATE TABLE IF NOT EXISTS wb_unit_economics.accounting_workflow_cards (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id),
    client_id text NOT NULL REFERENCES wb_unit_economics.clients(id),
    organization_id text NOT NULL,
    report_period date NOT NULL,
    stage text NOT NULL DEFAULT 'new',
    previous_stage text NOT NULL DEFAULT '',
    creation_kind text NOT NULL DEFAULT 'scheduled',
    responsible_user_id text REFERENCES wb_unit_economics.users(id),
    supervisor_user_id text REFERENCES wb_unit_economics.users(id),
    target_due_at timestamptz NOT NULL,
    hard_due_at timestamptz NOT NULL,
    blocking_reason text NOT NULL DEFAULT '',
    cancellation_reason text NOT NULL DEFAULT '',
    cancellation_detail text NOT NULL DEFAULT '',
    supersedes_card_id text REFERENCES wb_unit_economics.accounting_workflow_cards(id),
    created_by_user_id text REFERENCES wb_unit_economics.users(id),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    closed_at timestamptz,
    cancelled_at timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_accounting_workflow_base_card
    ON wb_unit_economics.accounting_workflow_cards (
        tenant_id, client_id, organization_id, report_period
    )
    WHERE supersedes_card_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_accounting_workflow_active_card
    ON wb_unit_economics.accounting_workflow_cards (
        tenant_id, client_id, organization_id, report_period
    )
    WHERE stage NOT IN ('closed_payroll', 'cancelled');

CREATE INDEX IF NOT EXISTS ix_accounting_workflow_cards_board
    ON wb_unit_economics.accounting_workflow_cards (
        tenant_id, report_period, stage
    );

CREATE TABLE IF NOT EXISTS wb_unit_economics.accounting_workflow_tasks (
    id text PRIMARY KEY,
    card_id text NOT NULL REFERENCES wb_unit_economics.accounting_workflow_cards(id) ON DELETE CASCADE,
    report_kind text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    current_report_id text REFERENCES wb_unit_economics.report_runs(id),
    current_payload_sha256 text NOT NULL DEFAULT '',
    is_final boolean NOT NULL DEFAULT false,
    reviewed_by_user_id text REFERENCES wb_unit_economics.users(id),
    reviewed_at timestamptz,
    facts_confirmed_by_user_id text REFERENCES wb_unit_economics.users(id),
    facts_confirmed_at timestamptz,
    text_approved_by_user_id text REFERENCES wb_unit_economics.users(id),
    text_approved_at timestamptz,
    blocking_reason text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT uq_accounting_workflow_task_kind UNIQUE (card_id, report_kind)
);

CREATE INDEX IF NOT EXISTS ix_accounting_workflow_tasks_card
    ON wb_unit_economics.accounting_workflow_tasks (card_id, status);

CREATE TABLE IF NOT EXISTS wb_unit_economics.accounting_workflow_report_revisions (
    id text PRIMARY KEY,
    task_id text NOT NULL REFERENCES wb_unit_economics.accounting_workflow_tasks(id) ON DELETE CASCADE,
    report_id text NOT NULL REFERENCES wb_unit_economics.report_runs(id),
    payload_sha256 text NOT NULL,
    is_final boolean NOT NULL DEFAULT false,
    is_current_for_task boolean NOT NULL DEFAULT true,
    attached_by_user_id text NOT NULL REFERENCES wb_unit_economics.users(id),
    created_at timestamptz NOT NULL,
    CONSTRAINT uq_accounting_workflow_task_report UNIQUE (task_id, report_id)
);

CREATE TABLE IF NOT EXISTS wb_unit_economics.accounting_workflow_attachments (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id),
    card_id text NOT NULL REFERENCES wb_unit_economics.accounting_workflow_cards(id) ON DELETE CASCADE,
    storage_key text NOT NULL UNIQUE,
    original_name text NOT NULL,
    content_type text NOT NULL,
    byte_size integer NOT NULL,
    sha256 text NOT NULL,
    uploaded_by_user_id text NOT NULL REFERENCES wb_unit_economics.users(id),
    created_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_accounting_workflow_revisions_task
    ON wb_unit_economics.accounting_workflow_report_revisions (
        task_id, is_current_for_task
    );

CREATE INDEX IF NOT EXISTS ix_accounting_workflow_attachments_card
    ON wb_unit_economics.accounting_workflow_attachments (card_id, created_at);

CREATE TABLE IF NOT EXISTS wb_unit_economics.accounting_workflow_deliveries (
    id text PRIMARY KEY,
    card_id text NOT NULL REFERENCES wb_unit_economics.accounting_workflow_cards(id) ON DELETE CASCADE,
    task_id text NOT NULL REFERENCES wb_unit_economics.accounting_workflow_tasks(id) ON DELETE CASCADE,
    report_id text NOT NULL REFERENCES wb_unit_economics.report_runs(id),
    payload_sha256 text NOT NULL,
    sent_at timestamptz NOT NULL,
    delivery_channel text NOT NULL,
    channel_detail text NOT NULL DEFAULT '',
    masked_recipient text NOT NULL,
    attachment_id text NOT NULL REFERENCES wb_unit_economics.accounting_workflow_attachments(id),
    contact_result text NOT NULL DEFAULT '',
    is_preliminary boolean NOT NULL DEFAULT false,
    created_by_user_id text NOT NULL REFERENCES wb_unit_economics.users(id),
    invalidated_at timestamptz,
    invalidation_reason text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS wb_unit_economics.accounting_workflow_followups (
    id text PRIMARY KEY,
    card_id text NOT NULL REFERENCES wb_unit_economics.accounting_workflow_cards(id) ON DELETE CASCADE,
    delivery_id text NOT NULL REFERENCES wb_unit_economics.accounting_workflow_deliveries(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'scheduled',
    due_at timestamptz NOT NULL,
    repeated_at timestamptz,
    escalation_due_at timestamptz,
    supervisor_notified_at timestamptz,
    completed_at timestamptz,
    result text NOT NULL DEFAULT '',
    updated_by_user_id text REFERENCES wb_unit_economics.users(id),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_accounting_workflow_deliveries_card
    ON wb_unit_economics.accounting_workflow_deliveries (card_id, sent_at);

CREATE TABLE IF NOT EXISTS wb_unit_economics.accounting_workflow_supervisors (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id),
    user_id text NOT NULL REFERENCES wb_unit_economics.users(id),
    is_active boolean NOT NULL DEFAULT true,
    granted_by_user_id text NOT NULL REFERENCES wb_unit_economics.users(id),
    granted_at timestamptz NOT NULL,
    revoked_by_user_id text REFERENCES wb_unit_economics.users(id),
    revoked_at timestamptz,
    CONSTRAINT uq_accounting_workflow_supervisor UNIQUE (tenant_id, user_id)
);

CREATE TABLE IF NOT EXISTS wb_unit_economics.accounting_workflow_comments (
    id text PRIMARY KEY,
    card_id text NOT NULL REFERENCES wb_unit_economics.accounting_workflow_cards(id) ON DELETE CASCADE,
    user_id text NOT NULL REFERENCES wb_unit_economics.users(id),
    body text NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS wb_unit_economics.accounting_workflow_audit_events (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id),
    card_id text REFERENCES wb_unit_economics.accounting_workflow_cards(id),
    user_id text REFERENCES wb_unit_economics.users(id),
    action text NOT NULL,
    entity_type text NOT NULL DEFAULT '',
    entity_id text NOT NULL DEFAULT '',
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_accounting_workflow_comments_card
    ON wb_unit_economics.accounting_workflow_comments (card_id, created_at);

CREATE INDEX IF NOT EXISTS ix_accounting_workflow_followups_due
    ON wb_unit_economics.accounting_workflow_followups (status, due_at);

CREATE INDEX IF NOT EXISTS ix_accounting_workflow_audit_card
    ON wb_unit_economics.accounting_workflow_audit_events (card_id, created_at);

CREATE INDEX IF NOT EXISTS ix_accounting_workflow_audit_tenant
    ON wb_unit_economics.accounting_workflow_audit_events (tenant_id, created_at);
-- Logistics hardening v3 is additive. Existing wb-logistics-v1/v2 rows are
-- kept untouched and are exposed as needs_rebuild by the application.
ALTER TABLE IF EXISTS wb_unit_economics.report_runs
    ADD COLUMN IF NOT EXISTS logistics_analysis_required boolean NOT NULL DEFAULT false;

ALTER TABLE IF EXISTS wb_unit_economics.report_runs
    ADD COLUMN IF NOT EXISTS logistics_dimensions_required boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS wb_unit_economics.report_logistics_dimension_rows (
    id bigserial PRIMARY KEY,
    report_run_id text NOT NULL REFERENCES wb_unit_economics.report_runs(id) ON DELETE CASCADE,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id),
    client_id text NOT NULL REFERENCES wb_unit_economics.clients(id),
    row_uid text NOT NULL,
    wb_cabinet_id text NOT NULL DEFAULT '',
    client_company_id text NOT NULL DEFAULT '',
    scheme text NOT NULL DEFAULT '',
    product_ref text NOT NULL DEFAULT '',
    product_key text NOT NULL DEFAULT '',
    nm_id text NOT NULL DEFAULT '',
    sku text NOT NULL DEFAULT '',
    vendor_code text NOT NULL DEFAULT '',
    product text NOT NULL DEFAULT '',
    length_cm numeric,
    width_cm numeric,
    height_cm numeric,
    weight_brutto_kg numeric,
    volume_l numeric,
    dimensions_valid boolean,
    measured_penalty_amount numeric,
    evidence_type text NOT NULL DEFAULT '',
    coverage_status text NOT NULL DEFAULT '',
    data_quality_status text NOT NULL DEFAULT '',
    source_hash_digest text NOT NULL DEFAULT '',
    CONSTRAINT uq_report_logistics_dimension_row UNIQUE (report_run_id, row_uid)
);

CREATE INDEX IF NOT EXISTS ix_report_logistics_dimension_filter
    ON wb_unit_economics.report_logistics_dimension_rows (
        report_run_id, wb_cabinet_id, client_company_id, scheme
    );

CREATE INDEX IF NOT EXISTS ix_report_logistics_dimension_product
    ON wb_unit_economics.report_logistics_dimension_rows (
        report_run_id, product_ref, nm_id
    );

CREATE TABLE IF NOT EXISTS wb_unit_economics.report_logistics_dimension_contexts (
    report_run_id text PRIMARY KEY REFERENCES wb_unit_economics.report_runs(id) ON DELETE CASCADE,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id),
    client_id text NOT NULL REFERENCES wb_unit_economics.clients(id),
    factor_methodology_version text NOT NULL,
    data_status text NOT NULL,
    input_hash text NOT NULL,
    source_snapshot_hash text NOT NULL DEFAULT '',
    source_loaded_at timestamptz,
    source_row_count integer NOT NULL DEFAULT 0,
    dimension_row_count integer NOT NULL DEFAULT 0,
    matched_product_count integer NOT NULL DEFAULT 0,
    missing_product_count integer NOT NULL DEFAULT 0,
    invalid_product_count integer NOT NULL DEFAULT 0,
    conflicting_product_count integer NOT NULL DEFAULT 0,
    signal_product_count integer NOT NULL DEFAULT 0,
    blocking_reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    review_reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_report_logistics_dimension_context_status
    ON wb_unit_economics.report_logistics_dimension_contexts (tenant_id, data_status);

ALTER TABLE IF EXISTS wb_unit_economics.report_logistics_analysis_contexts
    ADD COLUMN IF NOT EXISTS source_quality_status text NOT NULL DEFAULT 'ready',
    ADD COLUMN IF NOT EXISTS invalid_source_row_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS required_field_error_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS invalid_report_row_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS report_required_field_error_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS chain_dimension_conflict_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS raw_order_uid_cross_cabinet_reuse_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS unmatched_source_dimension_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS unmatched_report_dimension_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS dimension_delta_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS max_dimension_delta numeric NOT NULL DEFAULT 0;

ALTER TABLE IF EXISTS wb_unit_economics.report_logistics_order_rows
    ADD COLUMN IF NOT EXISTS financial_date date,
    ADD COLUMN IF NOT EXISTS order_period_status text NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS product_ref text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS warehouse_status text NOT NULL DEFAULT 'missing',
    ADD COLUMN IF NOT EXISTS destination_status text NOT NULL DEFAULT 'missing';

ALTER TABLE IF EXISTS wb_unit_economics.report_logistics_sku_rows
    ADD COLUMN IF NOT EXISTS financial_week_end date,
    ADD COLUMN IF NOT EXISTS product_ref text NOT NULL DEFAULT '';

DO $$
BEGIN
    IF to_regclass('wb_unit_economics.report_logistics_order_rows') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS ix_report_logistics_orders_product_ref
            ON wb_unit_economics.report_logistics_order_rows
            (report_run_id, product_ref, financial_date);
    END IF;
    IF to_regclass('wb_unit_economics.report_logistics_sku_rows') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS ix_report_logistics_sku_product_ref
            ON wb_unit_economics.report_logistics_sku_rows
            (report_run_id, product_ref, financial_week_start);
    END IF;
END
$$;

-- Logistics hardening v4 is additive. Existing wb-logistics-v1/v2/v3 rows
-- remain immutable and the application exposes them as needs_rebuild.
ALTER TABLE IF EXISTS wb_unit_economics.report_logistics_analysis_contexts
    ADD COLUMN IF NOT EXISTS invalid_source_payload_shape_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS source_identity_error_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS source_revision_conflict_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS source_revision_discarded_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS scope_mismatch_count integer NOT NULL DEFAULT 0;

ALTER TABLE IF EXISTS wb_unit_economics.report_logistics_sku_rows
    ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS client_id text NOT NULL DEFAULT '';

-- Logistics v5 keeps old immutable contexts untouched and uses a nullable
-- financial value for new rows so a missing ReportUnitRow link cannot become 0.
ALTER TABLE IF EXISTS wb_unit_economics.report_logistics_sku_rows
    ADD COLUMN IF NOT EXISTS financial_revenue numeric;

DO $$
BEGIN
    IF to_regclass('wb_unit_economics.report_logistics_order_rows') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS ix_report_logistics_orders_calendar_filter
            ON wb_unit_economics.report_logistics_order_rows
            (report_run_id, financial_date, wb_cabinet_id,
             client_company_id, scheme, product_ref);
    END IF;
END
$$;
