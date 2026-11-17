-- =============================================================================================
-- 04_checks.sql  (PostgreSQL)
-- Author: Neo Nguyen
--
-- Data checks. Each returns: name, severity, value found, value expected.
--   hard   must match, or run_sql.py rolls the whole rebuild back
--   info   reported as found; these are facts about how departments report, not load errors.
--          The report lists them so a reader knows what the tests are working with.
-- Primary and foreign keys in 01_tables.sql already stop duplicate keys and unknown codes at load
-- time; the hard checks below repeat the important ones so the report can list them in one place.
-- The file is one SELECT (no SET at the top) so run_sql.py can read its result straight back.
-- =============================================================================================


-- ---------------------------------------------------------------------------------------------
-- Hard: keys, references, derived columns
-- ---------------------------------------------------------------------------------------------

SELECT 'reports: unique (owner_org, reference_number)' AS check_name, 'hard' AS severity,
       count(*) - count(DISTINCT (owner_org, reference_number)) AS actual, 0::bigint AS expected
FROM contract_reports

UNION ALL
SELECT 'reports: every row has a known department', 'hard',
       count(*) FILTER (WHERE d.owner_org IS NULL), 0
FROM contract_reports r LEFT JOIN departments d USING (owner_org)

UNION ALL
SELECT 'reports: vendor_id points at a vendor', 'hard',
       count(*) FILTER (WHERE r.vendor_id IS NOT NULL AND v.vendor_id IS NULL), 0
FROM contract_reports r LEFT JOIN vendors v USING (vendor_id)

UNION ALL
-- every vendor has exactly one 'rule' alias: its own canonical key
SELECT 'vendors: one canonical alias each', 'hard',
       (SELECT count(*) FROM vendor_aliases WHERE match_method = 'rule'), (SELECT count(*) FROM vendors)

UNION ALL
SELECT 'vendors: alias row counts add up to vendor row counts', 'hard',
       (SELECT count(*)
        FROM vendors v
        LEFT JOIN (SELECT vendor_id, sum(row_count) AS alias_rows FROM vendor_aliases GROUP BY vendor_id) a
               USING (vendor_id)
        WHERE v.row_count IS DISTINCT FROM a.alias_rows), 0

UNION ALL
SELECT 'reports: contract_date inside the load window', 'hard',
       count(*) FILTER (WHERE contract_date < param('load_start')::date OR contract_date > current_date), 0
FROM contract_reports

UNION ALL
-- fiscal year label must agree with the date it was derived from
SELECT 'reports: fiscal_year matches contract_date', 'hard',
       count(*) FILTER (WHERE fiscal_year <> (extract(year FROM contract_date - interval '3 months'))::int::text
                                         || '-' || (extract(year FROM contract_date - interval '3 months') + 1)::int::text), 0
FROM contract_reports

UNION ALL
-- every contract appears exactly once
SELECT 'contracts: one row per (owner_org, contract_key)', 'hard',
       count(*) - count(DISTINCT (owner_org, contract_key)), 0
FROM contracts

UNION ALL
-- amendments never produce a contract on their own: each contract has a 'C' award row behind it
SELECT 'contracts: award row count = C rows that start a contract', 'hard',
       (SELECT count(*) FROM contracts),
       (SELECT count(DISTINCT (owner_org, coalesce(procurement_id, 'ref:' || reference_number)))
        FROM contract_reports WHERE instrument_type = 'C')

UNION ALL
-- run_sql.py has already checked that every setting the SQL reads was written; none may be blank
SELECT 'params: no setting is blank', 'hard',
       count(*) FILTER (WHERE value IS NULL OR value = ''), 0
FROM params

UNION ALL
-- every flag points at an award inside the analysis window
SELECT 'flags: every flagged contract is in awards', 'hard',
       (SELECT count(*) FROM audit_flags f LEFT JOIN awards a USING (owner_org, contract_key)
        WHERE a.contract_key IS NULL), 0

UNION ALL
-- T1 by construction: each flagged award is non-competitive and itself within the limit
SELECT 'flags: T1 awards are non-competitive and within the limit', 'hard',
       (SELECT count(*) FROM audit_flags f JOIN awards a USING (owner_org, contract_key)
        WHERE f.test_id = 'T1' AND (a.is_competitive OR NOT a.is_within_limit)), 0

UNION ALL
-- a splitting run has at least two awards per department, vendor and commodity type
SELECT 'flags: no T1 award stands alone', 'hard',
       (SELECT count(*) FROM (
            SELECT a.owner_org, a.vendor_id, a.commodity_type
            FROM audit_flags f JOIN awards a USING (owner_org, contract_key)
            WHERE f.test_id = 'T1'
            GROUP BY 1, 2, 3 HAVING count(*) < 2) AS lone), 0

UNION ALL
-- T2 by construction: non-competitive and within the limit
SELECT 'flags: T2 awards are non-competitive and within the limit', 'hard',
       (SELECT count(*) FROM audit_flags f JOIN awards a USING (owner_org, contract_key)
        WHERE f.test_id = 'T2' AND (a.is_competitive OR NOT a.is_within_limit)), 0

UNION ALL
-- the per-contract view keeps every award, flagged or not
SELECT 'award_flags: one row per award', 'hard',
       (SELECT count(*) FROM vw_award_flags), (SELECT count(*) FROM awards)

UNION ALL
SELECT 'risk_scores: one row per award', 'hard',
       (SELECT count(*) FROM risk_scores), (SELECT count(*) FROM awards)

UNION ALL
SELECT 'risk_scores: every score is between 0 and 100', 'hard',
       (SELECT count(*) FROM risk_scores WHERE risk_score IS NULL OR risk_score < 0 OR risk_score > 100), 0

UNION ALL
-- an award scores above zero exactly when at least one test flagged it
SELECT 'risk_scores: scored awards = flagged awards', 'hard',
       (SELECT count(*) FROM risk_scores WHERE risk_score > 0),
       (SELECT count(DISTINCT (owner_org, contract_key)) FROM audit_flags)


-- ---------------------------------------------------------------------------------------------
-- Info: how the departments reported
-- ---------------------------------------------------------------------------------------------

UNION ALL
-- the file is "contracts over $10,000", yet some award rows sit below it
SELECT 'award rows with contract_value under $10,000', 'info',
       count(*) FILTER (WHERE instrument_type = 'C' AND contract_value < 10000), 0
FROM contract_reports

UNION ALL
SELECT 'award rows with contract_value zero or negative', 'info',
       count(*) FILTER (WHERE instrument_type = 'C' AND contract_value <= 0), 0
FROM contract_reports

UNION ALL
-- on an award row the total should equal original + amendment (amendment is usually 0)
SELECT 'award rows where total <> original + amendment (by over $1)', 'info',
       count(*) FILTER (WHERE instrument_type = 'C' AND original_value IS NOT NULL AND amendment_value IS NOT NULL
                          AND abs(contract_value - original_value - amendment_value) > 1), 0
FROM contract_reports

UNION ALL
-- an amendment whose award was filed before the load window, or never filed
SELECT 'amendment rows with no award row in the load window', 'info',
       count(*), 0
FROM contract_reports a
WHERE a.instrument_type = 'A'
  AND a.procurement_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM contract_reports c
                  WHERE c.owner_org = a.owner_org AND c.procurement_id = a.procurement_id
                    AND c.instrument_type = 'C')

UNION ALL
SELECT 'rows with no procurement_id (cannot be chained to amendments)', 'info',
       count(*) FILTER (WHERE procurement_id IS NULL), 0
FROM contract_reports

UNION ALL
SELECT 'rows with no instrument_type', 'info', count(*) FILTER (WHERE instrument_type IS NULL), 0
FROM contract_reports

UNION ALL
SELECT 'award rows with no commodity_type (no s.6(b) limit can be applied)', 'info',
       count(*) FILTER (WHERE instrument_type = 'C' AND commodity_type IS NULL), 0
FROM contract_reports

UNION ALL
SELECT 'award rows with no solicitation_procedure', 'info',
       count(*) FILTER (WHERE instrument_type = 'C' AND solicitation_procedure IS NULL), 0
FROM contract_reports

UNION ALL
SELECT 'award rows with no number_of_bids', 'info',
       count(*) FILTER (WHERE instrument_type = 'C' AND number_of_bids IS NULL), 0
FROM contract_reports

UNION ALL
-- non-competitive but no s.6 exception given (the regulation requires one)
SELECT 'non-competitive awards with no s.6 exception recorded', 'info',
       count(*) FILTER (WHERE instrument_type = 'C' AND solicitation_procedure = 'TN'
                          AND (article_6_exceptions IS NULL OR article_6_exceptions IN ('0', '?'))), 0
FROM contract_reports

UNION ALL
SELECT 'rows where delivery_date is before contract_date', 'info',
       count(*) FILTER (WHERE delivery_date < contract_date), 0
FROM contract_reports

UNION ALL
SELECT 'rows with a malformed reporting_period (set to null)', 'info',
       count(*) FILTER (WHERE reporting_period IS NULL), 0
FROM contract_reports

UNION ALL
-- the same procurement id reported as a new contract more than once
SELECT 'procurement ids with more than one award (C) row', 'info',
       count(*), 0
FROM (SELECT owner_org, procurement_id FROM contract_reports
      WHERE instrument_type = 'C' AND procurement_id IS NOT NULL
      GROUP BY 1, 2 HAVING count(*) > 1) AS x

UNION ALL
-- a contract whose award and amendment rows disagree on how it was procured; the tests read the award row
SELECT 'contracts whose rows disagree on the solicitation procedure', 'info',
       count(*), 0
FROM (SELECT owner_org, procurement_id FROM contract_reports
      WHERE procurement_id IS NOT NULL AND instrument_type IN ('C', 'A') AND solicitation_procedure IS NOT NULL
      GROUP BY 1, 2 HAVING count(DISTINCT solicitation_procedure) > 1) AS x

UNION ALL
-- a standing offer agreement carries no value by the reporting rules
SELECT 'SOSA rows with a non-zero contract_value', 'info',
       count(*) FILTER (WHERE instrument_type = 'SOSA' AND contract_value <> 0), 0
FROM contract_reports

UNION ALL
SELECT 'rows with no vendor_id (name cleaned to nothing)', 'info',
       count(*) FILTER (WHERE vendor_id IS NULL), 0
FROM contract_reports;
