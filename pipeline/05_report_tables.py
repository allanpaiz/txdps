import json

import pandas as pd

import config as C
from report_data import (
    commercial_service_counts,
    county_outcome_counts,
    driver_race_known_counts,
    february_changes,
    inspection_leaders,
    program_monthly,
    search_fugitive_summary,
    violation_county_leaders,
)

ENF, INSP = "Traffic enforcement", "Commercial inspection"
QUADRANTS = [
    "More stops, higher citation share",
    "More stops, lower citation share",
    "Fewer stops, higher citation share",
    "Fewer stops, lower citation share",
]
COMP_SIZE = (
    r"\footnotesize\setlength{\tabcolsep}{3.5pt}\renewcommand{\arraystretch}{1.02}"
)


def tex_int(x):
    return f"{int(round(x)):,}".replace(",", "{,}")


def tex_num(x, nd=1):
    return f"{x:,.{nd}f}".replace(",", "{,}")


def stops_share(stops, total):
    return f"{tex_int(stops)} ({100 * stops / total:.1f}\\%)"


def tex_escape(s):
    return (
        str(s)
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("_", r"\_")
        .replace("#", r"\#")
    )


def fmt_opt(x, nd=1, signed=False, pct=False):
    if x is None or pd.isna(x):
        return "--"
    s = (f"{x:+,.{nd}f}" if signed else f"{x:,.{nd}f}").replace(",", "{,}")
    return s + (r"\%" if pct else "")


def fmt_delta(x, nd=0):
    value = fmt_opt(x, nd, signed=True)
    return (
        r"\textcolor{negative}{" + value + "}"
        if x is not None and not pd.isna(x) and x < 0
        else value
    )


def write(name, text):
    C.REPORT_GENERATED.mkdir(parents=True, exist_ok=True)
    (C.REPORT_GENERATED / name).write_text(text, encoding="utf-8")


def tabular(
    name, colspec, header, rows, size=None, midrules=(), env="tabular", width=None
):
    body = []
    for i, r in enumerate(rows):
        if i in midrules:
            body.append(r"\midrule")
        body.append(r)
    begin = rf"\begin{{{env}}}" + (f"{{{width}}}" if width else "") + f"{{{colspec}}}"
    text = (
        begin
        + "\n\\toprule\n"
        + header
        + r" \\"
        + "\n\\midrule\n"
        + "\n".join(body)
        + f"\n\\bottomrule\n\\end{{{env}}}\n"
    )
    if size:
        text = "{" + size + "\n" + text + "}\n"
    write(name, text)


LONG_HEAD = r"""\endfirsthead
\toprule
{hdr} \\
\midrule
\endhead
\midrule \multicolumn{{{n}}}{{r}}{{\emph{{continued on next page}}}} \\
\endfoot
\bottomrule
\endlastfoot
"""


def longtable(
    name,
    colspec,
    hdr,
    ncols,
    caption,
    label,
    rows,
    size=r"\scriptsize\setlength{\tabcolsep}{3.2pt}",
):
    write(
        name,
        "{"
        + size
        + "\n\\begin{longtable}{"
        + colspec
        + "}\n"
        + f"\\caption{{{caption}}}\\label{{{label}}}\\\\\n\\toprule\n{hdr} \\\\\n\\midrule\n"
        + LONG_HEAD.format(hdr=hdr, n=ncols)
        + "\n".join(rows)
        + "\n\\end{longtable}}\n",
    )


def numbers_tex(df, s, quality, facts):
    q = quality.set_index("check_id")
    by = df.set_index("county_name")
    macros = {
        "BaselinePerDay": tex_int(s["baseline_stops_per_day"]),
        "CitationRate": f"{s['citation_rate_pct']:.1f}",
        "CountiesForHalf": str(s["counties_for_half"]),
        "CountiesWithStops": str(s["counties_with_stops"]),
        "DuplicateStopIDs": tex_int(q.loc["Q19", "value"]),
        "EbA": f"{s['eb_prior']['a']:.2f}",
        "EbB": f"{s['eb_prior']['b']:.2f}",
        "InspPctElPaso": f"{by.loc['El Paso', 'inspection_share_pct']:.0f}",
        "InspPctWebb": f"{by.loc['Webb', 'inspection_share_pct']:.0f}",
        "LocatedPct": f"{100 * facts['located_stops'] / s['stops']:.1f}",
        "MedianCountyStops": tex_int(s["median_county_stops"]),
        "MinSearchesHit": str(C.MIN_SEARCHES_FOR_HIT_RATE),
        "MinStopsChange": str(C.MIN_STOPS_FOR_CHANGE),
        "MinStopsRate": str(C.MIN_STOPS_FOR_RATE),
        "MissingCoordsPct": f"{100 * q.loc['Q07', 'value'] / q.loc['Q07', 'denominator']:.1f}",
        "MissingCountyIDs": tex_int(q.loc["Q17", "value"]),
        "MissingTrooperIDs": tex_int(q.loc["Q18", "value"]),
        "OfficialStops": tex_int(s["official_2018"]["total_stops"]),
        "OutsideTexasStops": tex_int(facts["outside_texas"]),
        "PctChange": f"{s['pct_change_vs_6mo']:+.1f}",
        "PctChangePrior": f"{s['pct_change_vs_prior_month']:+.1f}",
        "QOneShare": f"{s['q1_share_of_official_annual_pct']:.1f}",
        "QOneStops": tex_int(s["q1_2018_stops"]),
        "RhoSarCitation": f"{s['rho_sar_vs_citation']:.2f}",
        "StopsPerDay": tex_int(s["stops_per_day"]),
        "TopTenEnfShare": f"{100 * df.nsmallest(10, 'rank').enf_stops.sum() / df.enf_stops.sum():.1f}",
        "InspectionShare": f"{s['inspection_share_pct']:.1f}",
        "RhoHitConsent": f"{facts['rho_hit_consent']:.2f}",
        "TopTenShare": f"{s['top_shares_pct']['10']:.1f}",
        "TotalStops": tex_int(s["stops"]),
        "TotalTickets": tex_int(s["tickets"]),
        "TotalViolations": tex_int(s["violation_records"]),
        "UnlinkedStopRecords": tex_int(q.loc["Q20", "value"]),
        "ViolationsPerStop": f"{s['violations_per_stop']:.2f}",
    }
    write(
        "numbers.tex",
        "\n".join(rf"\newcommand{{\{k}}}{{{v}}}" for k, v in macros.items()) + "\n",
    )


def table_abbreviations():
    definitions = [
        (r"\% TX; Stops (\%)", "Share of all statewide stops."),
        ("Stops; Tickets", "Reconstructed encounters; distinct source documents."),
        ("Per day; Feb/day; Mar/day", "Stops divided by days in the reporting period."),
        (r"$\Delta$ Feb; $\Delta$ 6-mo", "Percentage change in daily stops. Negative changes are red."),
        (r"$\Delta$/day; $\Delta$ rank", "Absolute change in daily stops; all stop rank minus rank excluding inspections."),
        ("Cited; Warn. only; No viol.", "Stops with a citation; warnings without a citation; neither recorded."),
        (r"Cited \%", "Citation share of enforcement stops."),
        ("Insp.", "Commercial inspection count; percentage in parentheses uses county or category stops."),
        ("CV stops", "Stops recorded by Commercial Vehicle Enforcement service troopers, including both stop types."),
        ("Search; Hit", "Searched enforcement stops; searches finding contraband."),
        ("Race known", "Race recorded as known before the stop. Missing flags are omitted."),
        ("Top County", "County with the largest count in the category. Ties are resolved alphabetically."),
        ("Pop. (k); VMT (M)", "2018 population in thousands; estimated March state highway vehicle miles in millions."),
        ("Per 10k; Per M VMT", "Enforcement stops per 10,000 residents; per million state highway vehicle miles."),
        ("O/E; Obs/Exp", "Observed over expected enforcement stops, estimated using Empirical Bayes."),
        ("--", "Unavailable or withheld."),
        ("DPS; THP; TxDOT", "Texas Department of Public Safety; Texas Highway Patrol; Texas Department of Transportation."),
        ("CVE3", "Commercial vehicle inspection report."),
        ("DVMT; VMT", "Daily vehicle miles traveled; vehicle miles traveled."),
        ("ES; P; HL", "Enforcement stops; population; state highway length in miles."),
        ("AUS; HOU; SA", "Austin; Houston; San Antonio in recorded program names."),
        ("STEP; FEDSTEP", "Selective Traffic Enforcement Program labels in the source."),
        ("PASS; FIXED; WARN; INFO", "No issue detected; cleaning applied; unresolved limitation; contextual result."),
    ]
    rows = [
        term + " & " + tex_escape(meaning) + r" \\" for term, meaning in definitions
    ]
    longtable(
        "table_abbreviations.tex",
        r"@{}>{\raggedright\arraybackslash}p{4cm}>{\raggedright\arraybackslash}p{12cm}@{}",
        "Term & Meaning",
        2,
        "Abbreviations and table key.",
        "tab:abbreviations",
        rows,
        size=r"\footnotesize\renewcommand{\arraystretch}{1.03}",
    )


def table_overview(df, s):
    q = s["county_quantiles"]
    population = df.pop_2018.sum()
    left = [
        (r"\textbf{Traffic stops}", r"\textbf{" + tex_int(s["stops"]) + "}"),
        (
            r"\qquad traffic enforcement",
            f"{tex_int(s['enforcement_stops'])} ({100 - s['inspection_share_pct']:.1f}\\%)",
        ),
        (
            r"\qquad commercial inspections",
            f"{tex_int(s['inspection_stops'])} ({s['inspection_share_pct']:.1f}\\%)",
        ),
        ("Source tickets", tex_int(s["tickets"])),
        ("Stops per day (31 days)", tex_int(s["stops_per_day"])),
        (
            "Change (per day) vs. February",
            fmt_opt(s["pct_change_vs_prior_month"], signed=True, pct=True),
        ),
        ("Troopers making stops", tex_int(s["troopers"])),
        (
            "All stops per 10,000 residents",
            tex_num(10_000 * s["stops"] / population, 1),
        ),
        (
            "Enforcement stops with a citation",
            fmt_opt(s["citation_rate_pct"], pct=True),
        ),
    ]
    right = [
        ("Counties with stops", f"{s['counties_with_stops']} of {len(df)}"),
        ("Fewest (" + s["min_county"]["name"] + ")", tex_int(s["min_county"]["stops"])),
        ("Median", tex_int(s["median_county_stops"])),
        ("Mean", tex_int(s["mean_county_stops"])),
        ("10th--90th percentiles", tex_int(q["0.1"]) + "--" + tex_int(q["0.9"])),
        ("Most (" + s["max_county"]["name"] + ")", tex_int(s["max_county"]["stops"])),
        (
            "Top 10 counties, share of stops",
            fmt_opt(s["top_shares_pct"]["10"], pct=True),
        ),
        ("Counties accounting for 50\\%", tex_int(s["counties_for_half"])),
        ("Counties accounting for 80\\%", tex_int(s["counties_for_80"])),
    ]
    rows = [f"{a} & {b} & & {c} & {d} \\\\" for (a, b), (c, d) in zip(left, right)]
    text = (
        r"\begin{tabular}{@{}lr@{\hspace{7pt}\vrule\hspace{7pt}}l@{}lr@{}}"
        + "\n\\toprule\n"
        + r"\multicolumn{2}{@{}l}{\textbf{A.\ Statewide counts and rates}} & & \multicolumn{2}{l@{}}{\textbf{B.\ County distribution}} \\"
        + "\n\\midrule\n"
        + "\n".join(rows)
        + "\n\\bottomrule\n\\end{tabular}\n"
    )
    text += (
        r"\par\vspace{3pt}{\footnotesize\color{ink2} Per resident rate uses 2018 population of all Texas counties ("
        + tex_int(population)
        + r")~\cite{census_pep_2018}.}"
        + "\n"
    )
    write("table_overview.tex", text)


def table_county_summary(df, s, n=30):
    rows = []
    selected = df.nsmallest(n, "rank") if n is not None else df.sort_values("rank")
    for r in selected.itertuples():
        rows.append(
            " & ".join(
                [
                    str(r.rank),
                    tex_escape(r.county_name),
                    f"{tex_int(r.stops)} ({r.share_pct:.1f}\\%)",
                    tex_num(r.stops_per_day, 0),
                    fmt_delta(r.pct_change_vs_prior_month),
                    fmt_delta(r.pct_change_vs_6mo),
                    tex_int(r.tickets),
                    tex_int(r.warning_only_stops),
                    tex_int(r.no_violation_stops),
                    stops_share(r.inspection_stops, r.stops),
                    tex_int(r.pop_2018 / 1000),
                    tex_num(r.vmt_month_millions, 0),
                    tex_num(r.stops_per_10k_pop, 0),
                    tex_num(r.stops_per_m_vmt, 1),
                    f"{r.sar:.2f}",
                ]
            )
            + r" \\"
        )
    if n is not None:
        rest = df[df["rank"] > n]
        rest_share = 100 * rest.stops.sum() / s["stops"]
        rows.append(
            " & ".join(
                [
                    f"{{[{n + 1}--{len(df)}]}}",
                    "",
                    f"{tex_int(rest.stops.sum())} ({rest_share:.1f}\\%)",
                    tex_num(rest.stops_per_day.sum(), 0),
                    "",
                    "",
                    *[
                        tex_int(rest[c].sum())
                        for c in [
                            "tickets",
                            "warning_only_stops",
                            "no_violation_stops",
                        ]
                    ],
                    stops_share(rest.inspection_stops.sum(), rest.stops.sum()),
                    tex_int(rest.pop_2018.sum() / 1000),
                    tex_num(rest.vmt_month_millions.sum(), 0),
                    tex_num(1e4 * rest.enf_stops.sum() / rest.pop_2018.sum(), 0),
                    tex_num(rest.enf_stops.sum() / rest.vmt_month_millions.sum(), 1),
                    "",
                ]
            )
            + r" \\"
        )
    rows.append(
        " & ".join(
            [
                "",
                r"\textbf{Texas}",
                r"\textbf{" + tex_int(s["stops"]) + r" (100.0\%)}",
                tex_num(s["stops_per_day"], 0),
                fmt_delta(s["pct_change_vs_prior_month"]),
                fmt_delta(s["pct_change_vs_6mo"]),
                *[
                    tex_int(df[c].sum())
                    for c in [
                        "tickets",
                        "warning_only_stops",
                        "no_violation_stops",
                    ]
                ],
                stops_share(s["inspection_stops"], s["stops"]),
                tex_int(s["state_population"] / 1000),
                tex_num(df.vmt_month_millions.sum(), 0),
                tex_num(s["stops_per_10k_pop"], 0),
                tex_num(s["stops_per_m_vmt"], 1),
                "1.00",
            ]
        )
        + r" \\"
    )
    hdr = (
        r"Rank & County & Stops (\% TX) & \shortstack{Per\\day} & \shortstack{$\Delta$\\Feb} & \shortstack{$\Delta$\\6-mo} & "
        r"Tickets & \shortstack{Warn.\\only} & \shortstack{No\\viol.} & "
        r"Insp. & \shortstack{Pop.\\(k)} & \shortstack{VMT\\(M)} & \shortstack{Per\\10k} & "
        r"\shortstack{Per M\\VMT} & Obs/Exp"
    )
    rows = [
        r"\rowcolor{accent!7} " + row if i % 2 else row for i, row in enumerate(rows)
    ]
    if n is None:
        longtable(
            "table_county_summary_full.tex",
            r"@{}rlrrrrrrrrrrrrr@{}",
            hdr,
            15,
            r"County detail for Table~\ref{tab:overview}, all 254 counties, March 2018.",
            "tab:allcounties",
            rows,
            size=r"\fontsize{8}{9.5}\selectfont\setlength{\tabcolsep}{1.8pt}\renewcommand{\arraystretch}{1.0}",
        )
    else:
        tabular(
            "table_county_summary.tex",
            r"@{}rlrrrrrrrrrrrrr@{}",
            hdr,
            rows,
            midrules=(n,),
            size=r"\fontsize{7}{8.4}\selectfont\setlength{\tabcolsep}{1.2pt}\renewcommand{\arraystretch}{0.98}",
        )


def change_row(r):
    change = r"\textbf{" + fmt_delta(r.change_per_day, 1) + "}"
    return (
        " & ".join(
            [
                tex_escape(r.county_name),
                tex_int(r.prior_month_stops),
                tex_int(r.stops),
                tex_num(r.feb_per_day),
                tex_num(r.mar_per_day),
                change,
                tex_num(r.baseline_per_day),
                fmt_delta(r.baseline_change_per_day, 1),
            ]
        )
        + r" \\"
    )


CHANGE_HEADER = (
    r"County & Feb stops & Mar stops & Feb/day & Mar/day & "
    r"\shortstack{vs. Feb\\$\Delta$/day} & \shortstack{Prev. 6 mo.\\Avg/day} & "
    r"\shortstack{vs. prev. 6 mo.\\$\Delta$/day}"
)


def table_change_extremes(df):
    b = february_changes(df)
    up = b.nlargest(10, "change_per_day")
    down = b.nsmallest(10, "change_per_day").iloc[::-1]
    rows = [
        r"\multicolumn{8}{@{}l}{\textcolor{accent}{\textbf{\textit{Largest increases}}}} \\"
    ]
    rows += stripe_rows([change_row(r) for r in up.itertuples()])
    rows += [
        r"\midrule \multicolumn{8}{@{}l}{\textcolor{accent}{\textbf{\textit{Largest decreases}}}} \\"
    ]
    rows += stripe_rows([change_row(r) for r in down.itertuples()])
    header = CHANGE_HEADER.replace(
        r"\shortstack{vs. Feb\\$\Delta$/day}",
        r"\textcolor{accent}{\shortstack{\textbf{vs. Feb}\\\textbf{$\Delta$/day} $\downarrow$}}",
    )
    tabular(
        "table_change_extremes.tex",
        r"@{}lrrrrr|rr@{}",
        header,
        rows,
        size=r"\scriptsize\setlength{\tabcolsep}{3.5pt}\renewcommand{\arraystretch}{1.02}",
    )


def table_programs(programs):
    p = program_monthly(programs)
    top = (
        programs[programs.month == C.TARGET_MONTH]
        .sort_values("stops", ascending=False)
        .drop_duplicates("special_program")
        .set_index("special_program")
    )
    rows = [
        f"{tex_escape(k)} & "
        + " & ".join(tex_int(v) for v in r)
        + (
            f" & {tex_escape(top.loc[k, 'county_name'])} ({tex_int(top.loc[k, 'stops'])})"
            if k in top.index
            else " & --"
        )
        + r" \\"
        for k, r in p.iterrows()
    ]
    totals = p.sum(axis=0)
    rows.append(
        r"\midrule Listed programs & "
        + " & ".join(tex_int(v) for v in totals)
        + r" & \\"
    )
    hdr = (
        "Program & "
        + " & ".join(pd.Timestamp(m + "-01").strftime("%b %y") for m in C.ALL_MONTHS)
        + r" & Top County, Mar 18"
    )
    tabular("table_programs.tex", r"@{}lrrrrrrrl@{}", hdr, rows, size=r"\small")


def stripe_rows(rows):
    out, index = [], 0
    for row in rows:
        rule = r"\midrule " if row.startswith(r"\midrule ") else ""
        body = row[len(rule) :]
        if not body.startswith(r"\multicolumn"):
            if index % 2:
                body = r"\rowcolor{accent!7} " + body
            index += 1
        out.append(rule + body)
    return out


def comparison_table(name, colspec, header, rows, size=COMP_SIZE, **kwargs):
    tabular(
        f"table_{name}.tex", colspec, header, stripe_rows(rows), size=size, **kwargs
    )


def table_driver(state_bd, bd):
    known = driver_race_known_counts()
    rows = []
    for dim, title, order in [
        (
            "Driver race/ethnicity",
            "Race/ethnicity",
            [
                "Hispanic or Latino",
                "White",
                "Black",
                "Asian or Pacific Islander",
                "Alaska Native or American Indian",
                "Other or unknown",
            ],
        ),
        ("Driver sex", "Sex", ["Male", "Female"]),
    ]:
        rows.append(
            (r"\midrule " if rows else "")
            + r"\multicolumn{8}{@{}l}{\emph{"
            + title
            + r"}} \\"
        )
        t = state_bd[state_bd.dimension == dim].set_index("category")
        for category in order:
            r = t.loc[category]
            county = (
                bd[(bd.dimension == dim) & (bd.category == category)]
                .sort_values(["stops", "county_name"], ascending=[False, True])
                .iloc[0]
            )
            leader = f"{tex_escape(county.county_name)} ({tex_int(county.stops)})"
            rows.append(
                " & ".join(
                    [
                        tex_escape(category),
                        stops_share(r.stops, t.stops.sum()),
                        tex_int(known.loc[(dim, category), "known"]),
                        tex_int(r.inspection_stops),
                        tex_int(r.citation_stops),
                        tex_int(r.searched_stops),
                        tex_int(r.contraband_stops),
                        leader,
                    ]
                )
                + r" \\"
            )
    total = state_bd[state_bd.dimension == "Driver race/ethnicity"].sum(
        numeric_only=True
    )
    rows.append(
        r"\midrule Texas & "
        + " & ".join(
            [
                stops_share(total.stops, total.stops),
                tex_int(known.loc["Driver race/ethnicity", "known"].sum()),
                tex_int(total.inspection_stops),
                tex_int(total.citation_stops),
                tex_int(total.searched_stops),
                tex_int(total.contraband_stops),
                "--",
            ]
        )
        + r" \\"
    )
    hdr = r"Category & Stops (\%) & Race known & Insp. & Cited & Search & Hit & Top County"
    comparison_table(
        "driver",
        r"@{}>{\raggedright\arraybackslash}Xrrrrrrl@{}",
        hdr,
        rows,
        size=r"\footnotesize\setlength{\tabcolsep}{3pt}\renewcommand{\arraystretch}{1.04}",
        env="tabularx",
        width=r"\textwidth",
    )


def table_inspection_counties(df):
    df = df.copy()
    df["cv_service_stops"] = df.county_name.map(commercial_service_counts()).fillna(0)
    t = inspection_leaders(df)
    statewide = df.stops.sum()
    rows = []
    for r in t.itertuples():
        change = r.rank - r.enf_rank
        delta = f"({change:+d})" if change else "(0)"
        if change < 0:
            delta = r"\textcolor{negative}{" + delta + "}"
        cells = [
            tex_escape(r.county_name),
            stops_share(r.stops, statewide),
            stops_share(r.inspection_stops, r.stops),
            stops_share(r.cv_service_stops, r.stops),
            rf"{r.rank} $\to$ {r.enf_rank}",
            delta,
        ]
        rows.append(" & ".join(cells) + r" \\")
    rows.append(
        r"\midrule Texas & "
        + stops_share(statewide, statewide)
        + " & "
        + stops_share(df.inspection_stops.sum(), statewide)
        + " & "
        + stops_share(df.cv_service_stops.sum(), statewide)
        + " & -- & --"
        + r" \\"
    )
    hdr = (
        r"County & Stops (\%) & Insp. (\%) & CV stops (\%) & "
        r"\shortstack{Rank\\all $\to$ excl.} & $\Delta$ rank"
    )
    hdr = hdr.replace(
        r"Insp. (\%)", r"\textcolor{accent}{\textbf{Insp. (\%)} $\downarrow$}"
    )
    comparison_table(
        "inspection_counties",
        r"@{}lrrrrr@{}",
        hdr,
        rows,
        size=r"\scriptsize\setlength{\tabcolsep}{3.2pt}\renewcommand{\arraystretch}{0.98}",
    )


def table_violation_categories(vc, s, leaders):
    v = vc.groupby("violation_category")[
        ["stops", "cited_stops", "violation_records", "citations", "warnings"]
    ].sum()
    insp = vc[vc.stop_type == INSP].set_index("violation_category").stops
    v["inspection_stops"] = insp.reindex(v.index).fillna(0)
    v = v.sort_values("stops", ascending=False)
    county = leaders.set_index("category")
    rows = []
    for k, r in v.iterrows():
        lead = county.loc[k]
        rows.append(
            " & ".join(
                [
                    tex_escape(k.title() if k.isupper() else k),
                    stops_share(r.stops, s["stops"]),
                    stops_share(r.cited_stops, r.stops),
                    stops_share(r.inspection_stops, r.stops),
                    f"{tex_escape(lead.county_name)} ({tex_int(lead.stops)})",
                ]
            )
            + r" \\"
        )
    hdr = r"Category & Stops (\%) & Cited (\%) & Insp. (\%) & Top County"
    comparison_table(
        "violation_categories",
        r"@{}>{\raggedright\arraybackslash}Xrrrl@{}",
        hdr,
        rows[:10],
        env="tabularx",
        width=r"\textwidth",
    )
    context = search_fugitive_summary()
    context_rows = []
    for category in ["Fugitive identified", "Search conducted", "Contraband found"]:
        r = context.loc[category]
        context_rows.append(
            " & ".join(
                [
                    category,
                    stops_share(r.stops, s["stops"]),
                    stops_share(r.cited, r.enforcement),
                    stops_share(r.inspections, r.stops),
                    f"{tex_escape(r.leading_county)} ({tex_int(r.leading_stops)})",
                ]
            )
            + r" \\"
        )
    comparison_table(
        "violation_context",
        r"@{}>{\raggedright\arraybackslash}Xrrrl@{}",
        r"Searches and fugitive identification & Stops (\%) & Cited (\%) & Insp. (\%) & Top County",
        context_rows,
        env="tabularx",
        width=r"\textwidth",
    )


def table_outcomes():
    counts = county_outcome_counts()
    rows = []
    groups = [
        (ENF, r"Traffic\\enforcement", ["Warning only", "Citation"]),
        (
            INSP,
            r"Commercial\\inspection",
            ["Warning only", "Citation", "No violation recorded"],
        ),
        (
            "Searches",
            r"Searches\\(enforcement)",
            ["All searches", "Consent", "Contraband found"],
        ),
    ]
    for title, label, categories in groups:
        for i, category in enumerate(categories):
            st = INSP if title == INSP else ENF
            t = counts[(counts.stop_type == st) & (counts.category == category)].copy()
            threshold = (
                C.MIN_SEARCHES_FOR_HIT_RATE
                if category in ["Consent", "Contraband found"]
                else C.MIN_STOPS_FOR_RATE
            )
            eligible = t[t.denominator >= threshold]
            median = (100 * eligible.stops / eligible.denominator).median()
            top = t.sort_values(["stops", "county_name"], ascending=[False, True]).iloc[
                0
            ]
            group = (
                rf"\multirow{{-{len(categories)}}}{{*}}{{\shortstack[l]{{{label}}}}}"
                if i == len(categories) - 1
                else ""
            )
            rule = r"\midrule " if rows and i == 0 else ""
            rows.append(
                rule
                + " & ".join(
                    [
                        group,
                        category,
                        stops_share(t.stops.sum(), t.denominator.sum()),
                        fmt_opt(median, 1, pct=True),
                        f"{tex_escape(top.county_name)} ({tex_int(top.stops)})",
                    ]
                )
                + r" \\"
            )
    tabular(
        "table_outcomes.tex",
        r"@{}l>{\raggedright\arraybackslash}Xrrl@{}",
        r"Group & Outcome & Texas (\%) & Median & Top County",
        rows,
        size=COMP_SIZE,
        env="tabularx",
        width=r"\textwidth",
    )


def table_quadrants(df, s):
    b = df[df.enf_stops >= C.MIN_STOPS_FOR_RATE]
    rows = []
    for q in QUADRANTS:
        r = b[b.quadrant == q]
        frequency = "More" if q.startswith("More") else "Fewer"
        citations = "Higher" if "higher" in q else "Lower"
        ex = ", ".join(r.nlargest(4, "enf_stops").county_name)
        rows.append(
            f"{frequency} & {citations} & {len(r)} & {stops_share(r.enf_stops.sum(), b.enf_stops.sum())} & "
            f"{r.sar.median():.2f} & {r.citation_rate_pct.median():.1f} & {ex} \\\\"
        )
    tabular(
        "table_quadrants.tex",
        r"@{}llrrrr>{\raggedright\arraybackslash}X@{}",
        r"Stops & Citations & Counties & Stops (\%) & \shortstack{Median\\O/E} & \shortstack{Median\\cited \%} & Top Counties",
        stripe_rows(rows),
        size=COMP_SIZE,
        env="tabularx",
        width=r"\textwidth",
    )


def table_quality(quality):
    rows = []
    for r in quality.itertuples():
        den = "" if pd.isna(r.denominator) else tex_int(r.denominator)
        pct = (
            ""
            if pd.isna(r.denominator) or r.denominator == 0
            else f"{100 * r.value / r.denominator:.2f}\\%"
        )
        rows.append(
            f"{r.check_id} & {tex_escape(r.check_name)} & {tex_int(r.value)} & {den} & {pct} & "
            f"\\textsf{{{r.status}}} & {tex_escape(r.handling)} \\\\"
        )
    longtable(
        "table_quality.tex",
        r"@{}p{0.7cm}p{6.6cm}rrrp{1.2cm}p{8.4cm}@{}",
        r"ID & Check & Count & Of & \% & Status & Handling",
        7,
        "Data quality checks, March 2018 unless noted.",
        "tab:quality",
        rows,
        size=r"\fontsize{7.5}{8.5}\selectfont\renewcommand{\arraystretch}{1.0}",
    )

    rules = [
        ("R1", "Match the county name Dewitt to De Witt."),
        ("R2", "Compare Yes/No flags without regard to letter case."),
        ("R3", "Trim padded trooper IDs, routes, vehicle types and program names; treat empty values as missing."),
        ("R4", "Treat zero posted speeds and vehicle years as missing."),
        ("R5", "Treat coordinates outside the Texas bounding box as missing; exclude points outside the state boundary from the location figure."),
    ]
    with (C.REPORT_GENERATED / "table_quality.tex").open("a") as f:
        f.write(r"\par\vspace{4pt}{\footnotesize\begin{tabularx}{\linewidth}{@{}lX@{}}" + "\n")
        f.write(r"\toprule Number & Rule \\\midrule" + "\n")
        f.write("\n".join(number + " & " + tex_escape(rule) + r" \\" for number, rule in rules))
        f.write("\n" + r"\bottomrule\end{tabularx}}" + "\n")


def main():
    df = pd.read_csv(
        C.OUTPUTS / f"county_metrics_{C.TARGET_MONTH}.csv", dtype={"fips": str}
    )
    s = json.loads((C.OUTPUTS / "statewide_summary.json").read_text())
    quality = pd.read_csv(C.OUTPUTS / "data_quality.csv")
    state_bd = pd.read_csv(C.OUTPUTS / f"statewide_breakdown_{C.TARGET_MONTH}.csv")
    bd = pd.read_csv(C.OUTPUTS / f"county_breakdown_{C.TARGET_MONTH}.csv")
    programs = pd.read_csv(C.OUTPUTS / "special_program_month.csv")
    vc = pd.read_csv(C.OUTPUTS / f"violation_categories_{C.TARGET_MONTH}.csv")
    facts = json.loads((C.BUILD / "figure_facts.json").read_text())
    facts["located_stops"] = facts["located"]

    numbers_tex(df, s, quality, facts)
    table_abbreviations()
    table_overview(df, s)
    table_county_summary(df, s)
    table_county_summary(df, s, n=None)
    table_change_extremes(df)
    table_programs(programs)
    table_driver(state_bd, bd)
    table_inspection_counties(df)
    table_violation_categories(vc, s, violation_county_leaders())
    table_outcomes()
    table_quadrants(df, s)
    table_quality(quality)
    print(f"  tables and macros -> {C.REPORT_GENERATED.relative_to(C.ROOT)}")


if __name__ == "__main__":
    main()
