(() => {
  "use strict";

  const isNum = (v) => Number.isFinite(v);
  const FORMAT = {
    int: (v) => d3.format(",")(Math.round(v)),
    dec1: d3.format(",.1f"),
    dec2: d3.format(".2f"),
    pct: (v) => d3.format(".1f")(v) + "%",
    pct_signed: (v) => d3.format("+.1f")(v) + "%",
    ratio: (v) => d3.format(".2f")(v) + "×",
    signed: (v) => (v > 0 ? "+" : "") + v,
  };
  const fmt = (f, v) => (isNum(v) ? FORMAT[f](v) : "–");
  const fmtBreak = (format, b) => {
    const s = b.toLocaleString("en-US", { maximumFractionDigits: 2 });
    if (format === "pct") return s + "%";
    if (format === "pct_signed") return (b > 0 ? "+" : "") + s + "%";
    if (format === "ratio") return s + "×";
    return s;
  };
  const $ = (sel) => document.querySelector(sel);
  const el = (tag, attrs = {}, text) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    return n;
  };

  const state = { data: null, geo: null, ih: null, byFips: new Map(), metric: null, selected: null, tab: "map",
    sort: { key: "stops", dir: -1 }, showIH: true };
  let P = null;

  Promise.all([d3.json("data/dashboard.json"), d3.json("data/counties.geojson"), d3.json("data/interstates.geojson")])
    .then(([data, geo, ih]) => {
      state.data = data;
      state.geo = geo;
      state.ih = ih;
      P = data.palette;
      Object.entries({ accent: P.sequential[4], selected: P.selected, important: P.important,
        highway: P.highway, "highway-casing": P.highway_casing, "county-border": P.county_border })
        .forEach(([key, value]) => document.documentElement.style.setProperty(`--${key}`, value));
      data.counties.forEach((c) => state.byFips.set(c.fips, c));
      const h = new URLSearchParams(location.hash.slice(1));
      state.metric = data.metrics.find((m) => m.key === h.get("metric")) || data.metrics[0];
      state.selected = state.byFips.has(h.get("county")) ? h.get("county") : null;
      state.tab = ["map", "table"].includes(h.get("tab")) ? h.get("tab") : "map";
      renderStats();
      initControls();
      initMap();
      updateMap();
      renderPanel();
      setTab(state.tab, { scroll: false });
      if (state.selected) zoomToCounty(state.selected, 0);
    })
    .catch((err) => {
      console.error(err);
      $("#stats").textContent = "Could not load the data. Serve this folder over HTTP (for example: python -m http.server).";
    });

  function syncHash() {
    const p = new URLSearchParams();
    if (state.tab !== "map") p.set("tab", state.tab);
    p.set("metric", state.metric.key);
    if (state.selected) p.set("county", state.selected);
    history.replaceState(null, "", "#" + p.toString());
  }

  function setTab(tab, { scroll = true } = {}) {
    state.tab = tab;
    document.querySelectorAll(".tabs [role=tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== "view-" + tab));
    if (tab === "table") renderTable();
    if (scroll) window.scrollTo({ top: 0 });
    syncHash();
  }

  function select(fips, { zoom = false } = {}) {
    state.selected = fips && state.byFips.has(fips) ? fips : null;
    updateSelection();
    renderPanel();
    markTableSelection();
    syncHash();
    if (zoom && state.selected) zoomToCounty(state.selected);
  }

  function renderStats() {
    const s = state.data.summary;
    const items = [
      [FORMAT.int(s.stops), `traffic stops, ${s.target_month_label.replace("Mar", "March")}`],
      [FORMAT.int(s.stops_per_day), "per day"],
      [FORMAT.pct_signed(s.pct_change_vs_6mo), "vs. Sep–Feb average (per day)"],
      [String(s.counties_with_stops), "of 254 counties with stops"],
      [FORMAT.pct(s.top_shares_pct["10"]), "of stops in the top 10 counties"],
      [String(s.counties_for_half), "counties account for half of all stops"],
      [FORMAT.int(s.median_county_stops), "median stops per county"],
    ];
    const host = $("#stats");
    host.replaceChildren(...items.map(([v, l]) => {
      const d = el("div", { class: "stat" });
      d.append(el("div", { class: "v" }, v), el("div", { class: "l" }, l));
      return d;
    }));
    $("#generated").textContent = s.generated;
    const src = $("#sources");
    state.data.sources.forEach((x, i) => {
      if (i) src.append(document.createTextNode(" · "));
      src.append(el("a", { href: x.url, target: "_blank", rel: "noopener" }, x.name));
    });
  }

  const MAP_W = 900, MAP_H = 830;
  let mapSvg, mapRoot, countyPaths, ihPaths, ihCasingPaths, selOutline, selCasing, labelLayer, zoom, path;

  const rampFor = (ramp, n) => (n >= ramp.length ? ramp : d3.range(n).map((i) => ramp[Math.round((i * (ramp.length - 1)) / Math.max(1, n - 1))]));
  const rampOf = (m) => rampFor(m.breaks.length === 4 ? P.sequential : P.sequential7, m.breaks.length + 1);
  function colorOf(m) {
    const s = d3.scaleThreshold().domain(m.breaks).range(rampOf(m));
    return (v) => (isNum(v) ? s(v) : null);
  }
  const classOf = (m, v) => (isNum(v) ? d3.bisectRight(m.breaks, v) : -1);

  function initMap() {
    mapSvg = d3.select("#map").attr("viewBox", `0 0 ${MAP_W} ${MAP_H}`);
    const proj = d3.geoIdentity().reflectY(true).fitExtent([[6, 6], [MAP_W - 6, MAP_H - 6]], state.geo);
    path = d3.geoPath(proj);
    const defs = mapSvg.append("defs");
    const pat = defs.append("pattern").attr("id", "hatch").attr("patternUnits", "userSpaceOnUse")
      .attr("width", 6).attr("height", 6).attr("patternTransform", "rotate(45)");
    pat.append("rect").attr("width", 6).attr("height", 6).attr("fill", P.suppressed);
    pat.append("line").attr("x1", 0).attr("y1", 0).attr("x2", 0).attr("y2", 6).attr("stroke", "#cfcdc5").attr("stroke-width", 1.5);

    mapRoot = mapSvg.append("g");
    countyPaths = mapRoot.append("g").selectAll("path").data(state.geo.features).join("path")
      .attr("class", "county").attr("d", path)
      .on("pointermove", (e, f) => showTooltip(e, countyTooltip(state.byFips.get(f.properties.fips))))
      .on("pointerleave", hideTooltip)
      .on("click", (e, f) => select(f.properties.fips === state.selected ? null : f.properties.fips));
    ihCasingPaths = mapRoot.append("g").selectAll("path").data(state.ih.features).join("path").attr("class", "interstate-casing").attr("d", path);
    ihPaths = mapRoot.append("g").selectAll("path").data(state.ih.features).join("path").attr("class", "interstate").attr("d", path);
    selCasing = mapRoot.append("path").attr("class", "selected-casing");
    selOutline = mapRoot.append("path").attr("class", "selected-outline");
    labelLayer = mapRoot.append("g").attr("display", "none");
    labelLayer.selectAll("text").data(state.geo.features).join("text").attr("class", "county-label")
      .attr("transform", (f) => `translate(${labelPoint(f)})`).attr("dy", "0.35em").text((f) => f.properties.name);

    zoom = d3.zoom().scaleExtent([1, 14]).translateExtent([[0, 0], [MAP_W, MAP_H]]).clickDistance(4)
      .on("zoom", (e) => {
        mapRoot.attr("transform", e.transform);
        const k = e.transform.k;
        countyPaths.style("stroke-width", 0.6 / k);
        ihCasingPaths.style("stroke-width", 2.1 / Math.sqrt(k));
        ihPaths.style("stroke-width", 1 / Math.sqrt(k));
        selCasing.style("stroke-width", 4.2 / k);
        selOutline.style("stroke-width", 2.8 / k);
        labelLayer.attr("display", k >= 3 ? null : "none").selectAll("text").style("font-size", `${11 / k}px`).style("stroke-width", 3 / k);
      });
    mapSvg.call(zoom).on("dblclick.zoom", null);
    updateSelection();
  }
  function labelPoint(f) {
    const g = f.geometry;
    if (g.type === "Polygon") return path.centroid(f);
    const parts = g.coordinates.map((c) => ({ type: "Polygon", coordinates: c }));
    return path.centroid(parts.reduce((a, b) => (path.area(b) > path.area(a) ? b : a)));
  }

  function updateMap() {
    const m = state.metric, color = colorOf(m);
    countyPaths.transition().duration(250).style("fill", (f) => color(state.byFips.get(f.properties.fips)[m.key]) || "url(#hatch)");
    renderLegend();
    const d = $("#metric-desc");
    d.replaceChildren(document.createTextNode(m.description + " "));
    if (m.caution) d.append(el("span", { class: "caution" }, m.caution));
  }

  function updateSelection() {
    const f = state.selected && state.geo.features.find((x) => x.properties.fips === state.selected);
    selOutline.attr("d", f ? path(f) : null);
    selCasing.attr("d", f ? path(f) : null);
  }

  function zoomToCounty(fips, duration = 650) {
    const f = state.geo.features.find((x) => x.properties.fips === fips);
    const [[x0, y0], [x1, y1]] = path.bounds(f);
    const k = Math.min(5, 0.22 / Math.max((x1 - x0) / MAP_W, (y1 - y0) / MAP_H));
    const t = d3.zoomIdentity.translate(MAP_W / 2, MAP_H / 2).scale(k).translate(-(x0 + x1) / 2, -(y0 + y1) / 2);
    mapSvg.transition().duration(duration).call(zoom.transform, t);
  }

  function renderLegend() {
    const m = state.metric, host = $("#legend"), ramp = rampOf(m), edges = [null, ...m.breaks, null];
    host.replaceChildren(el("span", { class: "legend-title" }, m.label));
    const items = ramp.map((color, i) => {
      const lo = edges[i], hi = edges[i + 1];
      const label = lo === null ? `< ${fmtBreak(m.format, hi)}` : hi === null ? `≥ ${fmtBreak(m.format, lo)}` : `${fmtBreak(m.format, lo)} – ${fmtBreak(m.format, hi)}`;
      return { color, label, n: m.counts[i], idx: i };
    });
    const missing = state.data.counties.filter((c) => !isNum(c[m.key])).length;
    if (missing) items.push({ hatched: true, label: "Too few stops", n: missing, idx: -1 });
    items.forEach((it) => {
      const item = el("span", { class: "legend-item" });
      const sw = el("span", { class: "swatch" + (it.hatched ? " hatched" : "") });
      if (!it.hatched) sw.style.background = it.color;
      item.append(sw, document.createTextNode(it.label + " "), el("span", { class: "n" }, `(${it.n})`));
      item.addEventListener("pointerenter", () => countyPaths.classed("dim", (f) => classOf(m, state.byFips.get(f.properties.fips)[m.key]) !== it.idx));
      item.addEventListener("pointerleave", () => countyPaths.classed("dim", false));
      host.append(item);
    });
    if (state.showIH) {
      const key = el("span", { class: "legend-item" });
      key.append(el("span", { class: "highway-swatch" }), document.createTextNode("Interstate highway"));
      host.append(key);
    }
  }
  const tip = $("#tooltip");
  function showTooltip(event, node) {
    tip.replaceChildren(node);
    tip.hidden = false;
    const pad = 14, r = tip.getBoundingClientRect();
    let x = event.clientX + pad, y = event.clientY + pad;
    if (x + r.width > window.innerWidth - 8) x = event.clientX - r.width - pad;
    if (y + r.height > window.innerHeight - 8) y = event.clientY - r.height - pad;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  function hideTooltip() { tip.hidden = true; }
  function tooltipNode(title, value, valueLabel, rows = []) {
    const frag = document.createDocumentFragment();
    frag.append(el("div", { class: "tt-title" }, title));
    if (value !== undefined) frag.append(el("div", { class: "tt-value" }, value), el("div", { class: "tt-label" }, valueLabel || ""));
    if (rows.length) {
      const g = el("div", { class: "tt-rows" });
      rows.forEach(([k, v]) => g.append(el("span", {}, k), el("span", {}, v)));
      frag.append(g);
    }
    return frag;
  }
  function countyTooltip(c) {
    const m = state.metric;
    return tooltipNode(`${c.name} County`, fmt(m.format, c[m.key]), m.label, [
      ["Traffic stops", `${FORMAT.int(c.stops)}  (#${c.rank})`],
      ["Inspections", fmt("pct", c.inspection_share_pct)],
      ["Stops vs. traffic", fmt("ratio", c.sar)],
      ["Cited", fmt("pct", c.citation_rate_pct)],
    ]);
  }

  function renderPanel() {
    const host = $("#panel"), s = state.data.summary;
    const c = state.selected ? state.byFips.get(state.selected) : null;
    host.replaceChildren();

    const head = el("div", { class: "panel-head" });
    const title = el("div");
    title.append(el("h2", {}, c ? `${c.name} County` : "Texas"));
    title.append(el("p", { class: "meta" }, c ? `${c.region || "–"} region · DPS district ${c.district || "–"} · pop. ${FORMAT.int(c.pop_2018)}`
      : "All 254 counties · click a county or search to see its profile"));
    head.append(title);
    if (c) {
      const close = el("button", { type: "button", class: "close", "aria-label": "Back to Texas" }, "×");
      close.addEventListener("click", () => select(null));
      head.append(close);
    }
    host.append(head);

    const figs = el("div", { class: "figures" });
    const fig = (label, value, note) => {
      const d = el("div", { class: "fig" });
      d.append(el("div", { class: "l" }, label), el("div", { class: "v" }, value));
      if (note) d.append(el("div", { class: "n" }, note));
      figs.append(d);
    };
    if (c) {
      fig("Traffic stops", FORMAT.int(c.stops), `rank ${c.rank} of 254 · ${FORMAT.dec1(c.share_pct)}% of Texas`);
      fig("Per day", FORMAT.dec1(c.stops_per_day), `${fmt("pct_signed", c.pct_change_vs_prior_month)} vs. Feb · ${fmt("pct_signed", c.pct_change_vs_6mo)} vs. Sep–Feb`);
      fig("Commercial inspections", FORMAT.int(c.inspection_stops), `${fmt("pct", c.inspection_share_pct)} of stops`);
      fig("Stops vs. traffic", fmt("ratio", c.sar), c.sar_signal.toLowerCase());
      fig("Cited / searched", `${fmt("pct", c.citation_rate_pct)} / ${fmt("pct", c.search_rate_pct)}`,
        isNum(c.hit_rate_pct) ? `contraband in ${FORMAT.pct(c.hit_rate_pct)} of searches` : "hit rate hidden (few searches)");
      fig("Per 10,000 residents", fmt("dec1", c.stops_per_10k_pop), `Texas ${FORMAT.dec1(s.stops_per_10k_pop)}`);
      fig("Per million vehicle miles", fmt("dec1", c.stops_per_m_vmt));
    } else {
      fig("Traffic stops", FORMAT.int(s.stops), `from ${FORMAT.int(s.tickets)} tickets, ${FORMAT.int(s.violation_records)} violation records`);
      fig("Per day", FORMAT.int(s.stops_per_day), `${FORMAT.pct_signed(s.pct_change_vs_prior_month)} vs. Feb · ${FORMAT.pct_signed(s.pct_change_vs_6mo)} vs. Sep–Feb`);
      fig("Commercial inspections", FORMAT.int(s.inspection_stops), `${FORMAT.pct(s.inspection_share_pct)} of stops`);
      fig("Troopers making stops", FORMAT.int(s.troopers));
      fig("Cited / searched", `${FORMAT.pct(s.citation_rate_pct)} / ${FORMAT.pct(s.search_rate_pct)}`, `contraband in ${FORMAT.pct(s.hit_rate_pct)} of searches`);
      fig("Per 10,000 residents", FORMAT.dec1(s.stops_per_10k_pop), "traffic enforcement stops");
      fig("Per million vehicle miles", FORMAT.dec1(s.stops_per_m_vmt), "state highways, March");
    }
    host.append(figs);

    host.append(el("h3", {}, "Stops per day by month"));
    const trend = el("div", { class: "chart" });
    host.append(trend);
    miniTrend(trend, c ? c.monthly : s.monthly);

    const mix = c ? c.mix : s.mix;
    const total = (o) => d3.sum(Object.values(o || {}));
    [["outcome", "Stop outcome (all stops)", (k) => k.replace(" recorded", "")],
      ["race", "Driver race/ethnicity", (k) => k.replace(" or Pacific Islander", "/Pac. Isl.").replace("Alaska Native or American Indian", "Am. Indian/AK Native")]]
      .forEach(([key, label, name]) => {
        host.append(el("h3", {}, label));
        const own = mix[key] || {}, tx = s.mix[key], ownTotal = total(own) || 1, txTotal = total(tx) || 1;
        Object.entries(tx).sort((a, b) => b[1] - a[1]).slice(0, 5).forEach(([cat]) => {
          const share = (own[cat] || 0) / ownTotal, txShare = tx[cat] / txTotal;
          const row = el("div", { class: "mix-row" });
          const bar = el("div", { class: "bar" });
          const fill = el("span");
          fill.style.width = (100 * share).toFixed(1) + "%";
          fill.style.background = P.raw;
          bar.append(fill);
          if (c) {
            const tick = el("i", { title: `Texas ${(100 * txShare).toFixed(1)}%` });
            tick.style.left = `calc(${(100 * txShare).toFixed(1)}% - 1px)`;
            bar.append(tick);
          }
          row.append(el("span", {}, name(cat)), bar, el("span", { class: "pct" }, d3.format(".0%")(share)));
          host.append(row);
        });
      });
    if (c) host.append(el("p", { class: "mix-key" }, "Black tick = Texas share."));
  }

  function miniTrend(host, monthly) {
    const days = state.data.month_days, labels = state.data.month_labels.map((l) => l.slice(0, 3));
    const perDay = monthly.map((v, i) => v / days[i]);
    const base = d3.sum(monthly.slice(0, 6)) / d3.sum(days.slice(0, 6));
    const w = Math.max(260, host.clientWidth || 320), h = 104, m = { t: 14, r: 4, b: 16, l: 4 };
    const x = d3.scaleBand().domain(d3.range(perDay.length)).range([m.l, w - m.r]).padding(0.3);
    const y = d3.scaleLinear().domain([0, (d3.max(perDay) || 1) * 1.08]).range([h - m.b, m.t]);
    const svg = d3.select(host).append("svg").attr("viewBox", `0 0 ${w} ${h}`);
    const last = perDay.length - 1;
    svg.append("g").selectAll("rect").data(perDay).join("rect").attr("x", (d, i) => x(i)).attr("width", x.bandwidth())
      .attr("y", (d) => y(d)).attr("height", (d) => y(0) - y(d)).attr("rx", 2).attr("fill", (d, i) => (i === last ? P.highlight : P.context));
    svg.append("line").attr("class", "ref-line").attr("x1", m.l).attr("x2", w - m.r).attr("y1", y(base)).attr("y2", y(base));
    const fmtV = (d) => (d >= 100 ? FORMAT.int(d) : FORMAT.dec1(d));
    svg.append("g").selectAll("text").data(perDay).join("text").attr("x", (d, i) => x(i) + x.bandwidth() / 2).attr("y", (d) => y(d) - 3)
      .attr("text-anchor", "middle").attr("font-size", 9.5).attr("class", (d, i) => (i === last ? "strong" : "muted")).text(fmtV);
    svg.append("g").selectAll("text").data(labels).join("text").attr("x", (d, i) => x(i) + x.bandwidth() / 2).attr("y", h - 3)
      .attr("text-anchor", "middle").attr("font-size", 9.5).text((d) => d);
    svg.append("g").selectAll("rect").data(perDay).join("rect").attr("class", "hit").attr("x", (d, i) => x(i) - 3).attr("width", x.bandwidth() + 6)
      .attr("y", 0).attr("height", h)
      .on("pointermove", (e, d) => {
        const i = perDay.indexOf(d);
        showTooltip(e, tooltipNode(state.data.month_labels[i], `${fmtV(d)} per day`, `${FORMAT.int(monthly[i])} stops in ${days[i]} days`,
          [["vs. Sep–Feb average", FORMAT.pct_signed(100 * (d / base - 1))]]));
      })
      .on("pointerleave", hideTooltip);
  }


  const COLUMNS = [
    { key: "_pos", label: "#", title: "Position in the current sort order" },
    { key: "name", label: "County", text: true },
    { key: "rank", label: "Rank", f: "int", title: "Rank by all stops" },
    { key: "stops", label: "Stops (% TX)", f: "int", share: "share_pct", title: "All stops and share of statewide stops" },
    { key: "stops_per_day", label: "Per day", f: "int" },
    { key: "pct_change_vs_prior_month", label: "Δ Feb", f: "pct_signed", title: "Percentage change in daily stops vs. February" },
    { key: "pct_change_vs_6mo", label: "Δ 6 mo.", f: "pct_signed", title: "Percentage change in daily stops vs. September to February" },
    { key: "tickets", label: "Tickets", f: "int" },
    { key: "warning_only_stops", label: "Warn. only", f: "int", title: "All stops with warnings and no citation" },
    { key: "no_violation_stops", label: "No viol.", f: "int", title: "All stops with no violation recorded" },
    { key: "inspection_stops", label: "Insp.", f: "int", share: "inspection_share_pct", title: "Commercial inspections and share of county stops" },
    { key: "pop_2018", label: "Pop. (k)", f: "int", divisor: 1000, title: "2018 population in thousands" },
    { key: "vmt_month_millions", label: "VMT (M)", f: "int", title: "March state highway vehicle miles in millions" },
    { key: "stops_per_10k_pop", label: "Per 10k", f: "int", title: "Enforcement stops per 10,000 residents" },
    { key: "stops_per_m_vmt", label: "Per M VMT", f: "dec1", title: "Enforcement stops per million state highway vehicle miles" },
    { key: "sar", label: "Obs/Exp", f: "dec2", title: "Observed over expected enforcement stops, Empirical Bayes estimate" },
  ];

  function renderTable() {
    const table = $("#county-table"), { key, dir } = state.sort;
    const q = $("#table-filter").value.trim().toLowerCase();
    const rows = state.data.counties.filter((c) => !q || c.name.toLowerCase().includes(q) || (c.region || "").toLowerCase().includes(q))
      .sort((a, b) => {
        const va = a[key], vb = b[key];
        if (typeof va === "string" || typeof vb === "string") return dir * String(va || "").localeCompare(String(vb || ""));
        if (!isNum(va)) return 1;
        if (!isNum(vb)) return -1;
        return dir * (va - vb);
      });
    const thead = el("thead"), tr = el("tr");
    COLUMNS.forEach((c) => {
      const th = el("th", { scope: "col", tabindex: "0", title: c.title || c.label }, c.label);
      if (c.key === key) th.setAttribute("aria-sort", dir > 0 ? "ascending" : "descending");
      if (c.key !== "_pos") {
        const sort = () => { state.sort = { key: c.key, dir: c.key === key ? -dir : c.text ? 1 : -1 }; renderTable(); };
        th.addEventListener("click", sort);
        th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sort(); } });
      }
      tr.append(th);
    });
    thead.append(tr);
    const tbody = el("tbody");
    rows.forEach((c, i) => {
      const r = el("tr", { "data-fips": c.fips, tabindex: "0", "aria-label": `Open ${c.name} County on the map` });
      COLUMNS.forEach((col) => {
        const v = col.key === "_pos" ? i + 1 : c[col.key];
        const text = col.key === "_pos" ? String(v) : col.text ? v || "–" :
          fmt(col.f, isNum(v) ? v / (col.divisor || 1) : v) + (col.share ? ` (${fmt("pct", c[col.share])})` : "");
        r.append(el("td", isNum(v) || col.text ? {} : { class: "na" }, text));
      });
      const open = () => { select(c.fips, { zoom: true }); setTab("map"); };
      r.addEventListener("click", open);
      r.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
      tbody.append(r);
    });
    table.replaceChildren(thead, tbody);
    markTableSelection();
    $("#table-key").textContent = "Key: # = position in the current sort; Rank = county rank by all stops; % TX = share of statewide stops; " +
      "Δ Feb and Δ 6 mo. = percentage change in daily stops; Tickets = distinct source documents; Warn. only = warnings without a citation; " +
      "No viol. = no violation recorded; Insp. = inspection count (share of county stops); Pop. (k) = population in thousands; " +
      "VMT (M) = estimated March state highway vehicle miles in millions; Per 10k and Per M VMT use enforcement stops; " +
      "Obs/Exp = observed over expected enforcement stops, Empirical Bayes estimate; – = unavailable or withheld.";
  }
  function markTableSelection() {
    document.querySelectorAll("#county-table tbody tr").forEach((r) => r.classList.toggle("selected", r.dataset.fips === state.selected));
  }

  function downloadCsv() {
    const skip = new Set(["mix", "monthly"]);
    const cols = Object.keys(state.data.counties[0]).filter((k) => !skip.has(k));
    const months = state.data.months.map((m) => "stops_" + m.replace("-", "_"));
    const esc = (v) => (v === null || v === undefined ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
    const lines = [cols.concat(months).join(",")].concat(state.data.counties.map((c) => cols.map((k) => esc(c[k])).concat(c.monthly).join(",")));
    const a = el("a", { href: URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" })), download: "thp_stops_by_county_2018-03.csv" });
    document.body.append(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
  }

  function initControls() {
    const host = $("#metric-buttons");
    state.data.metrics.forEach((m) => {
      const button = el("button", { type: "button", "data-metric": m.key, "aria-pressed": String(m.key === state.metric.key), title: m.label }, m.button);
      button.addEventListener("click", () => {
        state.metric = m;
        host.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.metric === m.key)));
        updateMap();
        syncHash();
      });
      host.append(button);
    });

    const list = $("#county-list");
    state.data.counties.slice().sort((a, b) => a.name.localeCompare(b.name)).forEach((c) => list.append(el("option", { value: c.name })));
    $("#county-search").addEventListener("change", (e) => {
      const c = state.data.counties.find((x) => x.name.toLowerCase() === e.target.value.trim().toLowerCase());
      if (c) select(c.fips, { zoom: true });
    });
    $("#toggle-ih").addEventListener("change", (e) => {
      state.showIH = e.target.checked;
      ihPaths.attr("display", state.showIH ? null : "none");
      ihCasingPaths.attr("display", state.showIH ? null : "none");
      renderLegend();
    });
    $("#zoom-in").addEventListener("click", () => mapSvg.transition().duration(300).call(zoom.scaleBy, 1.6));
    $("#zoom-out").addEventListener("click", () => mapSvg.transition().duration(300).call(zoom.scaleBy, 1 / 1.6));
    $("#zoom-reset").addEventListener("click", () => mapSvg.transition().duration(500).call(zoom.transform, d3.zoomIdentity));
    document.querySelectorAll(".tabs [role=tab]").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
    $("#table-filter").addEventListener("input", renderTable);
    $("#download-csv").addEventListener("click", downloadCsv);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.selected) select(null); });
    let t;
    window.addEventListener("resize", () => {
      clearTimeout(t);
      t = setTimeout(() => {
        if (state.tab === "map") renderPanel();
      }, 150);
    });
  }
})();
