import config as C
import duckdb


def driver_race_known_counts():

    with duckdb.connect(str(C.DB_PATH), read_only=True) as con:
        return con.execute("""
            SELECT dimension, category,
                   count(*) FILTER (WHERE race_known_prior) AS known,
                   count(*) FILTER (WHERE race_known_prior IS NULL) AS not_recorded
            FROM (UNPIVOT (
                SELECT race_ethnicity AS "Driver race/ethnicity", sex AS "Driver sex",
                       race_known_prior FROM stops WHERE month = ?
            ) ON "Driver race/ethnicity", "Driver sex"
              INTO NAME dimension VALUE category)
            GROUP BY dimension, category
        """, [C.TARGET_MONTH]).df().set_index(["dimension", "category"])


def commercial_service_counts():

    with duckdb.connect(str(C.DB_PATH), read_only=True) as con:
        return con.execute("""
            SELECT county_name, count(*) AS cv_service_stops
            FROM stops WHERE month = ? AND service = 'CV'
            GROUP BY county_name
        """, [C.TARGET_MONTH]).df().set_index("county_name").cv_service_stops


def county_outcome_counts():

    with duckdb.connect(str(C.DB_PATH), read_only=True) as con:
        return con.execute("""
            WITH counts AS (
                SELECT county_name, stop_type, count(*) AS total,
                       count(*) FILTER (WHERE outcome = 'Warning only') AS "Warning only",
                       count(*) FILTER (WHERE outcome = 'Citation') AS "Citation",
                       count(*) FILTER (WHERE outcome = 'No violation recorded') AS "No violation recorded",
                       count(*) FILTER (WHERE searched) AS "All searches",
                       count(*) FILTER (WHERE searched) AS searches,
                       count(*) FILTER (WHERE searched AND search_consent) AS "Consent",
                       count(*) FILTER (WHERE searched AND contraband_found) AS "Contraband found"
                FROM stops WHERE month = ? GROUP BY county_name, stop_type
            )
            SELECT county_name, stop_type, category, stops,
                   CASE WHEN category IN ('Consent', 'Contraband found')
                        THEN searches ELSE total END AS denominator
            FROM (UNPIVOT counts ON "Warning only", "Citation", "No violation recorded",
                  "All searches", "Consent", "Contraband found" INTO NAME category VALUE stops)
        """, [C.TARGET_MONTH]).df()


def inspection_leaders(df, n=15):

    return df.sort_values(["inspection_stops", "county_name"], ascending=[False, True]).head(n)


def county_speeding_counts():

    with duckdb.connect(str(C.DB_PATH), read_only=True) as con:
        return con.execute("""
            SELECT s.county_name, count(DISTINCT s.stop_id) AS speeding_stops
            FROM violations v JOIN ticket_stop x USING (ticket_number)
            JOIN stops s USING (stop_id)
            WHERE v.month = ? AND v.violation_category = 'SPEEDING - OVER LIMITS'
            GROUP BY s.county_name
        """, [C.TARGET_MONTH]).df()


def search_fugitive_summary():

    with duckdb.connect(str(C.DB_PATH), read_only=True) as con:
        return con.execute("""
            WITH flagged AS (
                SELECT county_name, is_inspection, outcome,
                       fugitive AS "Fugitive identified",
                       searched AS "Search conducted",
                       (searched AND contraband_found) AS "Contraband found"
                FROM stops WHERE month = ?
            ), counts AS (
                SELECT category, county_name, count(*) AS stops,
                       count(*) FILTER (WHERE is_inspection) AS inspections,
                       count(*) FILTER (WHERE NOT is_inspection) AS enforcement,
                       count(*) FILTER (WHERE NOT is_inspection AND outcome = 'Citation') AS cited
                FROM (UNPIVOT flagged
                      ON "Fugitive identified", "Search conducted", "Contraband found"
                      INTO NAME category VALUE present)
                WHERE present GROUP BY category, county_name
            )
            SELECT category, sum(stops) AS stops, sum(inspections) AS inspections,
                   sum(enforcement) AS enforcement, sum(cited) AS cited,
                   first(county_name ORDER BY stops DESC, county_name) AS leading_county,
                   max(stops) AS leading_stops
            FROM counts GROUP BY category
        """, [C.TARGET_MONTH]).df().set_index("category")


def february_changes(df):

    out = df.copy()
    out["feb_per_day"] = out.prior_month_stops / C.DAYS_IN_MONTH[C.PRIOR_MONTH]
    out["mar_per_day"] = out.stops / C.DAYS_IN_MONTH[C.TARGET_MONTH]
    out["change_per_day"] = out.mar_per_day - out.feb_per_day
    out["change_pct"] = 100 * out.change_per_day / out.feb_per_day.where(out.feb_per_day > 0)
    baseline_days = sum(C.DAYS_IN_MONTH[m] for m in C.BASELINE_MONTHS)
    out["baseline_per_day"] = out.baseline_stops_6mo / baseline_days
    out["baseline_change_per_day"] = out.mar_per_day - out.baseline_per_day
    out["baseline_change_pct"] = 100 * out.baseline_change_per_day / out.baseline_per_day.where(out.baseline_per_day > 0)
    return out


def program_monthly(programs):

    p = programs.pivot_table(index="special_program", columns="month", values="stops",
                             aggfunc="sum", fill_value=0).reindex(columns=C.ALL_MONTHS, fill_value=0)
    p = p.loc[p.sum(axis=1).sort_values(ascending=False).index]
    return p[p.sum(axis=1) >= 20]


def violation_county_leaders():

    with duckdb.connect(str(C.DB_PATH), read_only=True) as con:
        counts = con.execute("""
            SELECT coalesce(v.violation_category, '(category not recorded)') AS category,
                   s.county_name, count(DISTINCT s.stop_id) AS stops
            FROM violations v JOIN ticket_stop x USING (ticket_number)
            JOIN stops s USING (stop_id)
            WHERE v.month = ?
            GROUP BY ALL
        """, [C.TARGET_MONTH]).df()
    return counts.sort_values(["category", "stops", "county_name"],
                              ascending=[True, False, True]).drop_duplicates("category")
