import json
import shutil

import duckdb
import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import shapely
from scipy import stats
from shapely.plotting import patch_from_polygon

matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

import config as C
from report_data import county_speeding_counts, february_changes, inspection_leaders


P = C.PALETTE
SEQ, CAT = P["sequential"], P["categorical"]
INK, INK2, MUTED, GRID = "#1a1a1a", "#4d4c48", "#86857f", "#e4e3dc"
QUAD_COLORS = P["quadrants"]
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8.5, "axes.edgecolor": "#bdbcb4", "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
    "axes.titlesize": 9.5, "axes.titleweight": "bold", "axes.titlecolor": INK, "axes.titlelocation": "center",
    "axes.titlepad": 8, "legend.frameon": False, "savefig.bbox": "tight", "savefig.pad_inches": 0.04,
})
HALO = [pe.withStroke(linewidth=2.4, foreground="white")]
LABEL_OFFSETS = {
    "Hidalgo": (0, -60e3), "Starr": (-60e3, -55e3), "Cameron": (75e3, -30e3), "Zapata": (-95e3, -15e3),
    "Brooks": (70e3, 15e3), "Tarrant": (-95e3, 30e3), "Dallas": (90e3, 30e3), "Brazoria": (60e3, -45e3),
    "Montgomery": (85e3, 35e3), "Harris": (95e3, -5e3), "Bexar": (-70e3, -35e3), "Ellis": (80e3, -20e3),
    "Webb": (-80e3, -20e3), "Travis": (-75e3, 25e3), "El Paso": (0, 45e3), "Presidio": (-40e3, -60e3),
    "Maverick": (-70e3, -10e3), "Collin": (70e3, 30e3), "Parker": (-80e3, 0), "Kenedy": (75e3, 0),
}
def classify(values, breaks):
    v = np.asarray(values, float)
    return np.where(np.isnan(v), -1, np.digitize(v, breaks, right=False))


def class_labels(breaks, fmt, counts):
    edges = [None] + list(breaks) + [None]
    out = []
    for (lo, hi), n in zip(zip(edges[:-1], edges[1:]), counts):
        rng = f"< {fmt(hi)}" if lo is None else f"≥ {fmt(lo)}" if hi is None else f"{fmt(lo)} – {fmt(hi)}"
        out.append(f"{rng}  ({n} {'county' if n == 1 else 'counties'})")
    return out


def save(fig, name):
    C.REPORT_FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(C.REPORT_FIGURES / f"{name}.pdf")
    preview = {"fig_map_stops": "overview", "fig_decomposition": "frequency"}.get(name)
    if preview:
        fig.savefig(C.ROOT / "docs" / "assets" / f"{preview}.png", dpi=160)
    plt.close(fig)


def tidy_axes(ax, grid_axis="y"):
    ax.grid(True, axis=grid_axis, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def log_ratio_axis(ax, axis="x", ticks=(0.1, 0.2, 0.5, 1, 2, 5, 10, 20)):
    getattr(ax, f"set_{axis}scale")("log")
    lo, hi = getattr(ax, f"get_{axis}lim")()
    t = [x for x in ticks if lo <= x <= hi]
    getattr(ax, f"set_{axis}ticks")(t)
    getattr(ax, f"set_{axis}ticklabels")([f"{x:g}×" for x in t])
    getattr(ax, f"{axis}axis").set_minor_locator(matplotlib.ticker.NullLocator())


def draw_highways(ax, interstates, alpha=1.0):

    interstates.plot(ax=ax, color=P["highway_casing"], linewidth=1.5, zorder=2, alpha=alpha)
    interstates.plot(ax=ax, color=P["highway"], linewidth=0.7, zorder=2.1, alpha=alpha)


def highway_legend(alpha=1.0):
    return Line2D([], [], color=P["highway"], linewidth=0.9, label="Interstate highway", alpha=alpha,
                  path_effects=[pe.Stroke(linewidth=1.8, foreground=P["highway_casing"]), pe.Normal()])


def text_color(color):
    rgb = np.array(matplotlib.colors.to_rgb(color))
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    luminance = linear @ np.array([0.2126, 0.7152, 0.0722])
    return "white" if luminance < 0.179 else INK


def label_counties(ax, g, names, size=6.5, leader_lines=True, plain=False):
    for name in names:
        p = g.loc[g.county_name == name, "label_pt"].iloc[0]
        dx, dy = LABEL_OFFSETS.get(name, (0, 0))
        if dx or dy:
            ax.annotate(name, (p.x, p.y), xytext=(p.x + dx, p.y + dy), ha="center", va="center", fontsize=size,
                        color=INK, path_effects=None if plain else HALO,
                        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 0.4} if plain else None,
                        arrowprops=(dict(arrowstyle="-", color=INK2, linewidth=0.5, shrinkA=0, shrinkB=1)
                                    if leader_lines else None))
        else:
            ax.annotate(name, (p.x, p.y), ha="center", va="center", fontsize=size, color=INK,
                        path_effects=None if plain else HALO,
                        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 0.4} if plain else None)


def choropleth(ax, g, col, metric, fmt, title, legend_title, label_names=(), interstates=None, legend="right",
               ncol=1, colors=None, leader_lines=True, plain_labels=False, label_size=6.5):

    breaks = metric["breaks"]
    colors = colors or (P["sequential7"] if len(breaks) == 6 else SEQ)
    cls = classify(g[col], breaks)
    g.plot(ax=ax, color=[colors[c] if c >= 0 else P["suppressed"] for c in cls],
           edgecolor=P["county_border"], linewidth=0.35)
    n_missing = int((cls < 0).sum())
    if n_missing:
        g[cls < 0].plot(ax=ax, facecolor="none", edgecolor="#cfcdc5", linewidth=0.25, hatch="/////")
    if interstates is not None:
        draw_highways(ax, interstates)
    x0, y0, x1, y1 = g.total_bounds
    ax.set_xlim(x0 - 20e3, x1 + 20e3)
    ax.set_ylim(y0 - 20e3, y1 + 20e3)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(title, y=1.0)
    counts = [int((cls == i).sum()) for i in range(len(breaks) + 1)]
    handles = [Patch(facecolor=c, edgecolor="none", label=l) for c, l in zip(colors, class_labels(breaks, fmt, counts))]
    if n_missing:
        handles.append(Patch(facecolor=P["suppressed"], edgecolor="#cfcdc5", hatch="/////",
                             label=f"Suppressed, too few stops  ({n_missing} counties)"))
    if interstates is not None:
        handles.append(highway_legend())
    kw = dict(handles=handles, title=legend_title, fontsize=6.6, title_fontsize=7.0, handlelength=1.1,
              handleheight=0.9, alignment="left", ncol=ncol, columnspacing=1.0)
    if legend == "below":
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, 0.0), **kw)
    else:
        ax.legend(loc="lower left", bbox_to_anchor=(-0.02, 0.0), **kw)
    label_counties(ax, g, label_names, size=label_size, leader_lines=leader_lines, plain=plain_labels)
    return counts


def map_stops_figure(g, df, s, m, ih):

    month = s["target_month_label"].replace("Mar", "March")
    top8 = df.nsmallest(8, "rank").county_name.tolist()
    fint = lambda x: f"{x:,.0f}"

    fig, ax = plt.subplots(figsize=(6.5, 6.1))
    choropleth(ax, g, "stops", m["stops"], fint, f"THP traffic stops by county, {month}",
               "Traffic stops", top8, interstates=ih, leader_lines=False)
    with matplotlib.rc_context({"pdf.fonttype": 42}):
        save(fig, "fig_map_stops")


def map_change_figure(g, s, m):
    g = february_changes(g)
    fig, ax = plt.subplots(figsize=(4.0, 3.6))
    fpct = lambda x: f"{x:+.0f}%"
    choropleth(ax, g, "change_pct", m["pct_change_vs_prior_month"], fpct,
               f"March 2018 vs. {s['prior_month_label'].replace('Feb', 'February')}",
               "Change in stops per day")
    ax.legend(handles=ax.get_legend().legend_handles, title="Change in stops per day",
              loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=8, title_fontsize=8,
              handlelength=1.1, alignment="left")
    ax.set_title("")
    fig.canvas.draw()
    bounds = ax.get_tightbbox(fig.canvas.get_renderer())
    fig.suptitle(f"March 2018 vs. {s['prior_month_label'].replace('Feb', 'February')}",
                 x=(bounds.x0 + bounds.x1) / (2 * fig.bbox.width), y=0.98,
                 fontsize=9.5, fontweight="bold")
    with matplotlib.rc_context({"pdf.fonttype": 42}):
        save(fig, "fig_map_change")


def map_normalized_figure(g, df, m):
    fint = lambda x: f"{x:,.0f}"
    fig, axes = plt.subplots(1, 3, figsize=(6.6, 3.8))
    fig.subplots_adjust(wspace=0.12)
    specs = [("stops_per_10k_pop", "Per 10,000 residents", fint), ("stops_per_m_vmt", "Per million VMT", fint),
             ("stops_per_100_road_miles", "Per 100 highway miles", fint)]
    for ax, (col, title, f) in zip(axes, specs):
        choropleth(ax, g, col, m.get(col) or {"breaks": quantile_breaks(df[col]), "scale": "sequential"}, f, title,
                   "Traffic Stops", legend="below")
        ax.title.set_fontsize(8)
        for collection in ax.collections:
            collection.set_rasterized(True)
        ax.get_legend().set_rasterized(True)
    with matplotlib.rc_context({"pdf.fonttype": 42, "savefig.dpi": 300}):
        save(fig, "fig_map_normalized")


def map_figures(g, df, s, m, ih):
    map_stops_figure(g, df, s, m, ih)
    map_change_figure(g, s, m)
    map_normalized_figure(g, df, m)


def quantile_breaks(values, k=C.QUANTILE_CLASSES):
    v = pd.Series(values).dropna()
    qs = np.quantile(v, np.linspace(0, 1, k + 1)[1:-1])
    for sig in (2, 3, 4):
        out = sorted(set(float(f"{q:.{sig}g}") for q in qs))
        if len(out) == len(qs):
            break
    return [b for b in out if b > v.min()]


def stop_location_figure(g, ih, s):
    with duckdb.connect(str(C.DB_PATH), read_only=True) as con:
        pts = con.sql("SELECT latitude, longitude FROM stop_locations").df()
    xy = gpd.GeoSeries(gpd.points_from_xy(pts.longitude, pts.latitude), crs="EPSG:4326").to_crs(C.CRS_TEXAS)
    texas = g.geometry.union_all()
    inside = shapely.contains_xy(texas, xy.x.to_numpy(), xy.y.to_numpy())
    x, y = xy.x[inside], xy.y[inside]
    fig, ax = plt.subplots(figsize=(6.5, 6.1))
    g.boundary.plot(ax=ax, color=P["county_border"], linewidth=0.35, zorder=1.5)
    bounds, gridsize = [1, 5, 25, 100, 400, 100000], 95
    hb = ax.hexbin(x, y, gridsize=gridsize, mincnt=1, cmap=ListedColormap(SEQ), norm=BoundaryNorm(bounds, len(SEQ)),
                   linewidths=0)
    hb.set_clip_path(patch_from_polygon(texas, transform=ax.transData))
    draw_highways(ax, ih, alpha=0.55)
    ax.set_axis_off()
    hex_km = (x.max() - x.min()) / gridsize / 1000
    hex_miles = hex_km * 1000 / C.METRES_PER_MILE
    ax.set_title(f"Stop locations" + r"$^{*}$" + f", {s['target_month_label'].replace('Mar', 'March')}")
    labels = ["1 – 4", "5 – 24", "25 – 99", "100 – 399", "400 or more"]
    handles = [Patch(facecolor=c, edgecolor="none", label=f"{l} stops") for c, l in zip(SEQ, labels)]
    handles.append(highway_legend(alpha=0.55))
    ax.legend(handles=handles, title=f"Stops per hexagon (about {hex_miles:.0f} mi across)",
              loc="lower left", bbox_to_anchor=(-0.02, 0.0), fontsize=6.6, title_fontsize=7.0, alignment="left",
              handlelength=1.1, handleheight=0.9)
    save(fig, "fig_stop_locations")
    return {"located": int(inside.sum()), "outside_texas": int((~inside).sum()), "hex_km": hex_km}


def chart_trend(s):
    mo = pd.DataFrame(s["monthly"])
    labels = [pd.Timestamp(x + "-01").strftime("%b\n%Y") for x in mo.month]
    colors = np.where(mo.month == C.TARGET_MONTH, P["highlight"], P["sequential7"][0])
    fig, ax = plt.subplots(figsize=(6.5, 2.5))
    vals = mo.stops_per_day.to_numpy()
    bars = ax.bar(labels, vals, color=colors, width=0.6)
    base = mo.iloc[:-1].stops.sum() / mo.iloc[:-1].days.sum()
    ax.axhline(base, color=INK2, linewidth=0.8, linestyle=(0, (3, 2)))
    for bar, value in zip(bars, vals):
        ax.text(bar.get_x() + bar.get_width() / 2, value + vals.max() * 0.02,
                f"{value:,.0f}", ha="center", va="bottom", fontsize=6.6, color=INK)
    ax.set_ylim(0, vals.max() * 1.2)
    ax.set_title("Traffic stops per day", fontsize=8.8)
    ax.tick_params(axis="x", labelsize=6.8, length=0)
    ax.tick_params(axis="y", labelsize=6.6, length=0)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    tidy_axes(ax)
    ax.spines["left"].set_visible(False)
    save(fig, "fig_trend")


def county_stop_bands(df):

    edges = C.COUNTY_STOP_BAND_EDGES
    labels = [f"Fewer than {edges[0]:,}"]
    labels += [f"{lo:,}\N{EN DASH}{hi - 1:,}" for lo, hi in zip(edges[:-1], edges[1:])]
    labels += [f"{edges[-1]:,} or more"]
    groups = pd.cut(df.stops, [0, *edges, np.inf], labels=labels, right=False)
    bands = df.groupby(groups, observed=False).agg(counties=("stops", "size"), stops=("stops", "sum"))
    bands["share_pct"] = 100 * bands.stops / df.stops.sum()
    return bands


def chart_county_bins(df):

    bands = county_stop_bands(df)
    colors = P["sequential7"][1:]
    ordered = bands.iloc[::-1]
    group_colors = colors[::-1]
    y = np.arange(len(ordered))
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.8), sharey=True,
                             gridspec_kw={"width_ratios": [1, 2.1], "wspace": 0.25})
    for ax, col, title in [(axes[0], "counties", "Counties"),
                            (axes[1], "stops", "Traffic Stops")]:
        ax.barh(y, ordered[col], height=0.6, color=group_colors)
        ax.set_title(title, fontsize=8.5)
        ax.tick_params(axis="both", length=0, labelsize=7)
        ax.spines["left"].set_visible(False)
        tidy_axes(ax, "x")
        for i, (_, r) in enumerate(ordered.iterrows()):
            label = f"{int(r.counties):,}" if col == "counties" else f"{int(r.stops):,} ({r.share_pct:.1f}%)"
            ax.annotate(label, (r[col], i), xytext=(4, 0), textcoords="offset points",
                        va="center", fontsize=6.7, color=INK)
    axes[0].set_yticks(y, ordered.index)
    axes[0].invert_yaxis()
    axes[0].set_ylabel("Stops", fontsize=8, labelpad=8)
    axes[0].set_xlim(0, ordered.counties.max() * 1.2)
    axes[0].xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(nbins=4, integer=True))
    axes[0].set_xlabel("Number of counties", fontsize=7.5)
    stop_limit = np.ceil(ordered.stops.max() * 1.32 / 10_000) * 10_000
    axes[1].set_xlim(0, stop_limit)
    axes[1].set_xticks(np.arange(0, stop_limit + 1, 25_000))
    axes[1].xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    axes[1].set_xlabel("Number of stops", fontsize=7.5)
    axes[1].tick_params(axis="y", labelleft=False)
    save(fig, "fig_county_bins")


def chart_county_ranked(df):

    colors = P["sequential7"][1:]
    ordered = county_stop_bands(df).iloc[::-1]
    fig, ranked = plt.subplots(figsize=(6.6, 2.5))
    d = df.sort_values("rank")
    cls = classify(d.stops, C.COUNTY_STOP_BAND_EDGES)
    x = np.arange(1, len(d) + 1)
    ranked.bar(x, d.stops, width=0.8, color=[colors[c] for c in cls], linewidth=0)
    cumulative_counties = ordered.counties.cumsum()
    cumulative_shares = 100 * ordered.stops.cumsum() / d.stops.sum()
    for k, share in zip(cumulative_counties.iloc[:-1], cumulative_shares.iloc[:-1]):
        ranked.axvline(k + 0.5, color=INK2, linewidth=0.7, linestyle=(0, (3, 2)))
        ranked.annotate(f"{share:.1f}% of stops", (k + 0.5, 0.96), xycoords=("data", "axes fraction"),
                        xytext=(3, 0), textcoords="offset points", rotation=90, va="top", ha="left",
                        fontsize=6.4, color=INK)
    ranked.set_xlim(0, len(d) + 1)
    ranked.set_ylim(0, d.stops.max() * 1.06)
    ranked.set_xlabel("All 254 counties, ranked by stops", fontsize=7.5)
    ranked.set_ylabel("Traffic stops", fontsize=8)
    ranked.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ranked.set_xticks([1, 50, 100, 150, 200, 254])
    ranked.tick_params(axis="both", labelsize=7)
    tidy_axes(ranked)
    ranked.set_title("Every County's Stops", fontsize=8.5)
    save(fig, "fig_county_ranked")


def chart_race_counties(df, bd):
    order = ["Hispanic or Latino", "White", "Black", "Asian or Pacific Islander", "Other"]
    r = bd[bd.dimension == "Driver race/ethnicity"].copy()
    r["category"] = r.category.where(r.category.isin(order[:4]), "Other")
    all_counties = r.groupby(["county_name", "category"]).stops.sum().unstack(fill_value=0).reindex(columns=order, fill_value=0)
    counties = df.nsmallest(15, "rank").county_name.tolist()
    t = all_counties.reindex(counties).copy()
    t.loc["Texas"] = all_counties.sum()
    t = t.reindex(["Texas", *counties])
    shares = 100 * t.div(t.sum(axis=1), axis=0)
    fig, ax = plt.subplots(figsize=(6.5, 3.0))
    y = np.arange(len(t))[::-1]
    left = np.zeros(len(t))
    for category, color in zip(order, CAT):
        vals = shares[category].to_numpy()
        ax.barh(y, vals, left=left, color=color, height=0.84, edgecolor="white", linewidth=0.6, label=category)
        for yi, start, value in zip(y, left, vals):
            if value >= 8:
                ax.annotate(f"{value:.0f}%", (start + value / 2, yi), xytext=(0, -72 / 170),
                            textcoords="offset points", ha="center", va="center",
                            fontsize=6.8, color=text_color(color))
        left += vals
    ax.set_yticks(y, [f"{county}  ({int(count):,})" for county, count in zip(t.index, t.sum(axis=1))], fontsize=6.8)
    ax.get_yticklabels()[0].set_fontweight("bold")
    ax.axhline(y[0] - 0.5, color=GRID, linewidth=0.6)
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="x", labelsize=7)
    ax.spines["left"].set_visible(False)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3, fontsize=6.5,
              handlelength=1.0, columnspacing=1.0)
    ax.set_title("Drivers by county", pad=34)
    with matplotlib.rc_context({"pdf.fonttype": 42}):
        save(fig, "fig_race_counties")


def chart_inspection_effect(df):
    t = inspection_leaders(df).iloc[::-1].reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    y = np.arange(len(t))
    ax.hlines(y, t.enf_stops, t.stops, color="#cfcdc5", linewidth=2.2)
    ax.scatter(t.stops, y, s=30, color=CAT[0], edgecolor="white", linewidth=1.0, zorder=3, label="All stops")
    ax.scatter(t.enf_stops, y, s=30, color=CAT[1], edgecolor="white", linewidth=1.0, zorder=3,
               label="Excluding inspections")
    xmax = t.stops.max()
    ax.set_yticks(y)
    ax.set_yticklabels(t.county_name, fontsize=7)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlim(0, xmax * 1.05)
    ax.set_xlabel("Traffic stops")
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    tidy_axes(ax, "x")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, fontsize=6.8)
    ax.set_title("Commercial inspections by county", pad=20)
    save(fig, "fig_inspection_effect")


def chart_speeding_counties(df):

    t = df[["county_name", "stops"]].merge(county_speeding_counts(), on="county_name",
                                           how="left", validate="one_to_one")
    t["speeding_stops"] = t.speeding_stops.fillna(0)
    t["speeding_share_pct"] = 100 * t.speeding_stops / t.stops
    state_share = 100 * t.speeding_stops.sum() / t.stops.sum()
    fig, ax = plt.subplots(figsize=(6.5, 2.8))
    ax.scatter(t.speeding_share_pct, t.speeding_stops, s=15, color=CAT[1], alpha=0.7,
               edgecolor="white", linewidth=0.35, zorder=3, rasterized=True)
    offsets = {"Hidalgo": (6, 3), "Harris": (-6, -12), "Montgomery": (-7, 5),
               "Brazoria": (-6, 7), "Parker": (6, -10), "Webb": (-6, 5), "El Paso": (-6, 5)}
    selected = t[t.county_name.isin(offsets)]
    ax.scatter(selected.speeding_share_pct, selected.speeding_stops, s=23, color=P["raw"],
               edgecolor="white", linewidth=0.5, zorder=4, rasterized=True)
    ax.set_yscale("log")
    ax.set_ylim(0.65, 12000)
    ax.set_yticks([1, 10, 100, 1000, 10000], ["1", "10", "100", "1,000", "10,000"])
    ax.yaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    ax.set_xlim(0, 102)
    ax.set_xticks([0, 20, 40, 60, 80, 100], ["0%", "20%", "40%", "60%", "80%", "100%"])
    ax.axvline(state_share, color=P["important"], linewidth=1.2, linestyle=(0, (4, 3)), zorder=2)
    ax.text(state_share + 1, 1.0, f"Texas: {state_share:.1f}%",
            fontsize=7, color=INK2, ha="left", va="bottom")
    for r in selected.itertuples():
        dx, dy = offsets[r.county_name]
        ax.annotate(r.county_name, (r.speeding_share_pct, r.speeding_stops), xytext=(dx, dy),
                    textcoords="offset points", fontsize=6.6, color=INK,
                    ha="right" if dx < 0 else "left",
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 0.5})
    ax.set_title("Speeding Stops by County")
    ax.set_xlabel("Share of county stops involving speeding", fontsize=8)
    ax.set_ylabel("Speeding stops (log scale)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.spines["left"].set_visible(False)
    tidy_axes(ax, "y")
    with matplotlib.rc_context({"pdf.fonttype": 42, "savefig.dpi": 300}):
        save(fig, "fig_speeding_counties")


def chart_outcomes_by_region(df, s):
    b = df[df.enf_stops >= C.MIN_STOPS_FOR_RATE].copy()
    regions = [C.DPS_REGIONS[k] for k in sorted(C.DPS_REGIONS)]
    rng = np.random.default_rng(7)
    fig = plt.figure(figsize=(6.5, 5.35))
    grid = fig.add_gridspec(2, 2, height_ratios=[1, 1.85], width_ratios=[1, 0.25],
                            hspace=0.50, wspace=0.06)
    axes = [fig.add_subplot(grid[0, 0]), fig.add_subplot(grid[1, :])]
    ax=axes[0]
    for i, reg in enumerate(regions):
        r = b[b.region_name == reg]
        yj = i + rng.uniform(-0.14, 0.14, len(r))
        ax.scatter(r.citation_rate_pct, yj, s=4 + 60*np.sqrt(r.enf_stops/b.enf_stops.max()),
                   color=CAT[1],alpha=0.65,edgecolor='white',linewidth=0.4,rasterized=True,zorder=3)
        ax.plot([r.citation_rate_pct.median()]*2,[i-0.22,i+0.22],color=P['highlight'],linewidth=1.8,zorder=5)
        leader=r.sort_values(['citation_rate_pct','county_name'],ascending=[False,True]).iloc[0]
        leader_y=yj[r.index.get_loc(leader.name)]
        ax.scatter([leader.citation_rate_pct],[leader_y],s=26,color=P['raw'],edgecolor='white',
                   linewidth=0.4,rasterized=True,zorder=4)
        ax.annotate(f"{leader.county_name}  {leader.citation_rate_pct:.1f}%",
                    (leader.citation_rate_pct,leader_y),xytext=(7,0),va='center',ha='left',
                    textcoords='offset points',fontsize=6.4,color=INK,
                    bbox={'facecolor':'white','edgecolor':'none','alpha':0.9,'pad':0.4})
    ax.axvline(s['citation_rate_pct'],color=P['important'],linewidth=1,linestyle=(0,(4,3)))
    ax.set_title('Stops with a Citation',fontsize=8.8)
    citation_lo = max(0, 10 * np.floor(b.citation_rate_pct.min() / 10))
    citation_hi = min(100, 10 * np.ceil(b.citation_rate_pct.max() / 10) + 5)
    ax.set_xlim(citation_lo, citation_hi)
    ticks = np.arange(citation_lo, citation_hi + 1, 20)
    ax.set_xticks(ticks,[f'{v:g}%' for v in ticks],fontsize=7)
    ax.set_xlabel('Stops with a Citation (%)',fontsize=7.5,labelpad=3)
    ax.set_yticks(range(len(regions)),[f'{r} ({(b.region_name==r).sum()})' for r in regions],fontsize=6.8)
    ax.set_ylim(len(regions)-0.5,-0.5)
    ax.spines['left'].set_visible(False)
    ax.tick_params(axis='y',length=0)
    ax.legend(handles=[Line2D([],[],color=P['highlight'],marker='|',markersize=9,linestyle='none',label='Regional Median'),
                       Line2D([],[],color=P['important'],linestyle=(0,(4,3)),label='Statewide')],
              loc='center left',bbox_to_anchor=(1.03,0.5),fontsize=6.5)
    rho,n=draw_hit_consent(axes[1],df)
    with matplotlib.rc_context({'pdf.fonttype':42,'savefig.dpi':300}):
        save(fig,'fig_outcomes_by_region')
    return rho,n


def draw_hit_consent(ax, df):
    b=df.dropna(subset=['hit_rate_pct','consent_share_pct'])
    ax.axvline(b.consent_share_pct.median(),color=INK2,linewidth=0.8,linestyle=(0,(3,3)),zorder=1)
    ax.axhline(b.hit_rate_pct.median(),color=INK2,linewidth=0.8,linestyle=(0,(3,3)),zorder=1)
    ax.scatter(b.consent_share_pct,b.hit_rate_pct,s=6+100*np.sqrt(b.enf_searched_stops/b.enf_searched_stops.max()),
               color=CAT[1],alpha=0.65,edgecolor='white',linewidth=0.5,rasterized=True,zorder=3)
    offsets={'Hidalgo':(6,2),'Webb':(-6,4),'Starr':(6,5),'Harris':(-5,7),'Bexar':(6,5),
             'Cameron':(-6,-9),'Travis':(6,5),'Maverick':(6,5),'El Paso':(6,-9),'Dallas':(6,-9)}
    for r in b[b.county_name.isin(offsets)].itertuples():
        ax.scatter([r.consent_share_pct],[r.hit_rate_pct],
                   s=6+100*np.sqrt(r.enf_searched_stops/b.enf_searched_stops.max()),
                   color=P['raw'],edgecolor='white',linewidth=0.5,rasterized=True,zorder=4)
        dx,dy=offsets[r.county_name]
        ax.annotate(r.county_name,(r.consent_share_pct,r.hit_rate_pct),xytext=(dx,dy),
                    textcoords='offset points',fontsize=6.8,color=INK,ha='right' if dx<0 else 'left',
                    bbox={'facecolor':'white','edgecolor':'none','alpha':0.85,'pad':0.4})
    ax.set_xlim(max(0, 10 * np.floor(b.consent_share_pct.min() / 10)),
                min(100, 10 * np.ceil(b.consent_share_pct.max() / 10)))
    ax.set_ylim(max(0, 10 * np.floor(b.hit_rate_pct.min() / 10)),
                min(100, 10 * np.ceil(b.hit_rate_pct.max() / 10)))
    ax.set_xlabel('Consent Searches (%)',fontsize=7.5)
    ax.set_ylabel('Searches Finding Contraband (%)',fontsize=7.5)
    ax.set_title('Contraband Found vs. Consent Searches',fontsize=8.8)
    ax.tick_params(labelsize=7)
    ax.grid(False)
    ax.text(0.98,0.96,'Dashed lines: county medians',transform=ax.transAxes,
            ha='right',va='top',fontsize=6.2,color=INK2)
    return stats.spearmanr(b.consent_share_pct,b.hit_rate_pct)[0],len(b)


def chart_funnel(df, s):
    fig, ax = plt.subplots(figsize=(6.5, 2.7))
    e = np.geomspace(df.expected_stops.min() * 0.8, df.expected_stops.max() * 1.25, 200)
    lo, hi = stats.poisson.ppf(0.025, e) / e, stats.poisson.ppf(0.975, e) / e
    ax.fill_between(e, np.clip(lo, 0.02, None), hi, color="#e6e5de", linewidth=0,
                    label="Expected Range (95%)", rasterized=True)
    colors = {"Above expected": P["sequential"][-1], "Below expected": P["sequential"][2],
              "Not distinguishable from expected": P["context"]}
    names = {"Above expected": "Above Expected", "Below expected": "Below Expected",
             "Not distinguishable from expected": "Within expected range"}
    for sig, col in colors.items():
        r = df[df.sar_signal == sig]
        ax.scatter(r.expected_stops, r.sar_raw.clip(lower=0.03), s=13, color=col, edgecolor="white", linewidth=0.5,
                   label=f"{names[sig]} ({len(r)} Counties)" if sig != "Not distinguishable from expected" else names[sig], zorder=3, rasterized=True)
    ax.axhline(1, color=INK2, linewidth=0.8)
    df = df.assign(sar_plot=df.sar_raw.clip(lower=0.03))
    offsets = {"Presidio": (5, 3), "Starr": (5, 3), "Hidalgo": (5, 3),
               "Harris": (5, 3), "Dallas": (5, -7), "Borden": (5, 3)}
    for r in df[df.county_name.isin(offsets)].itertuples():
        ax.annotate(r.county_name, (r.expected_stops, r.sar_plot), xytext=offsets[r.county_name],
                    textcoords="offset points", fontsize=7.2, color=INK,
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 0.4})
    ax.set_xscale("log")
    ax.set_ylim(0.02, 40)
    log_ratio_axis(ax, "y", ticks=(0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20))
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_xlabel("Expected Traffic Enforcement Stops")
    ax.set_ylabel("Observed over Expected Ratio")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.23), ncol=2, fontsize=6.5,
              columnspacing=1.5).set_rasterized(True)
    ax.set_title("Stops vs. Traffic Expectation")
    tidy_axes(ax, "y")
    with matplotlib.rc_context({"pdf.fonttype": 42, "savefig.dpi": 300}):
        save(fig, "fig_funnel")


def chart_decomposition(df, s):
    b = df[df.enf_stops >= C.MIN_STOPS_FOR_RATE]
    state_citation = s["citation_rate_pct"]
    fig, ax = plt.subplots(figsize=(6.6, 4.0))
    ax.axvline(1, color=INK2, linewidth=0.8, linestyle=(0, (4, 3)), zorder=1)
    ax.axhline(state_citation, color=INK2, linewidth=0.8, linestyle=(0, (4, 3)), zorder=1)
    size = 6 + 170 * np.sqrt(b.enf_stops / b.enf_stops.max())
    for q, col in QUAD_COLORS.items():
        r = b[b.quadrant == q]
        ax.scatter(r.sar, r.citation_rate_pct, s=size[r.index], color=col, alpha=0.75, edgecolor="white", linewidth=0.7,
                   rasterized=True, zorder=3)
    labelled = []
    for quadrant, group in b.groupby("quadrant"):
        by_ratio = group.sort_values(["sar", "county_name"], ascending=[not quadrant.startswith("More"), True])
        by_citation = group.sort_values(["citation_rate_pct", "county_name"], ascending=["higher" not in quadrant, True])
        first = by_ratio.iloc[0]
        second = by_citation[by_citation.county_name != first.county_name].iloc[0]
        labelled.extend([first, second])
    offsets = {"Tarrant": (6, 4), "Dallas": (6, -4), "Rockwall": (6, 4), "Wichita": (-6, -7),
               "Dickens": (6, 4), "Caldwell": (6, -5), "Presidio": (-6, 4), "Stonewall": (6, 7)}
    for r in labelled:
        dx, dy = offsets.get(r.county_name, (6, 4))
        ax.annotate(r.county_name, (r.sar, r.citation_rate_pct), xytext=(dx, dy), textcoords="offset points",
                    ha="right" if dx < 0 else "left", fontsize=6.3, color=INK,
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.8, "pad": 0.4})
    ax.set_xlim(0.08, 25)
    ax.set_ylim(0, 85)
    log_ratio_axis(ax, "x")
    ax.text(0.085, state_citation + 1, f"Texas {state_citation:.1f}% cited", fontsize=6.4, color=INK2, va="bottom")
    ax.annotate("as expected", (1, 72), xytext=(-5, 0), textcoords="offset points",
                fontsize=6.4, color=INK2, rotation=90, va="center", ha="right")
    ax.set_xlabel("Stops vs. Traffic Expectation (Observed / Expected)")
    ax.set_ylabel("Stops with a Citation (%)")
    for x, y, text, ha in [(0.02,0.97,'Fewer stops, higher citations','left'),
                           (0.98,0.97,'More stops, higher citations','right'),
                           (0.02,0.03,'Fewer stops, lower citations','left'),
                           (0.98,0.03,'More stops, lower citations','right')]:
        ax.text(x,y,text,transform=ax.transAxes,ha=ha,va='top' if y>0.5 else 'bottom',
                fontsize=6.7,fontweight='bold',color='black',
                bbox={'facecolor':'white','edgecolor':'none','alpha':0.85,'pad':1})
    ax.set_title(f"Stop frequency and citation share, {len(b)} counties")
    ax.grid(False)
    with matplotlib.rc_context({"pdf.fonttype": 42, "savefig.dpi": 300}):
        save(fig, "fig_decomposition")


def main():
    df = pd.read_csv(C.OUTPUTS / f"county_metrics_{C.TARGET_MONTH}.csv", dtype={"fips": str})
    s = json.loads((C.OUTPUTS / "statewide_summary.json").read_text())
    metrics = {x["key"]: x for x in json.loads((C.SITE_DATA / "dashboard.json").read_text())["metrics"]}
    g = gpd.read_parquet(C.BUILD / "counties_figure.parquet").merge(df, on=["fips", "county_name"])
    g["label_pt"] = g.geometry.representative_point()
    ih = gpd.read_parquet(C.BUILD / "interstates_figure.parquet")

    C.REPORT_FIGURES.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(C.ROOT / "docs" / "assets" / "TX_-_DPS_Seal-background.png", C.REPORT_FIGURES / "dps_seal.png")
    map_figures(g, df, s, metrics, ih)
    loc = stop_location_figure(g, ih, s)
    chart_trend(s)
    chart_county_bins(df)
    chart_county_ranked(df)
    chart_race_counties(df, pd.read_csv(C.OUTPUTS / f"county_breakdown_{C.TARGET_MONTH}.csv"))
    chart_inspection_effect(df)
    chart_speeding_counties(df)
    rho_hit, n_hit = chart_outcomes_by_region(df, s)
    chart_funnel(df, s)
    chart_decomposition(df, s)

    facts = {**loc, "rho_hit_consent": float(rho_hit), "hit_consent_counties": int(n_hit)}
    (C.BUILD / "figure_facts.json").write_text(json.dumps(facts, indent=2))
    print(f"  figures -> {C.REPORT_FIGURES.relative_to(C.ROOT)} ({len(list(C.REPORT_FIGURES.glob('*.pdf')))} PDF figures)")


if __name__ == "__main__":
    main()
