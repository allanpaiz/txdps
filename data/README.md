# Source downloads

Place these public files in `data/` using the names below. The dashboard includes generated county summaries and does not need these files to run.

| File | Source |
|---|---|
| `2017-09.csv`, `2017-10.csv`, `2017-11.csv`, `2017-12.csv`, `2018-01.csv`, `2018-02.csv`, `2018-03.csv` | [Texas DPS monthly THP violation extracts](https://www.dps.texas.gov/section/highway-patrol/texas-highway-patrol-high-value-data-sets) |
| `2018.zip` | [TxDOT 2018 Roadway Inventory](https://www.txdot.gov/data-maps/roadway-inventory.html), certified FileGDB containing `2018_Roadway_Inventory.gdb` |
| `Texas_County_Boundaries_Detailed_6577682458018361305.zip` | [TxDOT detailed county boundaries](https://gis-txdot.opendata.arcgis.com/datasets/TXDOT::texas-county-boundaries-detailed), shapefile ZIP; rename the download to this filename |
| `co-est2018-alldata.csv` | [Census Vintage 2018 county population](https://www2.census.gov/programs-surveys/popest/datasets/2010-2018/counties/totals/co-est2018-alldata.csv) |

The [DPS field dictionary](https://www.dps.texas.gov/HighwayPatrol/docs/thpViolationsColNames_2013-2020.pdf) defines the extract columns. Paths and reporting months are set in `pipeline/config.py`.

The build checks for 254 counties and reconciles daily vehicle miles with TxDOT's 2018 totals: 772,705,427.482 across all roads and 556,901,648.533 on the state highway system. Raw downloads and the working database are excluded from the public package.
