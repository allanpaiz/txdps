CREATE OR REPLACE TABLE county_month AS
SELECT
    county_name,
    month,
    stop_type,
    count(*)                                                     AS stops,
    sum(n_tickets)                                               AS tickets,
    sum(n_violation_records)                                     AS violation_records,
    sum(n_citations)                                             AS citations,
    count(*) FILTER (WHERE outcome = 'Citation')                 AS citation_stops,
    count(*) FILTER (WHERE outcome = 'Warning only')             AS warning_only_stops,
    count(*) FILTER (WHERE outcome = 'No violation recorded')    AS no_violation_stops,
    count(*) FILTER (WHERE searched)                             AS searched_stops,
    count(*) FILTER (WHERE searched AND contraband_found)        AS contraband_stops,
    count(*) FILTER (WHERE searched AND search_consent)          AS consent_searches,
    count(*) FILTER (WHERE vehicle_class = 'Truck tractor')      AS truck_tractor_stops,
    count(*) FILTER (WHERE special_program IS NOT NULL)          AS special_program_stops,
    count(*) FILTER (WHERE road_class = 'IH')                    AS interstate_stops,
    count(*) FILTER (WHERE latitude IS NOT NULL)                 AS located_stops
FROM stops
GROUP BY ALL;

CREATE OR REPLACE TABLE county_region AS
SELECT county_name, region AS dps_region, district AS dps_district
FROM (SELECT county_name, region, district,
             row_number() OVER (PARTITION BY county_name ORDER BY count(*) DESC, region, district) AS rn
      FROM stops
      WHERE month = '{TARGET_MONTH}'
      GROUP BY county_name, region, district)
WHERE rn = 1;

CREATE OR REPLACE TABLE county_troopers AS
SELECT county_name,
       month,
       coalesce(stop_type, 'All stops')            AS stop_type,
       count(DISTINCT officer_id)                  AS troopers
FROM stops
GROUP BY GROUPING SETS ((county_name, month, stop_type), (county_name, month));

CREATE OR REPLACE TABLE statewide_troopers AS
SELECT month,
       coalesce(stop_type, 'All stops')            AS stop_type,
       count(*)                                    AS stops,
       count(DISTINCT officer_id)                  AS troopers
FROM stops
GROUP BY GROUPING SETS ((month, stop_type), (month));

CREATE OR REPLACE TABLE statewide_outcome_distribution AS
SELECT stop_type, outcome,
       CASE WHEN outcome = 'Citation' THEN least(n_citations, 5) END AS citations_bucket,
       count(*) AS stops
FROM stops WHERE month = '{TARGET_MONTH}'
GROUP BY ALL
ORDER BY stop_type, outcome, citations_bucket;

CREATE OR REPLACE TABLE county_breakdown AS
WITH s AS (
    SELECT county_name, is_inspection, outcome, searched, search_consent, contraband_found,
           n_violation_records,
           race_ethnicity                                                    AS "Driver race/ethnicity",
           sex                                                               AS "Driver sex",
           vehicle_class                                                     AS "Vehicle type",
           coalesce(road_class, 'Unknown')                                   AS "Road class",
           stop_type                                                         AS "Stop type",
           outcome                                                           AS "Stop outcome",
           coalesce(special_program, 'No program')                           AS "Special program",
           CASE WHEN accident THEN 'Yes' ELSE 'No' END                       AS "Crash involved",
           CASE WHEN construction_zone THEN 'Yes' ELSE 'No' END              AS "Work zone",
           CASE WHEN driver_cdl THEN 'Yes' ELSE 'No' END                     AS "Driver holds a CDL",
           CASE WHEN race_known_prior THEN 'Yes'
                WHEN race_known_prior IS NULL THEN 'Not recorded' ELSE 'No' END AS "Race known before stop",
           CASE WHEN fugitive THEN 'Yes'
                WHEN fugitive IS NULL THEN 'Not recorded' ELSE 'No' END      AS "Fugitive",
           CASE service WHEN 'HP' THEN 'Highway patrol' WHEN 'CV' THEN 'Commercial vehicle enforcement'
                ELSE 'Other service' END                                     AS "Trooper service"
    FROM stops
    WHERE month = '{TARGET_MONTH}'
)
SELECT county_name, dimension, category,
       count(*)                                                                    AS stops,
       count(*) FILTER (WHERE is_inspection)                                       AS inspection_stops,
       count(*) FILTER (WHERE NOT is_inspection)                                   AS enforcement_stops,
       count(*) FILTER (WHERE NOT is_inspection AND outcome = 'Citation')          AS citation_stops,
       count(*) FILTER (WHERE NOT is_inspection AND searched)                      AS searched_stops,
       count(*) FILTER (WHERE NOT is_inspection AND searched AND contraband_found) AS contraband_stops,
       count(*) FILTER (WHERE NOT is_inspection AND searched AND search_consent)   AS consent_searches,
       sum(n_violation_records)                                                    AS violation_records
FROM (UNPIVOT s
      ON "Driver race/ethnicity", "Driver sex", "Vehicle type", "Road class", "Stop type", "Stop outcome",
         "Special program", "Crash involved", "Work zone", "Driver holds a CDL", "Race known before stop",
         "Fugitive", "Trooper service"
      INTO NAME dimension VALUE category)
GROUP BY ALL;

CREATE OR REPLACE TABLE statewide_searches AS
SELECT stop_type,
       count(*) FILTER (WHERE searched)                                AS searched_stops,
       count(*) FILTER (WHERE searched AND search_consent)             AS consent,
       count(*) FILTER (WHERE searched AND search_probable_cause)      AS probable_cause,
       count(*) FILTER (WHERE searched AND search_incident_to_arrest)  AS incident_to_arrest,
       count(*) FILTER (WHERE searched AND search_inventory)           AS inventory,
       count(*) FILTER (WHERE searched AND contraband_found)           AS contraband_any,
       count(*) FILTER (WHERE searched AND contraband_drugs)           AS contraband_drugs,
       count(*) FILTER (WHERE searched AND contraband_weapons)         AS contraband_weapons,
       count(*) FILTER (WHERE searched AND contraband_currency)        AS contraband_currency,
       count(*) FILTER (WHERE searched AND contraband_other)           AS contraband_other,
       count(*) FILTER (WHERE searched AND search_consent AND contraband_found)        AS consent_hits,
       count(*) FILTER (WHERE searched AND search_probable_cause AND contraband_found) AS probable_cause_hits
FROM stops
WHERE month = '{TARGET_MONTH}'
GROUP BY stop_type;

CREATE OR REPLACE TABLE violation_category_stops AS
SELECT coalesce(v.violation_category, '(category not recorded)')     AS violation_category,
       s.stop_type,
       count(DISTINCT s.stop_id)                                      AS stops,
       count(DISTINCT s.stop_id) FILTER (WHERE v.violation_type = 'Citation') AS cited_stops,
       count(*)                                                       AS violation_records,
       count(*) FILTER (WHERE v.violation_type = 'Citation')          AS citations,
       count(*) FILTER (WHERE v.violation_type = 'Warning')           AS warnings
FROM violations v
JOIN ticket_stop x USING (ticket_number)
JOIN stops s USING (stop_id)
WHERE v.month = '{TARGET_MONTH}'
GROUP BY ALL;

CREATE OR REPLACE TABLE special_program_month AS
SELECT special_program, county_name, month, count(*) AS stops
FROM stops
WHERE special_program IS NOT NULL
GROUP BY ALL;

CREATE OR REPLACE TABLE stop_locations AS
SELECT county_name, stop_type, round(latitude, 4) AS latitude, round(longitude, 4) AS longitude
FROM stops
WHERE month = '{TARGET_MONTH}' AND latitude IS NOT NULL AND longitude IS NOT NULL;
