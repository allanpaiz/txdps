import json
from datetime import datetime
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pandas as pd
from scipy import optimize, special, stats

import config as C

ENF, INSP = "Traffic enforcement", "Commercial inspection"
MONTH_LABELS = {m: pd.Timestamp(m + "-01").strftime("%b %Y") for m in C.ALL_MONTHS}
COUNT_COLS = ["stops", "tickets", "violation_records", "citations", "citation_stops", "warning_only_stops",
              "no_violation_stops", "searched_stops", "contraband_stops", "consent_searches", "truck_tractor_stops",
              "special_program_stops", "interstate_stops", "located_stops"]
SIZE_BANDS = [(5000, "5,000 or more"), (2500, "2,500 - 4,999"), (1000, "1,000 - 2,499"),
              (500, "500 - 999"), (100, "100 - 499"), (0, "Fewer than 100")]


def load(con):
    tables = ["county_month", "county_reference", "county_region", "county_troopers", "statewide_troopers",
              "county_breakdown", "statewide_outcome_distribution", "statewide_searches",
              "violation_category_stops", "special_program_month",
              "data_quality"]
    return {t: con.sql(f"SELECT * FROM {t}").df() for t in tables}


def wilson_ci(k, n, z=1.96):

    k, n = np.asarray(k, float), np.asarray(n, float)
    with np.errstate(invalid="ignore", divide="ignore"):
        p = k / n
        den = 1 + z**2 / n
        centre = (p + z**2 / (2 * n)) / den
        half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / den
    return centre - half, centre + half


def fit_poisson_gamma(observed, expected):


    O, E = np.asarray(observed, float), np.asarray(expected, float)

    def neg_loglik(log_ab):
        a, b = np.exp(log_ab)
        return -np.sum(special.gammaln(O + a) - special.gammaln(a) - special.gammaln(O + 1)
                       + a * np.log(b / (b + E)) + O * np.log(E / (b + E)))

    res = optimize.minimize(neg_loglik, x0=[0.0, 0.0], method="Nelder-Mead",
                            options={"xatol": 1e-8, "fatol": 1e-8, "maxiter": 5000})
    if not res.success:
        raise RuntimeError(f"Empirical Bayes fit failed: {res.message}")
    a, b = np.exp(res.x)
    post_a, post_b = a + O, b + E
    return {"a": a, "b": b,
            "mean": post_a / post_b,
            "lo": stats.gamma.ppf(0.025, post_a, scale=1 / post_b),
            "hi": stats.gamma.ppf(0.975, post_a, scale=1 / post_b),
            "shrinkage": b / (b + E)}


def quantile_breaks(values, k=C.QUANTILE_CLASSES):

    values = pd.Series(values).dropna()
    qs = np.quantile(values, np.linspace(0, 1, k + 1)[1:-1])
    for sig in (2, 3, 4):
        out = sorted(set(float(f"{q:.{sig}g}") for q in qs))
        if len(out) == len(qs):
            break

    return [b for b in out if b > values.min()]


def class_counts(values, breaks):

    v = pd.Series(values).dropna().to_numpy()
    idx = np.digitize(v, breaks, right=False)
    return [int((idx == i).sum()) for i in range(len(breaks) + 1)]


def gini(values):

    s = np.sort(np.asarray(values, float))
    lorenz = np.cumsum(s) / s.sum()
    return float(1 - 2 * np.trapezoid(np.r_[0, lorenz], dx=1 / len(s)))


def pct_change(new, old, ok):
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(ok, 100 * (new / old - 1), np.nan)


def build_county_table(d):
    cm, ref = d["county_month"], d["county_reference"]
    days = C.DAYS_IN_MONTH[C.TARGET_MONTH]
    tm = cm[cm.month == C.TARGET_MONTH]
    all_ = tm.groupby("county_name")[COUNT_COLS].sum()
    enf = tm[tm.stop_type == ENF].set_index("county_name")[COUNT_COLS].add_prefix("enf_")
    insp = tm[tm.stop_type == INSP].set_index("county_name")[["stops", "violation_records"]].add_prefix("insp_")

    region = d["county_region"].assign(region_name=lambda x: x.dps_region.map(C.DPS_REGIONS))
    df = (ref.merge(region, on="county_name", how="left")
             .merge(all_, left_on="county_name", right_index=True, how="left")
             .merge(enf, left_on="county_name", right_index=True, how="left")
             .merge(insp, left_on="county_name", right_index=True, how="left"))
    num = [c for c in df.columns if c in COUNT_COLS or c.startswith(("enf_", "insp_"))]
    df[num] = df[num].fillna(0)
    ints = num
    df[ints] = df[ints].astype(int)


    total = df.stops.sum()
    df["share_pct"] = 100 * df.stops / total
    df["rank"] = df.stops.rank(ascending=False, method="min").astype(int)
    df = df.sort_values(["rank", "county_name"]).reset_index(drop=True)
    df["cum_share_pct"] = df.share_pct.cumsum()
    df["stops_per_day"] = df.stops / days
    lower_edges = [b for b, _ in SIZE_BANDS[::-1]]
    df["size_band"] = pd.cut(df.stops, lower_edges + [np.inf], right=False,
                             labels=[label for _, label in SIZE_BANDS[::-1]]).astype(str)
    df["inspection_stops"] = df.insp_stops
    df["inspection_share_pct"] = 100 * df.inspection_stops / df.stops
    df["truck_tractor_share_pct"] = 100 * df.truck_tractor_stops / df.stops
    df["truck_vmt_month_millions"] = df.dtrkvmt_on_system * days / 1e6
    df["missing_coords_pct"] = 100 * (1 - df.located_stops / df.stops)
    df["tickets_per_stop_pct_over"] = 100 * (df.tickets / df.stops - 1)
    df["inspections_per_m_truck_vmt"] = df.inspection_stops / df.truck_vmt_month_millions


    by_month = cm.groupby(["county_name", "month"]).stops.sum().unstack(fill_value=0).reindex(columns=C.ALL_MONTHS, fill_value=0)
    for m in C.ALL_MONTHS:
        df[f"stops_{m.replace('-', '_')}"] = df.county_name.map(by_month[m]).fillna(0).astype(int)
    prior = df[f"stops_{C.PRIOR_MONTH.replace('-', '_')}"]
    df["prior_month_stops"] = prior
    df["prior_month_stops_per_day"] = prior / C.DAYS_IN_MONTH[C.PRIOR_MONTH]
    base_days = sum(C.DAYS_IN_MONTH[m] for m in C.BASELINE_MONTHS)
    df["baseline_stops_6mo"] = sum(df[f"stops_{m.replace('-', '_')}"] for m in C.BASELINE_MONTHS)
    df["baseline_stops_per_day"] = df.baseline_stops_6mo / base_days
    ok_prior = (df.stops >= C.MIN_STOPS_FOR_CHANGE) & (df.prior_month_stops_per_day * days >= C.MIN_STOPS_FOR_CHANGE)
    ok_base = (df.stops >= C.MIN_STOPS_FOR_CHANGE) & (df.baseline_stops_per_day * days >= C.MIN_STOPS_FOR_CHANGE)
    df["change_per_day_vs_prior_month"] = df.stops_per_day - df.prior_month_stops_per_day
    df["change_per_day_vs_6mo"] = df.stops_per_day - df.baseline_stops_per_day
    df["pct_change_vs_prior_month"] = pct_change(df.stops_per_day, df.prior_month_stops_per_day, ok_prior)
    df["pct_change_vs_6mo"] = pct_change(df.stops_per_day, df.baseline_stops_per_day, ok_base)


    ok = (df.enf_stops >= C.MIN_STOPS_FOR_RATE).to_numpy()
    rate = lambda k, n, mask: np.where(mask, 100 * k / n.where(n > 0), np.nan)
    df["citation_rate_pct"] = rate(df.enf_citation_stops, df.enf_stops, ok)
    df["warning_only_rate_pct"] = rate(df.enf_warning_only_stops, df.enf_stops, ok)
    df["search_rate_pct"] = rate(df.enf_searched_stops, df.enf_stops, ok)
    df["violations_per_stop"] = np.where(ok, df.enf_violation_records / df.enf_stops.where(df.enf_stops > 0), np.nan)
    df["interstate_share_pct"] = rate(df.enf_interstate_stops, df.enf_stops, ok)
    hit_ok = (df.enf_searched_stops >= C.MIN_SEARCHES_FOR_HIT_RATE).to_numpy()
    lo, hi = wilson_ci(df.enf_contraband_stops, df.enf_searched_stops)
    df["hit_rate_pct"] = rate(df.enf_contraband_stops, df.enf_searched_stops, hit_ok)
    df["hit_rate_lo_pct"] = np.where(hit_ok, 100 * lo, np.nan)
    df["hit_rate_hi_pct"] = np.where(hit_ok, 100 * hi, np.nan)
    df["consent_share_pct"] = rate(df.enf_consent_searches, df.enf_searched_stops, hit_ok)

    tr = d["county_troopers"]
    tr = tr[(tr.stop_type == ENF) & (tr.month == C.TARGET_MONTH)].set_index("county_name")
    df["troopers"] = df.county_name.map(tr.troopers).fillna(0).astype(int)
    df["vmt_month_millions"] = df.dvmt_on_system * days / 1e6
    df["stops_per_10k_pop"] = 1e4 * df.enf_stops / df.pop_2018
    df["stops_per_m_vmt"] = df.enf_stops / df.vmt_month_millions
    df["stops_per_100_road_miles"] = 100 * df.enf_stops / df.centerline_miles_on_system


    enf_total = df.enf_stops.sum()
    df["expected_stops"] = enf_total * df.dvmt_on_system / df.dvmt_on_system.sum()
    df["sar_raw"] = df.enf_stops / df.expected_stops
    eb = fit_poisson_gamma(df.enf_stops, df.expected_stops)
    df["sar"], df["sar_lo"], df["sar_hi"], df["sar_shrinkage"] = eb["mean"], eb["lo"], eb["hi"], eb["shrinkage"]
    df["sar_signal"] = np.select([df.sar_lo > 1, df.sar_hi < 1], ["Above expected", "Below expected"],
                                 "Not distinguishable from expected")
    df["sar_all_stops_raw"] = df.stops / (total * df.dvmt_on_system / df.dvmt_on_system.sum())


    df["enf_share_pct"] = 100 * df.enf_stops / enf_total
    df["enf_rank"] = df.enf_stops.rank(ascending=False, method="min").astype(int)
    state_citation_rate = 100 * df.enf_citation_stops.sum() / enf_total
    df["quadrant"] = np.select(
        [~ok, (df.sar > 1) & (df.citation_rate_pct > state_citation_rate),
         (df.sar > 1), (df.citation_rate_pct > state_citation_rate)],
        ["", "More stops, higher citation share", "More stops, lower citation share",
         "Fewer stops, higher citation share"], "Fewer stops, lower citation share")
    df["citation_rate_std_pct"] = road_standardized_citation_rate(d["county_breakdown"], df, ok)
    return df, eb


def road_standardized_citation_rate(bd, df, ok):


    r = bd[bd.dimension == "Road class"].copy()
    state = r.groupby("category")[["enforcement_stops", "citation_stops"]].sum()
    w = state.enforcement_stops / state.enforcement_stops.sum()
    p_state = state.citation_stops / state.enforcement_stops
    r["p"] = np.where(r.enforcement_stops >= 10, r.citation_stops / r.enforcement_stops.where(r.enforcement_stops > 0),
                      r.category.map(p_state))
    p = r.pivot_table(index="county_name", columns="category", values="p").reindex(columns=w.index)
    p = p.fillna(pd.DataFrame({k: [p_state[k]] * len(p) for k in w.index}, index=p.index))
    std = 100 * (p * w).sum(axis=1)
    return np.where(ok, df.county_name.map(std), np.nan)


def statewide_monthly(cm, st):
    m = cm.pivot_table(index="month", columns="stop_type", values="stops", aggfunc="sum").reindex(C.ALL_MONTHS)
    td = st[st.stop_type == "All stops"].set_index("month").reindex(C.ALL_MONTHS)
    out = pd.DataFrame({"month": C.ALL_MONTHS, "label": [MONTH_LABELS[x] for x in C.ALL_MONTHS],
                        "days": [C.DAYS_IN_MONTH[x] for x in C.ALL_MONTHS],
                        "stops": m.sum(axis=1).to_numpy().astype(int),
                        "enforcement_stops": m[ENF].to_numpy().astype(int),
                        "inspection_stops": m[INSP].to_numpy().astype(int),
                        "troopers": td.troopers.to_numpy().astype(int)})
    out["stops_per_day"] = out.stops / out.days
    base = out[out.month.isin(C.BASELINE_MONTHS)]
    base_per_day = base.stops.sum() / base.days.sum()
    out["index_vs_baseline"] = 100 * out.stops_per_day / base_per_day
    return out, base_per_day


def statewide_breakdown(bd):

    b = bd
    cols = ["stops", "inspection_stops", "enforcement_stops", "citation_stops", "searched_stops", "contraband_stops",
            "consent_searches", "violation_records"]
    state = b.groupby(["dimension", "category"])[cols].sum().reset_index()
    state["share_pct"] = 100 * state.stops / state.groupby("dimension").stops.transform("sum")
    with np.errstate(invalid="ignore", divide="ignore"):
        state["citation_rate_pct"] = 100 * state.citation_stops / state.enforcement_stops
        state["search_rate_pct"] = 100 * state.searched_stops / state.enforcement_stops
        state["hit_rate_pct"] = 100 * state.contraband_stops / state.searched_stops
        state["consent_share_pct"] = 100 * state.consent_searches / state.searched_stops
        state["inspection_share_pct"] = 100 * state.inspection_stops / state.stops
        state["violations_per_stop"] = state.violation_records / state.stops
    return state


def normalization_agreement(df):

    b = df[df.enf_stops >= C.MIN_STOPS_FOR_RATE]
    cols = {"stops_per_10k_pop": "Per 10,000 residents", "stops_per_m_vmt": "Per million vehicle miles",
            "stops_per_100_road_miles": "Per 100 road-miles"}
    rows = []
    keys = list(cols)
    for i, a in enumerate(keys):
        for c in keys[i + 1:]:
            rows.append({"a": cols[a], "b": cols[c], "rho": float(stats.spearmanr(b[a], b[c])[0]),
                         "top10_overlap": len(set(b.nlargest(10, a).county_name) & set(b.nlargest(10, c).county_name))})
    return pd.DataFrame(rows), {k: b.nlargest(10, k).county_name.tolist() for k in keys}


def statewide_summary(df, d, eb, monthly, base_per_day, state_bd):
    total, enf_total = int(df.stops.sum()), int(df.enf_stops.sum())
    days = C.DAYS_IN_MONTH[C.TARGET_MONTH]
    q = d["data_quality"].set_index("check_id")
    st = d["statewide_troopers"]
    tr = st[st.month == C.TARGET_MONTH].set_index("stop_type")
    srch = d["statewide_searches"].set_index("stop_type").loc[ENF]
    mo = monthly.set_index("month")
    big = df[df.enf_stops >= C.MIN_STOPS_FOR_RATE]

    def counties_for_share(p):
        return int((df.cum_share_pct < p).sum() + 1)

    top10 = lambda frame, col: set(frame.nlargest(10, col).county_name)
    chg = pd.Series(df.pct_change_vs_6mo).dropna()
    chg_prior = pd.Series(df.pct_change_vs_prior_month).dropna()
    race = state_bd[state_bd.dimension == "Driver race/ethnicity"].set_index("category")
    return {
        "generated": datetime.now(ZoneInfo("America/New_York")).date().isoformat(),
        "target_month": C.TARGET_MONTH, "target_month_label": MONTH_LABELS[C.TARGET_MONTH],
        "prior_month_label": MONTH_LABELS[C.PRIOR_MONTH],

        "stops": total, "tickets": int(df.tickets.sum()), "violation_records": int(df.violation_records.sum()),
        "citations": int(df.citations.sum()), "counties_with_stops": int((df.stops > 0).sum()),
        "stops_per_day": total / days, "tickets_merged": int(q.loc["Q13", "value"]),
        "violations_per_stop": df.violation_records.sum() / total, "tickets_per_stop": df.tickets.sum() / total,
        "inspection_stops": int(df.inspection_stops.sum()), "enforcement_stops": enf_total,
        "inspection_share_pct": 100 * df.inspection_stops.sum() / total,
        "inspection_violations_per_stop": df.insp_violation_records.sum() / df.inspection_stops.sum(),
        "enforcement_violations_per_stop": df.enf_violation_records.sum() / enf_total,
        "truck_tractor_stops": int(df.truck_tractor_stops.sum()),
        "troopers": int(tr.loc["All stops", "troopers"]),
        "troopers_enforcement": int(tr.loc[ENF, "troopers"]),
        "troopers_inspection": int(tr.loc[INSP, "troopers"]),
        "county_quantiles": {k: float(v) for k, v in df.stops.quantile([0.1, 0.25, 0.5, 0.75, 0.9]).items()},
        "median_county_stops": float(df.stops.median()), "mean_county_stops": float(df.stops.mean()),
        "min_county": {"name": df.loc[df.stops.idxmin(), "county_name"], "stops": int(df.stops.min())},
        "max_county": {"name": df.loc[df.stops.idxmax(), "county_name"], "stops": int(df.stops.max())},
        "counties_under_100": int((df.stops < 100).sum()),
        "missing_coords_by_county": {
            "median": float(big.missing_coords_pct.median()),
            "min": {"name": big.loc[big.missing_coords_pct.idxmin(), "county_name"], "value": float(big.missing_coords_pct.min())},
            "max": {"name": big.loc[big.missing_coords_pct.idxmax(), "county_name"], "value": float(big.missing_coords_pct.max())},
            "over_50": int((big.missing_coords_pct > 50).sum()), "over_25": int((big.missing_coords_pct > 25).sum()),
            "counties": int(len(big))},
        "rollup_by_county": {
            "max": {"name": df.loc[df.tickets_per_stop_pct_over.idxmax(), "county_name"],
                    "value": float(df.tickets_per_stop_pct_over.max())},
            "median": float(df.tickets_per_stop_pct_over.median()),
            "over_5": int((df.tickets_per_stop_pct_over > 5).sum())},
        "top_shares_pct": {str(k): float(df.share_pct.head(k).sum()) for k in (1, 5, 10, 25, 40, 50, 100)},
        "counties_for_half": counties_for_share(50), "counties_for_80": counties_for_share(80),
        "bottom_half_share_pct": float(df.share_pct.tail(127).sum()),
        "gini": gini(df.stops),
        "size_bands": (df.groupby("size_band", observed=True).agg(counties=("county_name", "size"), stops=("stops", "sum"))
                         .reindex([l for _, l in SIZE_BANDS]).fillna(0).astype(int)
                         .assign(share_pct=lambda x: 100 * x.stops / total).reset_index().to_dict(orient="records")),

        "baseline_stops_per_day": base_per_day,
        "prior_month_stops_per_day": float(mo.loc[C.PRIOR_MONTH, "stops_per_day"]),
        "pct_change_vs_6mo": 100 * (total / days / base_per_day - 1),
        "pct_change_vs_prior_month": 100 * (total / days / mo.loc[C.PRIOR_MONTH, "stops_per_day"] - 1),
        "monthly": monthly.round(3).to_dict(orient="records"),
        "change_bands_6mo": {"up_15": int((chg >= 15).sum()), "up_5_15": int(((chg >= 5) & (chg < 15)).sum()),
                             "flat": int(((chg > -5) & (chg < 5)).sum()), "down_5_15": int(((chg <= -5) & (chg > -15)).sum()),
                             "down_15": int((chg <= -15).sum()), "suppressed": int(len(df) - chg.size)},
        "counties_up_vs_prior": int((chg_prior > 0).sum()), "counties_down_vs_prior": int((chg_prior < 0).sum()),
        "counties_up_vs_6mo": int((chg > 0).sum()), "counties_down_vs_6mo": int((chg < 0).sum()),

        "citation_rate_pct": 100 * df.enf_citation_stops.sum() / enf_total,
        "warning_only_rate_pct": 100 * df.enf_warning_only_stops.sum() / enf_total,
        "citation_rate_all_pct": 100 * df.citation_stops.sum() / total,
        "no_violation_inspections": int(df.no_violation_stops.sum()),
        "inspection_citation_rate_pct": 100 * (df.citation_stops.sum() - df.enf_citation_stops.sum()) / df.inspection_stops.sum(),
        "search_rate_pct": 100 * srch.searched_stops / enf_total,
        "searches": int(srch.searched_stops), "searches_with_contraband": int(srch.contraband_any),
        "hit_rate_pct": 100 * srch.contraband_any / srch.searched_stops,
        "consent_searches": int(srch.consent), "probable_cause_searches": int(srch.probable_cause),
        "consent_hit_rate_pct": 100 * srch.consent_hits / srch.consent,
        "probable_cause_hit_rate_pct": 100 * srch.probable_cause_hits / srch.probable_cause,
        "rho_citation_raw_vs_road_std": float(stats.spearmanr(big.citation_rate_pct, big.citation_rate_std_pct)[0]),
        "max_road_std_shift_pts": float((big.citation_rate_std_pct - big.citation_rate_pct).abs().max()),

        "stops_per_10k_pop": 1e4 * enf_total / df.pop_2018.sum(),
        "stops_per_m_vmt": enf_total / df.vmt_month_millions.sum(),
        "stops_per_100_road_miles": 100 * enf_total / df.centerline_miles_on_system.sum(),
        "vmt_month_billions": df.vmt_month_millions.sum() / 1e3,
        "state_population": int(df.pop_2018.sum()),
        "log_stops_vs_log_vmt_r": float(stats.pearsonr(np.log(df.enf_stops.clip(lower=1)), np.log(df.dvmt_on_system))[0]),
        "eb_prior": {"a": float(eb["a"]), "b": float(eb["b"]), "prior_mean": float(eb["a"] / eb["b"]),
                     "prior_cv": float(1 / np.sqrt(eb["a"]))},
        "sar_counts": df.sar_signal.value_counts().to_dict(),
        "sar_ge_2": int((df.sar >= 2).sum()), "sar_le_half": int((df.sar <= 0.5).sum()),
        "rho_sar_eb_vs_raw": float(stats.spearmanr(df.sar, df.sar_raw)[0]),
        "rho_sar_enf_vs_all": float(stats.spearmanr(df.sar_raw, df.sar_all_stops_raw)[0]),
        "rho_stops_all_vs_enf": float(stats.spearmanr(df.stops, df.enf_stops)[0]),
        "top10_overlap_all_vs_enf": len(top10(df, "stops") & top10(df, "enf_stops")),
        "rho_stops_vs_tickets": float(stats.spearmanr(df.stops, df.tickets)[0]),
        "rho_stops_vs_violation_records": float(stats.spearmanr(df.stops, df.violation_records)[0]),
        "race_share_pct": race.share_pct.round(3).to_dict(),
        "outcome_distribution": d["statewide_outcome_distribution"].to_dict(orient="records"),
        "rho_sar_vs_citation": float(stats.spearmanr(big.sar, big.citation_rate_pct)[0]),
        "quadrants": big.groupby("quadrant").agg(counties=("county_name", "size"),
                     stops=("enf_stops", "sum")).reset_index().to_dict(orient="records"),
        "official_2018": C.OFFICIAL_2018,
        "q1_2018_stops": int(mo.loc[["2018-01", "2018-02", "2018-03"], "stops"].sum()),
        "q1_share_of_official_annual_pct": 100 * mo.loc[["2018-01", "2018-02", "2018-03"], "stops"].sum() / C.OFFICIAL_2018["total_stops"],
    }


def metric_definitions(df):
    seq, div = "sequential", "diverging"
    ratio_breaks, change_breaks = [0.33, 0.5, 0.8, 1.25, 2, 3], [-30, -15, -5, 5, 15, 30]
    excl = "Traffic enforcement stops (commercial vehicle inspections excluded)."

    def m(key, label, group, fmt, scale, description, caution="", breaks=None):
        values = df[key]
        b = breaks if breaks is not None else quantile_breaks(values)
        return {"key": key, "label": label, "group": group, "format": fmt, "scale": scale, "breaks": b,
                "counts": class_counts(values, b), "description": description, "caution": caution}

    small = f"Hidden for counties with fewer than {C.MIN_STOPS_FOR_RATE} traffic enforcement stops."
    buttons = ["All", "No Inspections", "Only Inspections", "vs. February", "vs. Last 6 Mo.",
               "10k Residents", "Vehicle Miles", "vs. Expected", "Citations", "Search", "Contraband"]
    metrics = [
        m("stops", "Traffic stops", "Volume", "int", seq,
          "All THP traffic stops recorded in the county in March 2018, including commercial vehicle inspections."),
        m("enf_stops", "Stops excl. commercial inspections", "Volume", "int", seq,
          "Traffic enforcement stops: every stop except commercial vehicle inspections (CVE3 reports)."),
        m("inspection_stops", "Commercial vehicle inspections", "Volume", "int", seq,
          "Stops that included a commercial vehicle inspection report (CVE3), mostly of truck tractors.",
          "Inspections concentrate near ports of entry and inspection sites."),
        m("pct_change_vs_prior_month", "Change vs. February", "Trend", "pct_signed", div,
          "March stops per day compared with February 2018 stops per day.",
          f"Counties with less than {C.MIN_STOPS_FOR_CHANGE} stops ommitted", change_breaks),
        m("pct_change_vs_6mo", "Change vs. Sep-Feb average", "Trend", "pct_signed", div,
          "March stops per day compared with the September 2017 - February 2018 average.",
          f"Counties with less than {C.MIN_STOPS_FOR_CHANGE} stops ommitted", change_breaks),
        m("stops_per_10k_pop", "Per 10,000 residents", "Normalized", "dec1", seq,
          f"{excl} Divided by the county's 2018 population.",
          "Rural counties crossed by interstates rank high."),
        m("stops_per_m_vmt", "Per million vehicle miles", "Normalized", "dec1", seq,
          f"{excl} Divided by March vehicle miles traveled on state highways (TxDOT 2018 daily VMT x 31)."),
        m("sar", "Stops vs. traffic expectation", "Normalized", "ratio", div,
          "Observed / expected traffic enforcement stops, where expected = statewide stops x the county's share of "
          "state highway vehicle miles. 1.0 = as expected. Empirical Bayes estimate with 95% interval.",
          "Describes where enforcement concentrates relative to traffic.", ratio_breaks),
        m("citation_rate_pct", "Stops with a citation", "Outcomes", "pct", seq,
          "Share of traffic enforcement stops with at least one citation.", small),
        m("search_rate_pct", "Stops with a search", "Outcomes", "pct", seq,
          "Share of traffic enforcement stops with a vehicle search (any type).", small),
        m("hit_rate_pct", "Searches finding contraband", "Outcomes", "pct", seq,
          "Share of searches in which contraband was found.",
          f"Hidden for counties with fewer than {C.MIN_SEARCHES_FOR_HIT_RATE} searches."),
    ]

    return [dict(metric, button=button) for metric, button in zip(metrics, buttons, strict=True)]


SOURCES = [
    {"name": "Texas DPS, THP high-value data sets (violation extracts, Sep 2017 - Mar 2018)",
     "url": "https://www.dps.texas.gov/section/highway-patrol/texas-highway-patrol-high-value-data-sets"},
    {"name": "TxDOT 2018 Roadway Inventory (vehicle miles, interstates)", "url": "https://www.txdot.gov/data-maps/roadway-inventory.html"},
    {"name": "TxDOT county boundaries", "url": "https://gis-txdot.opendata.arcgis.com/datasets/TXDOT::texas-county-boundaries-detailed"},
    {"name": "U.S. Census Bureau 2018 population estimates",
     "url": "https://www.census.gov/data/developers/data-sets/popest-popproj/popest/2018.html"},
]

PANEL_DIMENSIONS = {"Driver race/ethnicity": "race", "Stop outcome": "outcome"}


def clean(v, nd=3):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (np.floating, float)):
        return round(float(v), nd)
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


def dashboard_payload(df, summary, metrics, state_bd, bd):
    county_mix = {}
    for dim, key in PANEL_DIMENSIONS.items():
        t = bd[bd.dimension == dim].pivot_table(index="county_name", columns="category", values="stops", fill_value=0)
        county_mix[key] = t
    counties = []
    keep_float = ["share_pct", "stops_per_day", "inspection_share_pct", "pct_change_vs_prior_month", "pct_change_vs_6mo",
                  "stops_per_10k_pop", "stops_per_m_vmt", "vmt_month_millions", "sar",
                  "citation_rate_pct", "search_rate_pct", "hit_rate_pct"]
    keep_int = ["rank", "stops", "tickets", "enf_stops", "inspection_stops", "pop_2018",
                "warning_only_stops", "no_violation_stops"]
    for r in df.itertuples():
        c = {"fips": r.fips, "name": r.county_name, "region": r.region_name if isinstance(r.region_name, str) else None,
             "district": r.dps_district if isinstance(r.dps_district, str) else None, "sar_signal": r.sar_signal}
        c.update({k: clean(getattr(r, k), 6)
                  for k in keep_float})
        c.update({k: int(getattr(r, k)) for k in keep_int})
        c["monthly"] = [int(getattr(r, f"stops_{m.replace('-', '_')}")) for m in C.ALL_MONTHS]
        c["mix"] = {key: {cat: int(v) for cat, v in t.loc[r.county_name].items() if v > 0} if r.county_name in t.index else {}
                    for key, t in county_mix.items()}
        counties.append(c)

    def state_mix(dim):
        t = state_bd[state_bd.dimension == dim]
        return {r.category: int(r.stops) for r in t.itertuples()}

    s = summary
    keep = ["generated", "target_month_label", "prior_month_label", "stops", "tickets", "violation_records",
            "counties_with_stops", "stops_per_day", "baseline_stops_per_day", "prior_month_stops_per_day",
            "pct_change_vs_6mo", "pct_change_vs_prior_month", "inspection_stops", "enforcement_stops",
            "inspection_share_pct", "troopers", "citation_rate_pct", "search_rate_pct", "hit_rate_pct", "median_county_stops",
            "stops_per_10k_pop", "stops_per_m_vmt", "top_shares_pct", "counties_for_half"]
    statewide = {**{k: s[k] for k in keep},
                 "monthly": [int(x["stops"]) for x in s["monthly"]],
                 "mix": {key: state_mix(dim) for dim, key in PANEL_DIMENSIONS.items()}}
    return {
        "palette": C.PALETTE,
        "summary": statewide,
        "months": C.ALL_MONTHS,
        "month_labels": [MONTH_LABELS[m] for m in C.ALL_MONTHS],
        "month_days": [C.DAYS_IN_MONTH[m] for m in C.ALL_MONTHS],
        "metrics": metrics,
        "sources": SOURCES,
        "counties": counties,
    }


def main():
    C.OUTPUTS.mkdir(exist_ok=True)
    with duckdb.connect(str(C.DB_PATH), read_only=True) as con:
        d = load(con)

    df, eb = build_county_table(d)
    monthly, base_per_day = statewide_monthly(d["county_month"], d["statewide_troopers"])
    state_bd = statewide_breakdown(d["county_breakdown"])
    summary = statewide_summary(df, d, eb, monthly, base_per_day, state_bd)
    norm_agree, norm_top10 = normalization_agreement(df)
    summary["normalization_top10"] = norm_top10
    metrics = metric_definitions(df)


    out = C.OUTPUTS
    df.to_csv(out / f"county_metrics_{C.TARGET_MONTH}.csv", index=False, float_format="%.4f")
    d["county_month"].merge(d["county_reference"][["county_name", "fips"]], on="county_name")\
        .sort_values(["county_name", "month", "stop_type"]).to_csv(out / "county_month.csv", index=False)
    d["county_breakdown"].sort_values(["county_name", "dimension", "category"]).to_csv(out / f"county_breakdown_{C.TARGET_MONTH}.csv", index=False)
    state_bd.to_csv(out / f"statewide_breakdown_{C.TARGET_MONTH}.csv", index=False, float_format="%.4f")
    norm_agree.to_csv(out / f"normalization_agreement_{C.TARGET_MONTH}.csv", index=False, float_format="%.4f")
    d["data_quality"].to_csv(out / "data_quality.csv", index=False)
    d["violation_category_stops"].sort_values(["stop_type", "stops", "violation_category"], ascending=[True, False, True])\
        .to_csv(out / f"violation_categories_{C.TARGET_MONTH}.csv", index=False)
    d["special_program_month"].sort_values(["special_program", "county_name", "month"]).to_csv(out / "special_program_month.csv", index=False)
    d["statewide_searches"].sort_values("stop_type").to_csv(out / f"statewide_searches_{C.TARGET_MONTH}.csv", index=False)
    (out / "statewide_summary.json").write_text(json.dumps(summary, indent=2, default=float))

    C.SITE_DATA.mkdir(parents=True, exist_ok=True)
    payload = dashboard_payload(df, summary, metrics, state_bd, d["county_breakdown"])
    (C.SITE_DATA / "dashboard.json").write_text(json.dumps(payload, separators=(",", ":")))

    s = summary
    print(f"  stops {s['stops']:,} = {s['enforcement_stops']:,} traffic enforcement + {s['inspection_stops']:,} inspections "
          f"| tickets {s['tickets']:,} | violation records {s['violation_records']:,}")
    print(f"  per day {s['stops_per_day']:,.0f} | vs Feb {s['pct_change_vs_prior_month']:+.1f}% | vs 6-mo {s['pct_change_vs_6mo']:+.1f}% "
          f"| top-10 share {s['top_shares_pct']['10']:.1f}% | counties for half {s['counties_for_half']} | Gini {s['gini']:.3f}")
    print(f"  EB prior a={eb['a']:.3f} b={eb['b']:.3f} | SAR signal {s['sar_counts']}")
    print(f"  stop frequency vs. citation share: rho={s['rho_sar_vs_citation']:.3f}")
    print(f"  county groups {[(q['quadrant'], q['counties']) for q in s['quadrants']]}")
    print(norm_agree.round(3).to_string(index=False))
    print(f"  dashboard.json {(C.SITE_DATA / 'dashboard.json').stat().st_size / 1e3:,.0f} KB")


if __name__ == "__main__":
    main()
