-- =============================================================================================
-- 03_audit_tests.sql  (PostgreSQL)
-- Author: Neo Nguyen
--
-- The five audit tests, run over the awards table (awards from ANALYSIS_START on). Each test is a view
-- that returns one row per flagged award with a plain-language reason, and audit_flags collects
-- them. A flag says an award is worth a reviewer's time. Most flagged awards will have an ordinary
-- explanation.
--
--   T1  contract splitting     several non-competitive awards to one vendor, each within the
--                              s.6(b) limit, that together exceed it within SPLIT_WINDOW_DAYS
--   T2  sole-source near limit a non-competitive award priced inside NEAR_LIMIT_BAND of the limit
--   T3  amendment growth       final value over AMENDMENT_GROWTH_FLAG above the award, or at
--                              least AMENDMENT_COUNT_FLAG amendments
--   T4  possible duplicate     same department, vendor and award value within DUPLICATE_WINDOW_DAYS
--   T5  vendor concentration   one vendor holds over CONCENTRATION_SHARE of a department's
--                              non-competitive spend
-- All cut-offs come from the params table, written from src/config.py.
-- =============================================================================================

SET search_path TO procurement;


-- ---------------------------------------------------------------------------------------------
-- T1  Contract splitting
-- ---------------------------------------------------------------------------------------------

-- Splitting matters because it avoids the bid requirement, so only non-competitive awards are
-- looked at. Call-ups against a standing offer are left out: the competition was held when the
-- offer was set up, and repeated small call-ups are how standing offers are meant to be used.
--
-- Step 1 (look_back): for each award, take the same department's awards to the same vendor in the
-- same commodity type over the SPLIT_WINDOW_DAYS before it. The award is a "trigger" when there are
-- at least two, every one is within the limit, and together they are over it.
-- Step 2 (look_ahead): flag every award that has a trigger on its own day or within the window
-- after it, so the first award of a run is flagged along with the last.
CREATE VIEW vw_test_splitting AS
WITH eligible AS (
    SELECT *
    FROM awards
    WHERE NOT is_competitive
      AND vendor_id IS NOT NULL
      AND commodity_type IS NOT NULL
      AND coalesce(contracting_entity, '') NOT IN ('DSOSA', 'PWSOSA', 'SSCSOSA')
      AND standing_offer_number IS NULL
),
look_back AS (
    SELECT owner_org, contract_key, vendor_id, commodity_type, award_date, original_value, s6b_limit,
           count(*) OVER w >= 2
               AND bool_and(is_within_limit) OVER w
               AND sum(original_value) OVER w > s6b_limit AS is_trigger
    FROM eligible
    WINDOW w AS (PARTITION BY owner_org, vendor_id, commodity_type
                 ORDER BY award_date
                 RANGE BETWEEN (param('split_window_days') || ' days')::interval PRECEDING AND CURRENT ROW)
),
look_ahead AS (
    SELECT *,
           bool_or(is_trigger)  OVER ahead  AS in_cluster,
           count(*)             OVER around AS n_nearby,
           sum(original_value)  OVER around AS value_nearby
    FROM look_back
    WINDOW ahead  AS (PARTITION BY owner_org, vendor_id, commodity_type
                      ORDER BY award_date
                      RANGE BETWEEN CURRENT ROW AND (param('split_window_days') || ' days')::interval FOLLOWING),
           around AS (PARTITION BY owner_org, vendor_id, commodity_type
                      ORDER BY award_date
                      RANGE BETWEEN (param('split_window_days') || ' days')::interval PRECEDING
                                AND (param('split_window_days') || ' days')::interval FOLLOWING)
)
SELECT owner_org, contract_key, 'T1' AS test_id, 'contract splitting' AS test_name,
       original_value AS flagged_value,
       format('part of a run of non-competitive awards to this vendor that passes the $%s limit inside %s days; '
              '%s awards worth $%s within %s days either side of this one',
              to_char(s6b_limit, 'FM999,999'), param('split_window_days'),
              n_nearby, to_char(value_nearby, 'FM999,999,999'), param('split_window_days')) AS flag_detail
FROM look_ahead
WHERE in_cluster;


-- ---------------------------------------------------------------------------------------------
-- T2  Sole-source award priced just under the limit
-- ---------------------------------------------------------------------------------------------

-- Non-competitive, and the award sits inside the top NEAR_LIMIT_BAND of the range that needs no
-- bids: for services, $36,000 to $40,000. A price that lands there is worth a second look.
CREATE VIEW vw_test_near_limit AS
SELECT owner_org, contract_key, 'T2' AS test_id, 'sole-source near limit' AS test_name,
       original_value AS flagged_value,
       format('non-competitive %s award of $%s, within %s%% of the $%s limit',
              lower(ct.label), to_char(original_value, 'FM999,999.00'),
              (param('near_limit_band')::numeric * 100)::int, to_char(s6b_limit, 'FM999,999')) AS flag_detail
FROM awards a
JOIN dim_commodity_type ct ON ct.code = a.commodity_type
WHERE NOT is_competitive
  AND original_value >= s6b_limit * (1 - param('near_limit_band')::numeric)
  AND original_value <= s6b_limit;


-- ---------------------------------------------------------------------------------------------
-- T3  Amendment growth
-- ---------------------------------------------------------------------------------------------

-- A contract that ended up far above what was approved at award, or that was amended again and
-- again. Only awards of MIN_ORIGINAL_FOR_GROWTH or more are tested: a tiny award can grow by a
-- huge multiple without meaning anything.
CREATE VIEW vw_test_amendment_growth AS
SELECT owner_org, contract_key, 'T3' AS test_id, 'amendment growth' AS test_name,
       value_change AS flagged_value,
       format('%s amendment(s): $%s at award, now $%s (%s%%)',
              n_amendments, to_char(original_value, 'FM999,999,999'), to_char(final_value, 'FM999,999,999'),
              to_char(growth_ratio * 100, 'FMS999,999')) AS flag_detail
FROM awards
WHERE original_value >= param('min_original_for_growth')::numeric
  AND (growth_ratio > param('amendment_growth_flag')::numeric
       OR n_amendments >= param('amendment_count_flag')::int);


-- ---------------------------------------------------------------------------------------------
-- T4  Possible duplicate
-- ---------------------------------------------------------------------------------------------

-- Two contracts with the same department, vendor and award value, dated within a week. Some are
-- task authorisations issued in batches; some are the same contract keyed twice. The later one is
-- flagged and points at the earlier one. Ties on the date are ordered by contract key in plain
-- byte order (COLLATE "C"), the same order pandas uses, so both sides pick the same row.
CREATE VIEW vw_test_duplicate AS
WITH ordered AS (
    SELECT owner_org, contract_key, vendor_id, original_value, award_date,
           lag(award_date)   OVER w AS prev_date,
           lag(contract_key) OVER w AS prev_key
    FROM awards
    WHERE original_value > 0 AND vendor_id IS NOT NULL
    WINDOW w AS (PARTITION BY owner_org, vendor_id, original_value
                 ORDER BY award_date, contract_key COLLATE "C")
)
SELECT owner_org, contract_key, 'T4' AS test_id, 'possible duplicate' AS test_name,
       original_value AS flagged_value,
       format('same vendor and value ($%s) as %s, awarded %s day(s) earlier',
              to_char(original_value, 'FM999,999,999.00'), prev_key, award_date - prev_date) AS flag_detail
FROM ordered
WHERE prev_date IS NOT NULL
  AND award_date - prev_date <= param('duplicate_window_days')::int;


-- ---------------------------------------------------------------------------------------------
-- T5  Vendor concentration
-- ---------------------------------------------------------------------------------------------

-- Per department: each vendor's share of the non-competitive awarded value over the window.
CREATE VIEW vw_vendor_concentration AS
SELECT owner_org, department, vendor_id, vendor,
       sum(original_value)                                      AS non_competitive_value,
       count(*)                                                 AS n_awards,
       sum(sum(original_value)) OVER (PARTITION BY owner_org)   AS department_non_competitive_value,
       sum(original_value) / sum(sum(original_value)) OVER (PARTITION BY owner_org) AS share
FROM awards
WHERE NOT is_competitive AND original_value > 0
GROUP BY owner_org, department, vendor_id, vendor;

-- Flag every non-competitive award to a vendor that holds over CONCENTRATION_SHARE of its
-- department's non-competitive spend, in departments with at least CONCENTRATION_MIN_SPEND of it.
CREATE VIEW vw_test_concentration AS
SELECT a.owner_org, a.contract_key, 'T5' AS test_id, 'vendor concentration' AS test_name,
       a.original_value AS flagged_value,
       format('vendor holds %s%% of the department''s $%s non-competitive spend (%s awards)',
              round(c.share * 100), to_char(c.department_non_competitive_value, 'FM999,999,999,999'),
              c.n_awards) AS flag_detail
FROM awards a
JOIN vw_vendor_concentration c USING (owner_org, vendor_id)
WHERE NOT a.is_competitive
  AND c.share > param('concentration_share')::numeric
  AND c.department_non_competitive_value >= param('concentration_min_spend')::numeric;


-- ---------------------------------------------------------------------------------------------
-- All flags, and one line per contract
-- ---------------------------------------------------------------------------------------------

-- Built once as a table: each test scans every award, and the score, the checks and the report
-- all read the flags again.
CREATE TABLE audit_flags AS
SELECT * FROM vw_test_splitting
UNION ALL SELECT * FROM vw_test_near_limit
UNION ALL SELECT * FROM vw_test_amendment_growth
UNION ALL SELECT * FROM vw_test_duplicate
UNION ALL SELECT * FROM vw_test_concentration;

ALTER TABLE audit_flags ADD PRIMARY KEY (owner_org, contract_key, test_id);

-- Every award with its flags side by side (zero flags included), the base for the risk score.
CREATE VIEW vw_award_flags AS
SELECT a.*,
       coalesce(f.n_flags, 0)                          AS n_flags,
       coalesce(f.t1, false) AS t1_splitting,
       coalesce(f.t2, false) AS t2_near_limit,
       coalesce(f.t3, false) AS t3_amendment_growth,
       coalesce(f.t4, false) AS t4_duplicate,
       coalesce(f.t5, false) AS t5_concentration,
       f.flag_details
FROM awards a
LEFT JOIN (
    SELECT owner_org, contract_key,
           count(*)                                      AS n_flags,
           bool_or(test_id = 'T1') AS t1, bool_or(test_id = 'T2') AS t2, bool_or(test_id = 'T3') AS t3,
           bool_or(test_id = 'T4') AS t4, bool_or(test_id = 'T5') AS t5,
           string_agg(test_id || ': ' || flag_detail, ' | ' ORDER BY test_id) AS flag_details
    FROM audit_flags
    GROUP BY owner_org, contract_key
) f USING (owner_org, contract_key);

-- Headline numbers per test for the report.
CREATE VIEW vw_test_summary AS
SELECT f.test_id, f.test_name,
       count(*)                                    AS n_flagged,
       count(DISTINCT f.owner_org)                 AS n_departments,
       sum(a.original_value)                       AS awarded_value_flagged,
       round(100.0 * count(*) / (SELECT count(*) FROM awards), 2) AS pct_of_awards
FROM audit_flags f
JOIN awards a USING (owner_org, contract_key)
GROUP BY f.test_id, f.test_name
ORDER BY f.test_id;


-- ---------------------------------------------------------------------------------------------
-- Risk score
-- ---------------------------------------------------------------------------------------------

-- Review priority per award: the weights of its flags, scaled up for larger awards.
--   flag_points       sum of the weights of the tests that flagged the award (0 to 100)
--   value_percentile  the award's percent rank by original value among all awards (0 to 1)
--   risk_score        flag_points x (0.5 + 0.5 x value_percentile); unflagged awards score 0
--   risk_rank         1 = review first; ties go to the larger award, then to the key in byte order
-- The score is kept unrounded so it matches src/flags.py exactly. Anything that displays it rounds it.
CREATE TABLE risk_scores AS
WITH w AS (
    SELECT param('weight_T1')::int AS t1, param('weight_T2')::int AS t2, param('weight_T3')::int AS t3,
           param('weight_T4')::int AS t4, param('weight_T5')::int AS t5
),
scored AS (
    SELECT f.owner_org, f.contract_key, f.original_value,
           f.t1_splitting::int * w.t1 + f.t2_near_limit::int * w.t2 + f.t3_amendment_growth::int * w.t3
               + f.t4_duplicate::int * w.t4 + f.t5_concentration::int * w.t5 AS flag_points,
           percent_rank() OVER (ORDER BY f.original_value)                    AS value_percentile
    FROM vw_award_flags f CROSS JOIN w
)
SELECT owner_org, contract_key, flag_points, value_percentile,
       flag_points * (0.5 + 0.5 * value_percentile) AS risk_score,
       row_number() OVER (ORDER BY flag_points * (0.5 + 0.5 * value_percentile) DESC, original_value DESC,
                                   owner_org COLLATE "C", contract_key COLLATE "C") AS risk_rank
FROM scored;

ALTER TABLE risk_scores ADD PRIMARY KEY (owner_org, contract_key);
