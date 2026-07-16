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
