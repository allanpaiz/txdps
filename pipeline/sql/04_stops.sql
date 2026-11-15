CREATE OR REPLACE TABLE ticket_stop AS
SELECT ticket_number,
       md5(concat_ws('|', officer_id, stop_ts, county_name,
                     coalesce(driver_race_sex, ''), coalesce(vehicle_make, ''),
                     coalesce(CAST(vehicle_year AS VARCHAR), ''), coalesce(vehicle_color, ''))) AS stop_id
FROM tickets;

CREATE OR REPLACE TABLE stops AS
SELECT
    x.stop_id,
    min(t.month)                                       AS month,
    min(t.stop_ts)                                     AS stop_ts,
    CAST(min(t.stop_ts) AS DATE)                       AS stop_date,
    min(t.county_name)                                 AS county_name,
    min(t.officer_id)                                  AS officer_id,
    min(t.service)                                     AS service,
    min(t.region)                                      AS region,
    min(t.district)                                    AS district,
    min(t.road_class)                                  AS road_class,
    min(t.route)                                       AS route,
    max(t.latitude)                                    AS latitude,
    max(t.longitude)                                   AS longitude,
    min(t.driver_race_sex)                             AS driver_race_sex,
    CASE WHEN min(t.driver_race_sex) LIKE 'Hispanic%'      THEN 'Hispanic or Latino'
         WHEN min(t.driver_race_sex) LIKE 'White%'         THEN 'White'
         WHEN min(t.driver_race_sex) LIKE 'Black%'         THEN 'Black'
         WHEN min(t.driver_race_sex) LIKE 'Asian%'         THEN 'Asian or Pacific Islander'
         WHEN min(t.driver_race_sex) LIKE 'Alaska Native%' THEN 'Alaska Native or American Indian'
         ELSE 'Other or unknown' END                   AS race_ethnicity,
    CASE WHEN min(t.driver_race_sex) LIKE '%Female' THEN 'Female'
         WHEN min(t.driver_race_sex) LIKE '%Male'   THEN 'Male'
         ELSE 'Unknown' END                            AS sex,
    min(t.vehicle_type)                                AS vehicle_type,
    CASE WHEN min(t.vehicle_type) = 'Passenger Car'                          THEN 'Passenger car'
         WHEN min(t.vehicle_type) = 'Pickup Truck'                           THEN 'Pickup truck'
         WHEN min(t.vehicle_type) IN ('SUV', 'Jeep')                         THEN 'SUV or jeep'
         WHEN min(t.vehicle_type) IN ('Van', 'Passenger Van')                THEN 'Van'
         WHEN min(t.vehicle_type) IN ('Motorcycle', 'Motor Scooter / Moped') THEN 'Motorcycle'
         WHEN min(t.vehicle_type) ILIKE '%tractor%'                          THEN 'Truck tractor'
         WHEN min(t.vehicle_type) IN ('Straight Truck, Dump Truck, Flatbed, Cement Mixer', 'Bus', 'School Bus',
                                      'Motor Coach', 'Tank', 'Utility Van (UPS, Bread Truck, etc)',
                                      'Semi-Trailer, Livestock', 'Pole-Trailer, Log', 'Full-Trailer, Refrigerator',
                                      'Dolly Converter')                     THEN 'Other truck or bus'
         ELSE 'Other or unknown' END                   AS vehicle_class,
    min(t.special_program)                             AS special_program,
    bool_or(t.ticket_type = 'CVE3')                    AS is_inspection,
    CASE WHEN bool_or(t.ticket_type = 'CVE3') THEN 'Commercial inspection'
         ELSE 'Traffic enforcement' END                AS stop_type,
    count(*)                                           AS n_tickets,
    sum(t.n_violation_records)                         AS n_violation_records,
    sum(t.n_citations)                                 AS n_citations,
    sum(t.n_warnings)                                  AS n_warnings,
    CASE WHEN sum(t.n_citations) > 0 THEN 'Citation'
         WHEN sum(t.n_warnings)  > 0 THEN 'Warning only'
         ELSE 'No violation recorded' END              AS outcome,
    bool_or(t.commercial_vehicle)                      AS commercial_vehicle,
    bool_or(t.driver_cdl)                              AS driver_cdl,
    bool_or(t.fugitive)                                AS fugitive,
    bool_or(t.race_known_prior)                        AS race_known_prior,
    bool_or(t.accident)                                AS accident,
    bool_or(t.construction_zone)                       AS construction_zone,
    bool_or(t.searched)                                AS searched,
    bool_or(t.search_consent)                          AS search_consent,
    bool_or(t.search_probable_cause)                   AS search_probable_cause,
    bool_or(t.search_incident_to_arrest)               AS search_incident_to_arrest,
    bool_or(t.search_inventory)                        AS search_inventory,
    bool_or(t.contraband_found)                        AS contraband_found,
    bool_or(t.contraband_drugs)                        AS contraband_drugs,
    bool_or(t.contraband_weapons)                      AS contraband_weapons,
    bool_or(t.contraband_currency)                     AS contraband_currency,
    bool_or(t.contraband_other)                        AS contraband_other
FROM tickets t
JOIN ticket_stop x USING (ticket_number)
GROUP BY x.stop_id;
