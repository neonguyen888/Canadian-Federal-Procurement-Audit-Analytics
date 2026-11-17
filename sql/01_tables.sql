-- =============================================================================================
-- 01_tables.sql  (PostgreSQL)
-- Author: Neo Nguyen
--
-- Creates the procurement schema: code lists, the two lookups, the fact table and the parameter
-- table. src/run_sql.py then loads data/processed/*.csv into them.
--   dim_...            code lists copied from the portal's data dictionary
--   departments        one row per reporting organisation
--   vendors            one row per cleaned vendor name (src/vendors.py)
--   contract_reports   one row per transaction a department reported: a contract award (C),
--                      an amendment (A) or a standing offer / supply arrangement (SOSA)
--   params             the settings from src/config.py the views depend on
-- =============================================================================================

DROP SCHEMA IF EXISTS procurement CASCADE;
CREATE SCHEMA procurement;
SET search_path TO procurement;


-- ---------------------------------------------------------------------------------------------
-- Code lists, copied from the data dictionary:
-- https://open.canada.ca/data/recombinant-published-schema/contracts.json
-- ---------------------------------------------------------------------------------------------

CREATE TABLE dim_commodity_type (
    code  text PRIMARY KEY,
    label text NOT NULL
);
INSERT INTO dim_commodity_type VALUES ('G', 'Good'), ('S', 'Service'), ('C', 'Construction');

CREATE TABLE dim_instrument_type (
    code  text PRIMARY KEY,
    label text NOT NULL
);
INSERT INTO dim_instrument_type VALUES
    ('C', 'Contract (or call-up against a standing offer)'),
    ('A', 'Amendment'),
    ('SOSA', 'Standing offer or supply arrangement agreement');

-- is_competitive: whether bids were solicited. An ACAN is treated as non-competitive here because
-- no bids are received; the department only posts a notice that it intends to award to one firm.
CREATE TABLE dim_solicitation_procedure (
    code           text    PRIMARY KEY,
    label          text    NOT NULL,
    is_competitive boolean NOT NULL
);
INSERT INTO dim_solicitation_procedure VALUES
    ('OB', 'Competitive - open bidding (GETS)',   true),
    ('TC', 'Competitive - traditional',           true),
    ('ST', 'Competitive - selective tendering',   true),
    ('AC', 'Advance contract award notice (ACAN)', false),
    ('TN', 'Non-competitive',                     false);

-- Government Contracts Regulations s.6: the reason a department gave for not soliciting bids.
-- https://laws-lois.justice.gc.ca/eng/regulations/SOR-87-402/section-6.html
CREATE TABLE dim_article_6_exception (
    code  text PRIMARY KEY,
    label text NOT NULL
);
INSERT INTO dim_article_6_exception VALUES
    ('0', 'Not applicable (bids were solicited)'),
    ('1', 'Pressing emergency'),
    ('2', 'Below the s.6(b) dollar limit'),
    ('3', 'Not in the public interest to solicit bids'),
    ('4', 'Only one person is capable of performing the contract');


-- ---------------------------------------------------------------------------------------------
-- Lookups
-- ---------------------------------------------------------------------------------------------

CREATE TABLE departments (                                   -- departments.csv
    owner_org text PRIMARY KEY,
    name_en   text NOT NULL,
    name_fr   text NOT NULL
);

CREATE TABLE vendors (                                       -- vendors.csv
    vendor_id              integer PRIMARY KEY,
    vendor_name_normalized text    NOT NULL UNIQUE,          -- the alias with the most rows
    display_name           text    NOT NULL,                 -- the most common raw spelling
    raw_name_count         integer NOT NULL,                 -- how many spellings fed into this vendor
    alias_count            integer NOT NULL,                 -- how many cleaned keys were merged
    row_count              integer NOT NULL
);

-- Every cleaned spelling and how it reached its vendor, so a merge can be traced and undone.
--   rule      the key is the vendor's own canonical key
--   squeezed  same letters once spaces are removed
--   fuzzy     letters match at least FUZZY_THRESHOLD out of 100 (sampled and checked by hand)
CREATE TABLE vendor_aliases (                                -- vendor_aliases.csv
    alias_key    text    PRIMARY KEY,
    vendor_id    integer NOT NULL REFERENCES vendors (vendor_id),
    match_method text    NOT NULL CHECK (match_method IN ('rule', 'squeezed', 'fuzzy')),
    match_score  numeric(5,1) NOT NULL,
    row_count    integer NOT NULL
);


-- ---------------------------------------------------------------------------------------------
-- Fact table
-- ---------------------------------------------------------------------------------------------

-- One row per reported transaction.                         (contract_reports.csv)
-- Rows that belong to the same contract share (owner_org, procurement_id): the award row has
-- instrument_type 'C' and each later change is an 'A' row whose contract_value is the amended
-- total. contract_date on an amendment is the original award date, per the reporting rules;
-- reporting_period says which quarter the amendment was filed in.
CREATE TABLE contract_reports (
    owner_org               text          NOT NULL REFERENCES departments (owner_org),
    reference_number        text          NOT NULL,
    procurement_id          text,
    vendor_id               integer       REFERENCES vendors (vendor_id),
    vendor_name_raw         text          NOT NULL,
    vendor_postal_fsa       text,                            -- first three characters of the postal code
    country_of_vendor       text,
    buyer_name              text,
    contract_date           date          NOT NULL,
    contract_period_start   date,
    delivery_date           date,
    contract_value          numeric(16,2) NOT NULL,          -- total after this transaction
    original_value          numeric(16,2),                   -- value at award
    amendment_value         numeric(16,2),                   -- this amendment only (negative = decrease)
    economic_object_code    text,
    description_en          text,
    commodity_type          text          REFERENCES dim_commodity_type (code),
    commodity_code          text,
    solicitation_procedure  text          REFERENCES dim_solicitation_procedure (code),
    limited_tendering_reason text,
    number_of_bids          integer,
    article_6_exceptions    text,                            -- '?' appears in the file, so no foreign key
    award_criteria          text,
    agreement_type_code     text,
    instrument_type         text          REFERENCES dim_instrument_type (code),
    contracting_entity      text,
    standing_offer_number   text,
    ministers_office        boolean,
    former_public_servant   boolean,
    reporting_period        text,                            -- 'YYYY-YYYY-Qn', null when malformed
    fiscal_year             text          NOT NULL,          -- of contract_date, April to March
    fiscal_quarter          text          NOT NULL,
    PRIMARY KEY (owner_org, reference_number)
);

-- The tests group by department and vendor over time, and chain amendments to their award
CREATE INDEX ix_reports_org_vendor_date ON contract_reports (owner_org, vendor_id, contract_date);
CREATE INDEX ix_reports_org_procurement ON contract_reports (owner_org, procurement_id);
CREATE INDEX ix_reports_date            ON contract_reports (contract_date);


-- ---------------------------------------------------------------------------------------------
-- Parameters and Python-side data-quality counts
-- ---------------------------------------------------------------------------------------------

-- Written by run_sql.py from src/config.py, so SQL and Python use the same cut-offs.
CREATE TABLE params (
    name  text PRIMARY KEY,
    value text NOT NULL
);

-- What clean.py changed or dropped, so the report can list it with the SQL checks.
CREATE TABLE dq_python (                                     -- dq_python.csv
    check_name text   PRIMARY KEY,
    value      bigint NOT NULL
);
