CREATE OR REPLACE TABLE raw_violations AS
SELECT
    row_number() OVER ()                                      AS source_row_id,
    regexp_extract(filename, '(\d{4}-\d{2})\.csv$', 1)       AS source_month,
    * EXCLUDE (filename)
FROM read_csv('{THP_CSV_GLOB}',
              nullstr        = 'NULL',
              all_varchar    = true,
              filename       = true,
              union_by_name  = true);
