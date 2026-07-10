CREATE SCHEMA IF NOT EXISTS wb_unit_economics;

CREATE TABLE IF NOT EXISTS wb_unit_economics.tenants (
    id text PRIMARY KEY,
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wb_unit_economics.consulting_firms (
    id text PRIMARY KEY,
    name text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wb_unit_economics.clients (
    id text PRIMARY KEY,
    firm_id text NOT NULL REFERENCES wb_unit_economics.consulting_firms(id) ON DELETE RESTRICT,
    tenant_id text NOT NULL UNIQUE REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    name text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    default_report_settings jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_clients_firm_status
    ON wb_unit_economics.clients (firm_id, status);

CREATE TABLE IF NOT EXISTS wb_unit_economics.client_companies (
    id text PRIMARY KEY,
    client_id text NOT NULL REFERENCES wb_unit_economics.clients(id) ON DELETE CASCADE,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    display_name text NOT NULL,
    source_key text NOT NULL,
    onec_organization_id text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (client_id, source_key)
);

CREATE INDEX IF NOT EXISTS ix_client_companies_client
    ON wb_unit_economics.client_companies (client_id, status);

CREATE TABLE IF NOT EXISTS wb_unit_economics.wb_cabinets (
    id text PRIMARY KEY,
    client_id text NOT NULL REFERENCES wb_unit_economics.clients(id) ON DELETE CASCADE,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    client_company_id text REFERENCES wb_unit_economics.client_companies(id) ON DELETE SET NULL,
    display_name text NOT NULL,
    cabinet_key text NOT NULL,
    provider text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (client_id, cabinet_key)
);

CREATE INDEX IF NOT EXISTS ix_wb_cabinets_client
    ON wb_unit_economics.wb_cabinets (client_id, status);

CREATE INDEX IF NOT EXISTS ix_wb_cabinets_provider
    ON wb_unit_economics.wb_cabinets (tenant_id, provider);

CREATE TABLE IF NOT EXISTS wb_unit_economics.users (
    id text PRIMARY KEY,
    email text NOT NULL UNIQUE,
    name text NOT NULL DEFAULT '',
    password_hash text NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wb_unit_economics.user_tenant_access (
    id bigserial PRIMARY KEY,
    user_id text NOT NULL REFERENCES wb_unit_economics.users(id) ON DELETE CASCADE,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('client', 'consultant', 'admin')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, tenant_id)
);

CREATE TABLE IF NOT EXISTS wb_unit_economics.tenant_integrations (
    id bigserial PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    provider text NOT NULL,
    label text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'not_configured',
    secret_hash text NOT NULL DEFAULT '',
    secret_hint text NOT NULL DEFAULT '',
    config_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_checked_at timestamptz,
    disabled_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, provider)
);

CREATE INDEX IF NOT EXISTS ix_tenant_integrations_tenant
    ON wb_unit_economics.tenant_integrations (tenant_id, provider);

CREATE TABLE IF NOT EXISTS wb_unit_economics.sessions (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES wb_unit_economics.users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    last_seen_at timestamptz,
    user_agent text NOT NULL DEFAULT '',
    ip_address text NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS wb_unit_economics.report_runs (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    client_id text NOT NULL REFERENCES wb_unit_economics.clients(id) ON DELETE CASCADE,
    client_name text NOT NULL,
    title text NOT NULL,
    period_start date NOT NULL,
    period_end date NOT NULL,
    source_coverage_start date,
    source_coverage_end date,
    period_text text NOT NULL,
    period_status text NOT NULL,
    generated_at timestamptz NOT NULL,
    status text NOT NULL,
    publication_status text NOT NULL DEFAULT 'published',
    is_current boolean NOT NULL DEFAULT false,
    lineage_type text NOT NULL DEFAULT 'legacy_excel_import',
    source_snapshot_set_id text NOT NULL DEFAULT '',
    methodology_version text NOT NULL,
    source_workbook text NOT NULL DEFAULT '',
    source_workbook_path text NOT NULL DEFAULT '',
    return_reason_limitation text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_report_runs_tenant_period
    ON wb_unit_economics.report_runs (tenant_id, period_start, period_end, generated_at DESC);

CREATE INDEX IF NOT EXISTS ix_report_runs_client_period
    ON wb_unit_economics.report_runs (client_id, period_start, period_end, generated_at DESC);

CREATE TABLE IF NOT EXISTS wb_unit_economics.report_unit_rows (
    id bigserial PRIMARY KEY,
    report_run_id text NOT NULL REFERENCES wb_unit_economics.report_runs(id) ON DELETE CASCADE,
    client_id text NOT NULL DEFAULT '',
    client_company_id text NOT NULL DEFAULT '',
    wb_cabinet_id text NOT NULL DEFAULT '',
    row_uid text NOT NULL,
    week date,
    month text NOT NULL DEFAULT '',
    document_report text NOT NULL DEFAULT '',
    wb_report_id text NOT NULL DEFAULT '',
    wb_report_date text NOT NULL DEFAULT '',
    organization text NOT NULL DEFAULT '',
    cabinet text NOT NULL DEFAULT '',
    product text NOT NULL DEFAULT '',
    nm_id text NOT NULL DEFAULT '',
    article_wb text NOT NULL DEFAULT '',
    article_1c text NOT NULL DEFAULT '',
    barcode text NOT NULL DEFAULT '',
    scheme text NOT NULL DEFAULT '',
    sales numeric NOT NULL DEFAULT 0,
    returns numeric NOT NULL DEFAULT 0,
    net_qty numeric NOT NULL DEFAULT 0,
    return_rate numeric,
    revenue_before_spp numeric NOT NULL DEFAULT 0,
    spp numeric NOT NULL DEFAULT 0,
    revenue numeric NOT NULL DEFAULT 0,
    vat numeric NOT NULL DEFAULT 0,
    vat_output numeric NOT NULL DEFAULT 0,
    vat_input numeric NOT NULL DEFAULT 0,
    vat_input_from_wb numeric NOT NULL DEFAULT 0,
    vat_input_from_1c numeric NOT NULL DEFAULT 0,
    vat_input_difference numeric NOT NULL DEFAULT 0,
    vat_input_completeness varchar NOT NULL DEFAULT '',
    vat_payable numeric NOT NULL DEFAULT 0,
    revenue_without_vat numeric NOT NULL DEFAULT 0,
    cost numeric NOT NULL DEFAULT 0,
    commission numeric NOT NULL DEFAULT 0,
    logistics numeric NOT NULL DEFAULT 0,
    storage numeric NOT NULL DEFAULT 0,
    acceptance numeric NOT NULL DEFAULT 0,
    promotion numeric NOT NULL DEFAULT 0,
    penalties numeric NOT NULL DEFAULT 0,
    acquiring numeric NOT NULL DEFAULT 0,
    usn numeric NOT NULL DEFAULT 0,
    income_tax_kind text NOT NULL DEFAULT '',
    income_tax_base numeric NOT NULL DEFAULT 0,
    income_tax numeric NOT NULL DEFAULT 0,
    income_tax_included boolean NOT NULL DEFAULT false,
    profit_before_tax numeric NOT NULL DEFAULT 0,
    profit numeric NOT NULL DEFAULT 0,
    margin numeric,
    unit_profit numeric,
    tax_method text NOT NULL DEFAULT '',
    tax_profile_source text NOT NULL DEFAULT '',
    tax_completeness text NOT NULL DEFAULT '',
    pnl_vat_mode text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT '',
    status_reason text NOT NULL DEFAULT '',
    spp_status text NOT NULL DEFAULT '',
    loss_class text NOT NULL DEFAULT '',
    loss_driver text NOT NULL DEFAULT '',
    source_snapshot_hashes jsonb NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (report_run_id, row_uid)
);

CREATE INDEX IF NOT EXISTS ix_report_unit_rows_filter
    ON wb_unit_economics.report_unit_rows (
        report_run_id,
        month,
        document_report,
        cabinet,
        organization,
        scheme,
        status,
        loss_class
    );

CREATE INDEX IF NOT EXISTS ix_report_unit_rows_product
    ON wb_unit_economics.report_unit_rows (
        report_run_id, product, nm_id, article_wb, article_1c, barcode
    );

CREATE TABLE IF NOT EXISTS wb_unit_economics.report_lost_sales_rows (
    id bigserial PRIMARY KEY,
    report_run_id text NOT NULL REFERENCES wb_unit_economics.report_runs(id) ON DELETE CASCADE,
    client_id text NOT NULL DEFAULT '',
    wb_cabinet_id text NOT NULL DEFAULT '',
    row_uid text NOT NULL,
    cabinet text NOT NULL DEFAULT '',
    product text NOT NULL DEFAULT '',
    article_1c text NOT NULL DEFAULT '',
    barcode text NOT NULL DEFAULT '',
    zero_stock_days numeric NOT NULL DEFAULT 0,
    onec_stock_quantity numeric NOT NULL DEFAULT 0,
    onec_warehouses text NOT NULL DEFAULT '',
    sales numeric NOT NULL DEFAULT 0,
    lost_units numeric NOT NULL DEFAULT 0,
    lost_revenue numeric NOT NULL DEFAULT 0,
    lost_profit numeric NOT NULL DEFAULT 0,
    note text NOT NULL DEFAULT '',
    UNIQUE (report_run_id, row_uid)
);

CREATE TABLE IF NOT EXISTS wb_unit_economics.report_reconciliation_monthly (
    id bigserial PRIMARY KEY,
    report_run_id text NOT NULL REFERENCES wb_unit_economics.report_runs(id) ON DELETE CASCADE,
    month text NOT NULL,
    wb_quantity numeric NOT NULL DEFAULT 0,
    onec_quantity numeric,
    quantity_delta numeric,
    wb_cogs numeric NOT NULL DEFAULT 0,
    onec_cogs numeric,
    cogs_delta numeric,
    wb_mp_expenses numeric NOT NULL DEFAULT 0,
    onec_mp_expenses numeric,
    mp_expenses_delta numeric,
    status text NOT NULL DEFAULT '',
    wb_basis text NOT NULL DEFAULT '',
    onec_basis text NOT NULL DEFAULT '',
    source_run_id text NOT NULL DEFAULT '',
    comment text NOT NULL DEFAULT '',
    UNIQUE (report_run_id, month)
);

CREATE TABLE IF NOT EXISTS wb_unit_economics.report_document_reconciliation_rows (
    id bigserial PRIMARY KEY,
    report_run_id text NOT NULL REFERENCES wb_unit_economics.report_runs(id) ON DELETE CASCADE,
    client_id text NOT NULL DEFAULT '',
    client_company_id text NOT NULL DEFAULT '',
    wb_cabinet_id text NOT NULL DEFAULT '',
    row_uid text NOT NULL,
    status text NOT NULL DEFAULT '',
    payout_status text NOT NULL DEFAULT '',
    period_status text NOT NULL DEFAULT '',
    document_report text NOT NULL DEFAULT '',
    sales_period text NOT NULL DEFAULT '',
    sales_period_start date,
    sales_period_end date,
    expected_document_date date,
    document_type text NOT NULL DEFAULT '',
    cabinet text NOT NULL DEFAULT '',
    organization text NOT NULL DEFAULT '',
    summary_report_id text NOT NULL DEFAULT '',
    weekly_sales_report_id text NOT NULL DEFAULT '',
    weekly_buyout_report_id text NOT NULL DEFAULT '',
    wb_report_ids text NOT NULL DEFAULT '',
    onec_documents text NOT NULL DEFAULT '',
    onec_document_types text NOT NULL DEFAULT '',
    onec_document_dates text NOT NULL DEFAULT '',
    wb_sales_quantity numeric,
    wb_return_quantity numeric,
    wb_net_quantity numeric,
    onec_sales_quantity numeric,
    onec_return_quantity numeric,
    onec_net_quantity numeric,
    sales_quantity_delta numeric,
    return_quantity_delta numeric,
    net_quantity_delta numeric,
    wb_quantity numeric,
    onec_quantity numeric,
    quantity_delta numeric,
    wb_amount numeric,
    onec_amount numeric,
    amount_delta numeric,
    buyout_retail_amount_sum numeric,
    buyout_for_pay_sum numeric,
    buyout_bank_payment_sum numeric,
    onec_expense_invoice_amount numeric,
    buyout_retail_delta numeric,
    buyout_for_pay_delta numeric,
    buyout_bank_delta numeric,
    pdf_bank_payment numeric,
    wb_for_pay_sum numeric,
    onec_settlement_total numeric,
    settlement_delta numeric,
    onec_source_rows integer,
    comment text NOT NULL DEFAULT '',
    UNIQUE (report_run_id, row_uid)
);

CREATE INDEX IF NOT EXISTS ix_report_document_reconciliation_filter
    ON wb_unit_economics.report_document_reconciliation_rows (
        report_run_id,
        document_report,
        cabinet,
        organization,
        status,
        document_type
    );

CREATE TABLE IF NOT EXISTS wb_unit_economics.source_loads (
    id bigserial PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    client_id text NOT NULL DEFAULT '',
    wb_cabinet_id text NOT NULL DEFAULT '',
    report_run_id text REFERENCES wb_unit_economics.report_runs(id) ON DELETE CASCADE,
    source_refresh_run_id text,
    required boolean NOT NULL DEFAULT false,
    publication_required boolean NOT NULL DEFAULT false,
    source_type text NOT NULL,
    source_label text NOT NULL,
    status text NOT NULL,
    snapshot_hash text NOT NULL DEFAULT '',
    row_count integer NOT NULL DEFAULT 0,
    loaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wb_unit_economics.source_refresh_runs (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    client_id text NOT NULL DEFAULT '',
    requested_by_user_id text REFERENCES wb_unit_economics.users(id) ON DELETE SET NULL,
    source_report_run_id text REFERENCES wb_unit_economics.report_runs(id) ON DELETE SET NULL,
    new_report_run_id text REFERENCES wb_unit_economics.report_runs(id) ON DELETE SET NULL,
    resumed_from_run_id text REFERENCES wb_unit_economics.source_refresh_runs(id) ON DELETE SET NULL,
    mode text NOT NULL,
    credential_source text NOT NULL,
    dry_run boolean NOT NULL DEFAULT false,
    status text NOT NULL DEFAULT 'queued',
    reason text NOT NULL DEFAULT '',
    snapshot_set_id text NOT NULL,
    period_start date NOT NULL,
    period_end date NOT NULL,
    root_dir text NOT NULL DEFAULT '',
    workbook_path text NOT NULL DEFAULT '',
    error_message text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_source_refresh_runs_active
    ON wb_unit_economics.source_refresh_runs (tenant_id, mode, status);

CREATE INDEX IF NOT EXISTS ix_source_refresh_runs_snapshot
    ON wb_unit_economics.source_refresh_runs (tenant_id, snapshot_set_id);

CREATE TABLE IF NOT EXISTS wb_unit_economics.source_refresh_collections (
    id bigserial PRIMARY KEY,
    refresh_run_id text NOT NULL REFERENCES wb_unit_economics.source_refresh_runs(id) ON DELETE CASCADE,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    client_id text NOT NULL DEFAULT '',
    wb_cabinet_id text NOT NULL DEFAULT '',
    source_type text NOT NULL,
    source_label text NOT NULL,
    required boolean NOT NULL DEFAULT false,
    publication_required boolean NOT NULL DEFAULT false,
    status text NOT NULL,
    snapshot_hash text NOT NULL DEFAULT '',
    row_count integer NOT NULL DEFAULT 0,
    raw_path text NOT NULL DEFAULT '',
    error_message text NOT NULL DEFAULT '',
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    loaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_source_refresh_collections_run
    ON wb_unit_economics.source_refresh_collections (
        refresh_run_id, source_type, status
    );

CREATE TABLE IF NOT EXISTS wb_unit_economics.source_snapshot_rows (
    id bigserial PRIMARY KEY,
    refresh_run_id text NOT NULL REFERENCES wb_unit_economics.source_refresh_runs(id) ON DELETE CASCADE,
    collection_id bigint NOT NULL REFERENCES wb_unit_economics.source_refresh_collections(id) ON DELETE CASCADE,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    client_id text NOT NULL DEFAULT '',
    wb_cabinet_id text NOT NULL DEFAULT '',
    source_type text NOT NULL,
    source_label text NOT NULL,
    source_row_id text NOT NULL DEFAULT '',
    row_number integer NOT NULL,
    raw_payload_hash text NOT NULL,
    row_payload jsonb NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (refresh_run_id, collection_id, row_number)
);

CREATE INDEX IF NOT EXISTS ix_source_snapshot_rows_lookup
    ON wb_unit_economics.source_snapshot_rows (
        tenant_id, source_type, source_row_id
    );

CREATE TABLE IF NOT EXISTS wb_unit_economics.organization_tax_profiles (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    client_id text NOT NULL REFERENCES wb_unit_economics.clients(id) ON DELETE CASCADE,
    client_company_id text REFERENCES wb_unit_economics.client_companies(id) ON DELETE SET NULL,
    organization_id text NOT NULL,
    tax_system text NOT NULL,
    vat_rate numeric NOT NULL DEFAULT 0,
    vat_mode text NOT NULL DEFAULT 'none',
    vat_deduction_mode text NOT NULL DEFAULT 'unknown',
    revenue_tax_rate numeric NOT NULL DEFAULT 0,
    income_tax_kind text NOT NULL DEFAULT '',
    valid_from date,
    valid_to date,
    source text NOT NULL,
    source_refresh_run_id text NOT NULL REFERENCES wb_unit_economics.source_refresh_runs(id) ON DELETE CASCADE,
    source_snapshot_hash text NOT NULL DEFAULT '',
    methodology_version text NOT NULL DEFAULT 'ozon-tax-profile-v2',
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_refresh_run_id, organization_id, valid_from, source)
);

CREATE INDEX IF NOT EXISTS ix_organization_tax_profiles_lookup
    ON wb_unit_economics.organization_tax_profiles (
        client_id, organization_id, valid_from, valid_to
    );

CREATE TABLE IF NOT EXISTS wb_unit_economics.organization_tax_profile_overrides (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    client_id text NOT NULL REFERENCES wb_unit_economics.clients(id) ON DELETE CASCADE,
    client_company_id text NOT NULL REFERENCES wb_unit_economics.client_companies(id) ON DELETE CASCADE,
    organization_id text NOT NULL,
    tax_system text NOT NULL,
    vat_rate numeric NOT NULL DEFAULT 0,
    vat_mode text NOT NULL DEFAULT 'none',
    vat_deduction_mode text NOT NULL DEFAULT 'unknown',
    revenue_tax_rate numeric NOT NULL DEFAULT 0,
    income_tax_kind text NOT NULL DEFAULT '',
    valid_from date NOT NULL,
    valid_to date,
    status text NOT NULL DEFAULT 'active',
    reason text NOT NULL,
    created_by_user_id text REFERENCES wb_unit_economics.users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_organization_tax_profile_overrides_lookup
    ON wb_unit_economics.organization_tax_profile_overrides (
        client_company_id, status, valid_from, valid_to
    );

CREATE TABLE IF NOT EXISTS wb_unit_economics.marketplace_mapping_items (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    client_id text NOT NULL REFERENCES wb_unit_economics.clients(id) ON DELETE CASCADE,
    marketplace text NOT NULL,
    source_item_key text NOT NULL,
    seller_account_id text NOT NULL DEFAULT '',
    organization_id text NOT NULL DEFAULT '',
    wb_cabinet_id text NOT NULL DEFAULT '',
    product_id text NOT NULL DEFAULT '',
    nm_id text NOT NULL DEFAULT '',
    ozon_sku text NOT NULL DEFAULT '',
    offer_id text NOT NULL DEFAULT '',
    vendor_code text NOT NULL DEFAULT '',
    barcode text NOT NULL DEFAULT '',
    title text NOT NULL DEFAULT '',
    source_type text NOT NULL DEFAULT '',
    source_row_id text NOT NULL DEFAULT '',
    source_snapshot_hash text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'missing',
    candidate_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (client_id, marketplace, source_item_key)
);

CREATE INDEX IF NOT EXISTS ix_marketplace_mapping_items_client_status
    ON wb_unit_economics.marketplace_mapping_items (
        client_id, marketplace, status, updated_at
    );

CREATE INDEX IF NOT EXISTS ix_marketplace_mapping_items_lookup
    ON wb_unit_economics.marketplace_mapping_items (
        tenant_id, marketplace, seller_account_id, vendor_code, barcode
    );

CREATE TABLE IF NOT EXISTS wb_unit_economics.onec_mapping_items (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    client_id text NOT NULL REFERENCES wb_unit_economics.clients(id) ON DELETE CASCADE,
    source_item_key text NOT NULL,
    onec_item_id text NOT NULL DEFAULT '',
    onec_article text NOT NULL DEFAULT '',
    onec_characteristic text NOT NULL DEFAULT '',
    name text NOT NULL DEFAULT '',
    barcode text NOT NULL DEFAULT '',
    source_type text NOT NULL DEFAULT '',
    source_row_id text NOT NULL DEFAULT '',
    source_snapshot_hash text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (client_id, source_item_key)
);

CREATE INDEX IF NOT EXISTS ix_onec_mapping_items_client_lookup
    ON wb_unit_economics.onec_mapping_items (
        client_id, onec_item_id, onec_article, barcode
    );

CREATE TABLE IF NOT EXISTS wb_unit_economics.marketplace_1c_mapping_candidates (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    client_id text NOT NULL REFERENCES wb_unit_economics.clients(id) ON DELETE CASCADE,
    item_id text NOT NULL REFERENCES wb_unit_economics.marketplace_mapping_items(id) ON DELETE CASCADE,
    onec_mapping_item_id text NOT NULL REFERENCES wb_unit_economics.onec_mapping_items(id) ON DELETE CASCADE,
    candidate_key text NOT NULL,
    method text NOT NULL,
    source text NOT NULL DEFAULT 'auto',
    confidence numeric NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'active',
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    rejected_reason text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (item_id, candidate_key)
);

CREATE INDEX IF NOT EXISTS ix_marketplace_1c_candidates_item
    ON wb_unit_economics.marketplace_1c_mapping_candidates (
        item_id, status, confidence
    );

CREATE INDEX IF NOT EXISTS ix_marketplace_1c_candidates_client
    ON wb_unit_economics.marketplace_1c_mapping_candidates (
        client_id, method, source
    );

CREATE TABLE IF NOT EXISTS wb_unit_economics.marketplace_1c_current_mappings (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    client_id text NOT NULL REFERENCES wb_unit_economics.clients(id) ON DELETE CASCADE,
    item_id text NOT NULL REFERENCES wb_unit_economics.marketplace_mapping_items(id) ON DELETE CASCADE,
    candidate_id text REFERENCES wb_unit_economics.marketplace_1c_mapping_candidates(id) ON DELETE SET NULL,
    onec_mapping_item_id text REFERENCES wb_unit_economics.onec_mapping_items(id) ON DELETE SET NULL,
    status text NOT NULL,
    match_method text NOT NULL DEFAULT '',
    confidence numeric NOT NULL DEFAULT 0,
    comment text NOT NULL DEFAULT '',
    updated_by_user_id text REFERENCES wb_unit_economics.users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    UNIQUE (item_id)
);

CREATE INDEX IF NOT EXISTS ix_marketplace_1c_current_client_status
    ON wb_unit_economics.marketplace_1c_current_mappings (
        client_id, status, updated_at
    );

CREATE TABLE IF NOT EXISTS wb_unit_economics.marketplace_1c_mapping_decisions (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    client_id text NOT NULL REFERENCES wb_unit_economics.clients(id) ON DELETE CASCADE,
    item_id text NOT NULL,
    candidate_id text REFERENCES wb_unit_economics.marketplace_1c_mapping_candidates(id) ON DELETE SET NULL,
    onec_mapping_item_id text REFERENCES wb_unit_economics.onec_mapping_items(id) ON DELETE SET NULL,
    previous_mapping_id text NOT NULL DEFAULT '',
    new_mapping_id text NOT NULL DEFAULT '',
    action text NOT NULL,
    reason text NOT NULL DEFAULT '',
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    user_id text REFERENCES wb_unit_economics.users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_marketplace_1c_decisions_item_created
    ON wb_unit_economics.marketplace_1c_mapping_decisions (
        item_id, created_at, id
    );

CREATE INDEX IF NOT EXISTS ix_marketplace_1c_decisions_client_created
    ON wb_unit_economics.marketplace_1c_mapping_decisions (
        client_id, created_at
    );

CREATE TABLE IF NOT EXISTS wb_unit_economics.live_check_cache (
    id bigserial PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    report_run_id text NOT NULL REFERENCES wb_unit_economics.report_runs(id) ON DELETE CASCADE,
    source_type text NOT NULL,
    check_type text NOT NULL,
    lookup_key text NOT NULL,
    status text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_live_check_cache_lookup
    ON wb_unit_economics.live_check_cache (
        tenant_id, report_run_id, check_type, lookup_key, created_at DESC
    );

CREATE TABLE IF NOT EXISTS wb_unit_economics.data_refresh_jobs (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    source_report_run_id text NOT NULL REFERENCES wb_unit_economics.report_runs(id) ON DELETE CASCADE,
    new_report_run_id text REFERENCES wb_unit_economics.report_runs(id) ON DELETE SET NULL,
    requested_by_user_id text NOT NULL REFERENCES wb_unit_economics.users(id) ON DELETE RESTRICT,
    thread_id text REFERENCES wb_unit_economics.ai_threads(id) ON DELETE SET NULL,
    status text NOT NULL DEFAULT 'queued',
    reason text NOT NULL DEFAULT '',
    collections jsonb NOT NULL DEFAULT '[]'::jsonb,
    snapshot_dir text NOT NULL DEFAULT '',
    workbook_path text NOT NULL DEFAULT '',
    error_message text NOT NULL DEFAULT '',
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_data_refresh_jobs_active
    ON wb_unit_economics.data_refresh_jobs (
        tenant_id, source_report_run_id, status
    );

CREATE INDEX IF NOT EXISTS ix_data_refresh_jobs_report_created
    ON wb_unit_economics.data_refresh_jobs (
        tenant_id, source_report_run_id, created_at DESC
    );

CREATE TABLE IF NOT EXISTS wb_unit_economics.audit_events (
    id bigserial PRIMARY KEY,
    tenant_id text REFERENCES wb_unit_economics.tenants(id) ON DELETE SET NULL,
    user_id text REFERENCES wb_unit_economics.users(id) ON DELETE SET NULL,
    action text NOT NULL,
    entity_type text NOT NULL DEFAULT '',
    entity_id text NOT NULL DEFAULT '',
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_audit_events_tenant_created
    ON wb_unit_economics.audit_events (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS wb_unit_economics.ai_threads (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    user_id text NOT NULL REFERENCES wb_unit_economics.users(id) ON DELETE CASCADE,
    report_run_id text REFERENCES wb_unit_economics.report_runs(id) ON DELETE SET NULL,
    title text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wb_unit_economics.ai_messages (
    id bigserial PRIMARY KEY,
    thread_id text NOT NULL REFERENCES wb_unit_economics.ai_threads(id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content text NOT NULL,
    tool_name text NOT NULL DEFAULT '',
    citations jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wb_unit_economics.ai_tool_calls (
    id bigserial PRIMARY KEY,
    thread_id text NOT NULL REFERENCES wb_unit_economics.ai_threads(id) ON DELETE CASCADE,
    user_id text REFERENCES wb_unit_economics.users(id) ON DELETE SET NULL,
    tool_name text NOT NULL,
    input_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    output_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wb_unit_economics.ai_events (
    id bigserial PRIMARY KEY,
    thread_id text NOT NULL REFERENCES wb_unit_economics.ai_threads(id) ON DELETE CASCADE,
    user_id text REFERENCES wb_unit_economics.users(id) ON DELETE SET NULL,
    event_type text NOT NULL,
    title text NOT NULL DEFAULT '',
    message text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'ok',
    tool_name text NOT NULL DEFAULT '',
    visibility text NOT NULL DEFAULT 'client',
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ai_events_thread_created
    ON wb_unit_economics.ai_events (thread_id, created_at, id);

CREATE TABLE IF NOT EXISTS wb_unit_economics.ai_client_drafts (
    id bigserial PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES wb_unit_economics.tenants(id) ON DELETE CASCADE,
    report_run_id text NOT NULL REFERENCES wb_unit_economics.report_runs(id) ON DELETE CASCADE,
    thread_id text REFERENCES wb_unit_economics.ai_threads(id) ON DELETE SET NULL,
    author_user_id text NOT NULL REFERENCES wb_unit_economics.users(id) ON DELETE RESTRICT,
    revision integer NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'ready')),
    source text NOT NULL DEFAULT 'manual',
    content text NOT NULL,
    instruction text NOT NULL DEFAULT '',
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    limitations jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (report_run_id, revision)
);

CREATE INDEX IF NOT EXISTS ix_ai_client_drafts_report_revision
    ON wb_unit_economics.ai_client_drafts (
        tenant_id, report_run_id, revision DESC
    );
