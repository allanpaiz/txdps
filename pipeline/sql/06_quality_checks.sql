CREATE OR REPLACE TABLE null_profile AS
WITH counts AS (
    SELECT source_month AS month,
           count(*)     AS records,
           count(COLUMNS(* EXCLUDE (source_row_id, source_month)))
    FROM raw_violations
    GROUP BY source_month)
SELECT month, column_name, records, records - non_null AS null_count
FROM (UNPIVOT counts ON COLUMNS(* EXCLUDE (month, records)) INTO NAME column_name VALUE non_null);

CREATE OR REPLACE TABLE data_quality AS
WITH
tm AS (SELECT * FROM violations WHERE month = '{TARGET_MONTH}'),
raw_tm AS (SELECT * FROM raw_violations WHERE source_month = '{TARGET_MONTH}'),
n AS (SELECT count(*) AS records FROM tm),
ticket_integrity AS (
    SELECT count(*) FILTER (WHERE n_cty > 1 OR n_ts > 1 OR n_off > 1) AS bad_tickets,
           count(*) AS tickets
    FROM (SELECT ticket_number, count(DISTINCT county_name) n_cty,
                 count(DISTINCT stop_ts) n_ts, count(DISTINCT officer_id) n_off
          FROM violations GROUP BY 1)),
dups AS (
    SELECT (SELECT count(*) FROM raw_tm)
         - (SELECT count(*) FROM (SELECT DISTINCT * EXCLUDE (source_row_id, source_month) FROM raw_tm)) AS dup_rows),
midnight AS (
    SELECT count(*) FILTER (WHERE strftime(stop_ts, '%H:%M') IN ('00:00', '00:01')) AS at_midnight,
           count(*) AS stops
    FROM stops WHERE month = '{TARGET_MONTH}'),
t_tm AS (SELECT * FROM tickets WHERE month = '{TARGET_MONTH}'),
s_tm AS (SELECT * FROM stops   WHERE month = '{TARGET_MONTH}'),
schema_drift AS (
    SELECT count(DISTINCT column_name) AS drift_cols FROM null_profile WHERE null_count = records)

SELECT 'Q01' AS check_id, 'Violation records' AS check_name,
       records AS value, NULL::BIGINT AS denominator, 'INFO' AS status,
       'Source rows, including inspection entries with no recorded violation' AS handling FROM n
UNION ALL
SELECT 'Q02', 'Records missing a Ticket_Number',
       count(*) FILTER (WHERE ticket_number IS NULL), count(*),
       CASE WHEN count(*) FILTER (WHERE ticket_number IS NULL) = 0 THEN 'PASS' ELSE 'WARN' END,
       'Use Ticket_Number as the document key' FROM tm
UNION ALL
SELECT 'Q03', 'Tickets mapping to more than one county, timestamp or officer (all months)',
       bad_tickets, tickets, CASE WHEN bad_tickets = 0 THEN 'PASS' ELSE 'WARN' END,
       'Confirms a ticket is a single document at one place and time' FROM ticket_integrity
UNION ALL
SELECT 'Q04', 'Records with a timestamp outside of March',
       count(*) FILTER (WHERE stop_ts IS NULL OR strftime(stop_ts, '%Y-%m') <> '{TARGET_MONTH}'), count(*),
       CASE WHEN count(*) FILTER (WHERE stop_ts IS NULL OR strftime(stop_ts, '%Y-%m') <> '{TARGET_MONTH}') = 0 THEN 'PASS' ELSE 'WARN' END,
       'Data month and record dates agree' FROM tm
UNION ALL
SELECT 'Q17', 'Source records missing a county name',
       count(*) FILTER (WHERE nullif(trim(County), '') IS NULL), count(*),
       CASE WHEN count(*) FILTER (WHERE nullif(trim(County), '') IS NULL) = 0 THEN 'PASS' ELSE 'WARN' END,
       'The source identifies counties by name; Q05 separately checks names against the county reference' FROM raw_tm
UNION ALL
SELECT 'Q05', 'County names that do not match TxDOT county names',
       count(*) FILTER (WHERE r.county_name IS NULL), count(*),
       CASE WHEN count(*) FILTER (WHERE r.county_name IS NULL) = 0 THEN 'PASS' ELSE 'WARN' END,
       'One spelling fixed in pre-processing before matching (Dewitt -> De Witt, rule R1)'
FROM tm LEFT JOIN county_reference r USING (county_name)
UNION ALL
SELECT 'Q06', 'Texas counties with zero stops',
       254 - count(DISTINCT county_name), 254, 'INFO',
       'All 254 counties report at least one stop' FROM s_tm
UNION ALL
SELECT 'Q07', 'Stops without usable latitude/longitude',
       count(*) FILTER (WHERE latitude IS NULL), count(*), 'WARN',
       'County is recorded on every stop; coordinates used only for the location figure' FROM s_tm
UNION ALL
SELECT 'Q08', 'Exact duplicate violation records',
       dup_rows, (SELECT records FROM n), 'WARN',
       'Kept (e.g. repeat offenses per passenger); no effect on stop counts' FROM dups
UNION ALL
SELECT 'Q09', 'Searched flag written as YES instead of Yes',
       count(*) FILTER (WHERE Searched = 'YES'), count(*), 'FIXED',
       'Case insensitive comparison (rule R2)' FROM raw_tm
UNION ALL
SELECT 'Q10', 'Records with no Violation_Type (inspections)',
       count(*) FILTER (WHERE violation_type IS NULL), count(*), 'INFO',
       'CVE3 inspection entries; stop outcome depends on all linked citation and warning records' FROM tm
UNION ALL
SELECT 'Q12', 'Stops time stamped at exactly 00:00 or 00:01',
       at_midnight, stops, 'WARN',
       'Likely default times; affects time of day patterns' FROM midnight
UNION ALL
SELECT 'Q13', 'Tickets combined into reconstructed stops',
       (SELECT count(*) FROM t_tm) - (SELECT count(*) FROM s_tm), (SELECT count(*) FROM t_tm), 'INFO',
       'Ticket count overstates stops by this amount; see stop definition (04_stops.sql)'
UNION ALL
SELECT 'Q14', 'Tickets whose rows disagree on Searched',
       count(*), (SELECT count(*) FROM t_tm), 'INFO',
       'Ticket treated as searched if any row says so'
FROM (SELECT ticket_number FROM tm GROUP BY 1 HAVING count(DISTINCT searched) > 1)
UNION ALL
SELECT 'Q15', 'Stops with no vehicle type recorded',
       count(*) FILTER (WHERE vehicle_type IS NULL), count(*), 'INFO',
       'Grouped as "Other or unknown" vehicle type' FROM s_tm
UNION ALL
SELECT 'Q16', 'Columns present in some monthly files but not others (Sep 2017 - Mar 2018)',
       drift_cols, (SELECT count(DISTINCT column_name) FROM null_profile), 'INFO',
       'Vehicle_Model (2017 files only) and Violation_Name (2018 files only); neither affects counts' FROM schema_drift
UNION ALL
SELECT 'Q18', 'Source records missing a trooper ID',
       count(*) FILTER (WHERE nullif(trim(Officer_ID), '') IS NULL), count(*),
       CASE WHEN count(*) FILTER (WHERE nullif(trim(Officer_ID), '') IS NULL) = 0 THEN 'PASS' ELSE 'WARN' END,
       'Trooper ID is required for encounter grouping and distinct trooper counts' FROM raw_tm
UNION ALL
SELECT 'Q19', 'Duplicate stop IDs in the stop table',
       count(stop_id) - count(DISTINCT stop_id), count(*),
       CASE WHEN count(stop_id) = count(DISTINCT stop_id) THEN 'PASS' ELSE 'WARN' END,
       'Counts repeated non missing stop IDs' FROM s_tm
UNION ALL
SELECT 'Q20', 'Source records without a processed stop',
       count(*) FILTER (WHERE v.source_row_id IS NULL OR x.stop_id IS NULL OR s.stop_id IS NULL), count(*),
       CASE WHEN count(*) FILTER (WHERE v.source_row_id IS NULL OR x.stop_id IS NULL OR s.stop_id IS NULL) = 0
            THEN 'PASS' ELSE 'WARN' END,
       'Trace each source row through violations, ticket_stop and stops; no source row should be lost'
FROM raw_tm r
LEFT JOIN violations v USING (source_row_id)
LEFT JOIN ticket_stop x ON v.ticket_number = x.ticket_number
LEFT JOIN stops s ON x.stop_id = s.stop_id;
