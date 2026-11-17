-- =============================================================================================
-- 02_views.sql  (PostgreSQL)
-- Author: Neo Nguyen
--
-- Shapes the fact table into the two tables everything else reads:
--   contracts   one row per contract: the award joined to all of its amendments
--   awards      the awards inside the analysis window, with the s.6(b) limit attached
-- Both are tables, built once. As views, the five audit tests, the checks and the report queries
-- would each redo the 800,000-row grouping. The settings come from the params table (written from
-- src/config.py) and are read once at the top of each statement.
-- =============================================================================================

SET search_path TO procurement;

CREATE FUNCTION param(p_name text) RETURNS text
LANGUAGE sql STABLE AS $$ SELECT value FROM params WHERE name = p_name $$;


-- ---------------------------------------------------------------------------------------------
-- Contracts: award + amendments
-- ---------------------------------------------------------------------------------------------

-- A contract is everything reported under one (owner_org, procurement_id). Rows without a
-- procurement id cannot be chained, so each stands alone under its reference number.
-- Where a department filed more than one 'C' row for the same id, the earliest is the award.
CREATE TABLE contracts AS
WITH keyed AS (
    SELECT r.*,
           coalesce(r.procurement_id, 'ref:' || r.reference_number) AS contract_key,
           coalesce(r.reporting_period, '0000-0000-Q0')             AS period_sort
    FROM contract_reports r
    WHERE r.instrument_type IS DISTINCT FROM 'SOSA'
),
award AS (
    SELECT DISTINCT ON (owner_org, contract_key) *
    FROM keyed
    WHERE instrument_type = 'C'
    ORDER BY owner_org, contract_key, contract_date, period_sort, reference_number
),
-- The current value comes from the award row or one of its amendments, never from a second 'C' row
-- filed under the same number. Departments do not record the order of filings within a quarter, so
-- in the latest quarter an amendment beats the award row, and of two amendments the higher total wins.
latest AS (
    SELECT DISTINCT ON (k.owner_org, k.contract_key)
           k.owner_org, k.contract_key, k.contract_value AS latest_value, k.reporting_period AS latest_period
    FROM keyed k
    JOIN award a ON a.owner_org = k.owner_org AND a.contract_key = k.contract_key
    WHERE k.instrument_type = 'A' OR k.reference_number = a.reference_number
    ORDER BY k.owner_org, k.contract_key, k.period_sort DESC, (k.instrument_type = 'A') DESC, k.contract_value DESC
),
-- An amendment filed twice word for word (same quarter, same amount, same new total) under two
-- reference numbers is counted once.
amend AS (
    SELECT owner_org, contract_key,
           count(*)                                   AS n_amendments,
           sum(amendment_value)                       AS amendment_total,
           count(*) FILTER (WHERE amendment_value < 0) AS n_decreases,
           min(reporting_period)                      AS first_amendment_period
    FROM (SELECT DISTINCT owner_org, contract_key, reporting_period, amendment_value, contract_value
          FROM keyed
          WHERE instrument_type = 'A') AS distinct_amendments
    GROUP BY owner_org, contract_key
)
SELECT a.owner_org, a.contract_key, a.procurement_id, a.reference_number AS award_reference,
       a.vendor_id, a.vendor_name_raw, a.contract_date AS award_date, a.fiscal_year, a.fiscal_quarter,
       a.commodity_type, a.commodity_code, a.economic_object_code, a.description_en,
       a.solicitation_procedure, a.article_6_exceptions, a.limited_tendering_reason, a.number_of_bids,
       a.contracting_entity, a.standing_offer_number, a.ministers_office, a.former_public_servant,
       a.contract_period_start, a.delivery_date, a.vendor_postal_fsa, a.country_of_vendor,
       coalesce(a.original_value, a.contract_value)             AS original_value,
       l.latest_value                                           AS final_value,
       coalesce(m.n_amendments, 0)                              AS n_amendments,
       coalesce(m.amendment_total, 0)                           AS amendment_total,
       coalesce(m.n_decreases, 0)                               AS n_decreases,
       m.first_amendment_period,
       l.latest_value - coalesce(a.original_value, a.contract_value) AS value_change,
       CASE WHEN coalesce(a.original_value, a.contract_value) > 0
            THEN l.latest_value / coalesce(a.original_value, a.contract_value) - 1 END AS growth_ratio
FROM award a
JOIN latest l USING (owner_org, contract_key)
LEFT JOIN amend m USING (owner_org, contract_key);

ALTER TABLE contracts ADD PRIMARY KEY (owner_org, contract_key);


-- ---------------------------------------------------------------------------------------------
-- Awards inside the analysis window
-- ---------------------------------------------------------------------------------------------

-- The rows the audit tests run on, with the GCR s.6(b) limit for the commodity type and whether
-- the award is within it. The regulation says "does not exceed", so an award of exactly $40,000
-- is within the limit. ANALYSIS_START is the day these limits came into force (10 June 2019).
-- Older awards stay in contracts so their amendments still chain, but they are not tested.
CREATE TABLE awards AS
WITH p AS (
    SELECT param('analysis_start')::date AS analysis_start,
           param('s6b_limit_G')::numeric AS limit_g,
           param('s6b_limit_S')::numeric AS limit_s,
           param('s6b_limit_C')::numeric AS limit_c
),
lim AS (
    SELECT c.*,
           CASE c.commodity_type WHEN 'G' THEN p.limit_g WHEN 'S' THEN p.limit_s WHEN 'C' THEN p.limit_c END AS s6b_limit
    FROM contracts c CROSS JOIN p
    WHERE c.award_date >= p.analysis_start
)
SELECT lim.*,
       d.name_en               AS department,
       v.display_name          AS vendor,
       sp.is_competitive,
       lim.original_value <= lim.s6b_limit AS is_within_limit
FROM lim
JOIN departments d USING (owner_org)
LEFT JOIN vendors v USING (vendor_id)
LEFT JOIN dim_solicitation_procedure sp ON sp.code = lim.solicitation_procedure;

ALTER TABLE awards ADD PRIMARY KEY (owner_org, contract_key);
CREATE INDEX ix_awards_org_vendor_date ON awards (owner_org, vendor_id, commodity_type, award_date);
CREATE INDEX ix_awards_org_vendor_value ON awards (owner_org, vendor_id, original_value, award_date);


-- ---------------------------------------------------------------------------------------------
-- Summaries for the report
-- ---------------------------------------------------------------------------------------------

-- Awarded without competition at a value within the limit, then amended to a value above it. Only
-- awards with a positive value at award and at least one amendment row count: a $0 award row says
-- nothing about the price that was agreed.
CREATE VIEW vw_amended_past_limit AS
SELECT *
FROM awards
WHERE NOT is_competitive AND is_within_limit
  AND original_value > 0 AND n_amendments > 0
  AND final_value > s6b_limit;

CREATE VIEW vw_spend_by_fiscal_year AS
SELECT fiscal_year,
       count(*)                                              AS n_awards,
       sum(original_value)                                   AS awarded_value,
       sum(final_value)                                      AS current_value,
       count(*) FILTER (WHERE NOT is_competitive)            AS n_non_competitive,
       round(100.0 * count(*) FILTER (WHERE NOT is_competitive) / count(*), 1) AS pct_non_competitive,
       count(*) FILTER (WHERE n_amendments > 0)              AS n_amended
FROM awards
GROUP BY fiscal_year
ORDER BY fiscal_year;
