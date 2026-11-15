import json
import warnings

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely

import config as C

warnings.filterwarnings("ignore", message="Measured")
ROADWAY_GDB = f"zip://{C.ROADWAY_INVENTORY}!2018_Roadway_Inventory.gdb"


def load_boundaries() -> gpd.GeoDataFrame:
    g = gpd.read_file(f"zip://{C.COUNTY_BOUNDARIES}")
    g = g.rename(columns={"CNTY_NM": "county_name", "CNTY_FIPS": "fips", "CNTY_NBR": "txdot_county_nbr",
                          "DPS_NBR": "dps_county_nbr", "DIST_NM": "txdot_district"})
    g["fips"] = g["fips"].astype(str).str.zfill(5)
    g = g[["county_name", "fips", "txdot_county_nbr", "dps_county_nbr", "txdot_district", "geometry"]]
    g = g.to_crs(C.CRS_TEXAS)
    g["area_sq_mi"] = g.geometry.area / 2_589_988.11
    assert len(g) == 254 and g.fips.is_unique, "expected 254 unique counties"
    return g.sort_values("county_name").reset_index(drop=True)


def load_population() -> pd.DataFrame:
    p = pd.read_csv(C.POPULATION, encoding="latin-1", dtype={"STATE": str, "COUNTY": str})
    p = p[(p.SUMLEV == 50) & (p.STATE == "48")]
    p = pd.DataFrame({"fips": "48" + p.COUNTY.str.zfill(3), "pop_2018": p.POPESTIMATE2018})
    assert len(p) == 254
    return p


def load_traffic_exposure() -> pd.DataFrame:


    seg = pyogrio.read_dataframe(ROADWAY_GDB, layer="TxDOT_Roadway_Inventory", read_geometry=False,
                                 columns=["CO", "RDBD_ID", "ADMIN", "LEN_SEC", "DVMT", "DTRKVMT"])
    seg = seg[seg.RDBD_ID.isin(C.ROADBEDS_FOR_TOTALS)].copy()
    seg["on_system"] = seg.ADMIN == 1

    total, on_sys = seg.DVMT.sum(), seg.loc[seg.on_system, "DVMT"].sum()
    assert abs(total - C.PUBLISHED_2018_STATEWIDE_DVMT) < 1, f"DVMT reconciliation failed: {total:,.3f}"
    assert abs(on_sys - C.PUBLISHED_2018_ON_SYSTEM_DVMT) < 1, f"On-system reconciliation failed: {on_sys:,.3f}"
    print(f"  DVMT reconciles to TxDOT published totals: all roads {total:,.3f}; on-system {on_sys:,.3f}")

    by_cty = seg.groupby("CO").agg(dvmt_all_roads=("DVMT", "sum"), centerline_miles_all=("LEN_SEC", "sum"))
    on = seg[seg.on_system].groupby("CO").agg(dvmt_on_system=("DVMT", "sum"), dtrkvmt_on_system=("DTRKVMT", "sum"),
                                              centerline_miles_on_system=("LEN_SEC", "sum"))
    out = by_cty.join(on).reset_index().rename(columns={"CO": "txdot_county_nbr"})
    out["txdot_county_nbr"] = out.txdot_county_nbr.astype(int)
    assert len(out) == 254
    return out


def load_interstates() -> gpd.GeoDataFrame:


    ih = pyogrio.read_dataframe(ROADWAY_GDB, layer="TxDOT_Roadway_Inventory_wAssets",
                                columns=["HWY", "HSYS", "RDBD_ID"],
                                where="HSYS = 'IH' AND RDBD_ID = 'KG'")
    assert len(ih) > 1000, "interstate segments not found in the roadway inventory"
    ih = ih.to_crs(C.CRS_TEXAS).dissolve("HWY").reset_index()
    ih["name"] = "I-" + ih.HWY.str[2:].str.lstrip("0")

    ih["geometry"] = shapely.simplify(shapely.line_merge(ih.geometry.values), C.INTERSTATE_SIMPLIFY_TOLERANCE_M)
    return ih[["name", "geometry"]].sort_values("name").reset_index(drop=True)


def display_outlines(g: gpd.GeoDataFrame, tolerance_m: float) -> gpd.GeoDataFrame:


    def drop_slivers(geom):
        parts = [p for p in shapely.get_parts(geom) if p.area > 2e6]
        return shapely.MultiPolygon(parts) if len(parts) > 1 else parts[0]
    cleaned = shapely.set_precision(np.array([drop_slivers(x) for x in g.geometry.values]), 1.0)
    out = g[["fips", "county_name"]].copy()
    return gpd.GeoDataFrame(out, geometry=shapely.coverage_simplify(cleaned, tolerance_m), crs=g.crs)


def write_web_geojson(gdf: gpd.GeoDataFrame, filename: str) -> None:


    gj = json.loads(gdf.to_json(drop_id=True))

    def rnd(c):
        return [rnd(x) for x in c] if isinstance(c[0], list) else [round(c[0]), round(c[1])]
    for f in gj["features"]:
        f["geometry"]["coordinates"] = rnd(f["geometry"]["coordinates"])
    gj.pop("crs", None)
    C.SITE_DATA.mkdir(parents=True, exist_ok=True)
    path = C.SITE_DATA / filename
    path.write_text(json.dumps(gj, separators=(",", ":")))
    print(f"  wrote docs/data/{filename} ({path.stat().st_size / 1e3:,.0f} KB)")


def main() -> None:
    C.BUILD.mkdir(exist_ok=True)
    C.OUTPUTS.mkdir(exist_ok=True)

    g = load_boundaries()
    ref = (g.drop(columns="geometry")
             .merge(load_population(), on="fips", how="left", validate="1:1")
             .merge(load_traffic_exposure(), on="txdot_county_nbr", how="left", validate="1:1"))
    assert ref.notna().all().all(), "every county must have population and DVMT"

    with duckdb.connect(str(C.DB_PATH)) as con:
        con.register("ref_df", ref)
        con.execute("CREATE OR REPLACE TABLE county_reference AS SELECT * FROM ref_df")
    ref.to_csv(C.OUTPUTS / "county_reference.csv", index=False)

    display_outlines(g, C.FIGURE_SIMPLIFY_TOLERANCE_M).to_parquet(C.BUILD / "counties_figure.parquet")
    write_web_geojson(display_outlines(g, C.WEB_SIMPLIFY_TOLERANCE_M).rename(columns={"county_name": "name"}),
                      "counties.geojson")
    ih = load_interstates()
    ih.to_parquet(C.BUILD / "interstates_figure.parquet")
    write_web_geojson(ih, "interstates.geojson")
    print(f"  county_reference: {len(ref)} counties, population {ref.pop_2018.sum():,}; {len(ih)} interstate routes")


if __name__ == "__main__":
    main()
