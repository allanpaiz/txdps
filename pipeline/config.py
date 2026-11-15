from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


DATA = ROOT / "data"
THP_CSV_GLOB = DATA / "20??-??.csv"
ROADWAY_INVENTORY = DATA / "2018.zip"
COUNTY_BOUNDARIES = DATA / "Texas_County_Boundaries_Detailed_6577682458018361305.zip"
POPULATION = DATA / "co-est2018-alldata.csv"


BUILD = ROOT / "build"
DB_PATH = BUILD / "txdps.duckdb"
SQL_DIR = ROOT / "pipeline" / "sql"
OUTPUTS = ROOT / "outputs"
SITE_DATA = ROOT / "docs" / "data"
REPORT_GENERATED = ROOT / "report" / "generated"
REPORT_FIGURES = ROOT / "report" / "figures"


TARGET_MONTH = "2018-03"
PRIOR_MONTH = "2018-02"
BASELINE_MONTHS = ["2017-09", "2017-10", "2017-11", "2017-12", "2018-01", "2018-02"]
ALL_MONTHS = BASELINE_MONTHS + [TARGET_MONTH]
DAYS_IN_MONTH = {"2017-09": 30, "2017-10": 31, "2017-11": 30, "2017-12": 31,
                 "2018-01": 31, "2018-02": 28, "2018-03": 31}


DPS_REGIONS = {"1": "North Texas", "2": "Southeast Texas", "3": "South Texas",
               "4": "West Texas", "5": "Northwest Texas", "6": "Central Texas"}
ROAD_CLASSES = {"IH": "Interstate", "US/SH": "US & state highway", "FM/RR": "Farm/ranch-to-market road",
                "CITY_ST": "City street", "CNTY_RD": "County road", "OTHER": "Other", "Unknown": "Unknown"}


CRS_TEXAS = "EPSG:3083"
WEB_SIMPLIFY_TOLERANCE_M = 600
FIGURE_SIMPLIFY_TOLERANCE_M = 250
INTERSTATE_SIMPLIFY_TOLERANCE_M = 400


TEAL_BLUE = ["#E7F3EF", "#CBE7DF", "#A3D2CB", "#7AB7B9", "#5D98A8", "#447893", "#2E5778"]
PALETTE = {
    "sequential": [TEAL_BLUE[i] for i in (1, 2, 3, 5, 6)],
    "sequential7": TEAL_BLUE,
    "categorical": [TEAL_BLUE[6], TEAL_BLUE[3], "#E6BB70", "#E69B7B", TEAL_BLUE[1]],
    "quadrants": {
        "More stops, higher citation share": TEAL_BLUE[6],
        "More stops, lower citation share": TEAL_BLUE[3],
        "Fewer stops, higher citation share": "#E69B7B",
        "Fewer stops, lower citation share": "#E6BB70",
    },
    "highlight": TEAL_BLUE[6],
    "context": TEAL_BLUE[1],
    "raw": TEAL_BLUE[6],
    "highway": "#344C59",
    "highway_casing": "#FFF7E8",
    "county_border": "#5D7D85",
    "selected": "#E69B7B",
    "important": "#E6BB70",
    "suppressed": "#F3F2EE",
}
QUANTILE_CLASSES = 5
COUNTY_STOP_BAND_EDGES = [100, 700, 1700, 2700, 3700]
METRES_PER_MILE = 1609.344


ROADBEDS_FOR_TOTALS = ["KG", "AG", "XG"]
PUBLISHED_2018_STATEWIDE_DVMT = 772_705_427.482
PUBLISHED_2018_ON_SYSTEM_DVMT = 556_901_648.533


MIN_STOPS_FOR_RATE = 50
MIN_SEARCHES_FOR_HIT_RATE = 20
MIN_STOPS_FOR_CHANGE = 50


OFFICIAL_2018 = {
    "total_stops": 2_953_280,
    "citation_stops": 1_027_644,
    "warning_stops": 1_925_636,
    "race_share": {
        "Alaska Native or American Indian": 0.13,
        "Asian or Pacific Islander": 1.91,
        "Black": 10.93,
        "Hispanic or Latino": 43.90,
        "White": 43.13,
    },
}
