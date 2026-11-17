-- =============================================================================================
-- 05_tableau_views.sql  (PostgreSQL)
-- Author: Neo Nguyen
--
-- What the Tableau dashboard reads: one row per award in the analysis window, with its flags and
-- risk score, in plain labels a dashboard can show as they are. src/export_tableau.py writes it to
-- data/tableau/awards.csv, because Tableau Public reads files, not databases.
-- Vendor names are left out of the public version. Each vendor gets a stable code instead, so the
-- dashboard can still show that several awards went to the same supplier.
-- =============================================================================================

SET search_path TO procurement;

CREATE VIEW vw_tableau_awards AS
SELECT f.owner_org,
       f.department,
       f.award_reference,
       'V' || lpad(f.vendor_id::text, 5, '0')                        AS vendor_code,
       f.award_date,
       f.fiscal_year,
       f.fiscal_quarter,
       CASE f.commodity_type WHEN 'S' THEN 'Service' WHEN 'G' THEN 'Good' WHEN 'C' THEN 'Construction' END AS commodity,
       CASE WHEN f.is_competitive THEN 'Competed' WHEN NOT f.is_competitive THEN 'Sole-sourced' ELSE 'Unknown' END AS competition,
       f.original_value                                              AS value_at_award,
       f.final_value                                                 AS value_now,
       f.n_amendments,
       f.s6b_limit,
       f.is_within_limit,
       f.t1_splitting::int        AS t1_splitting,
       f.t2_near_limit::int       AS t2_near_limit,
       f.t3_amendment_growth::int AS t3_amendment_growth,
       f.t4_duplicate::int        AS t4_duplicate,
       f.t5_concentration::int    AS t5_concentration,
       f.n_flags,
       (f.n_flags > 0)::int                                          AS is_flagged,
       round(r.risk_score::numeric, 1)                               AS risk_score,
       r.risk_rank,
       f.flag_details
FROM vw_award_flags f
JOIN risk_scores r USING (owner_org, contract_key);
