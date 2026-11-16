# DPS THP Traffic Stops, March 2018

County distribution of Texas Highway Patrol stops, with an interactive dashboard and a [PDF report](docs/report.pdf).

**271,242 stops · 254 counties · 30,107 inspections · 37 counties account for half of all stops.**

![Traffic stops by county](docs/assets/overview.png)

## Rebuild the analysis

Requires Python 3.10 through 3.13 and the downloads listed in [data/README.md](data/README.md). Put those files in `data/`, then run:

On Linux, 
```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python pipeline/run_all.py
```

On Windows,
```sh
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.ext pipeline/run_all.py
```



The five stages prepare county references, build the DuckDB database, calculate county measures, draw figures and generate tables. Results go to `outputs/`, `docs/data/` and `report/`.

### Slide Show
[Slide Show (GD)](https://docs.google.com/presentation/d/16ZLiXa1FnvP99rJ0e9wGIXU3CgaOxKy3iKByXu5fjOY/edit?usp=sharing)

[Slide Show (PDF)](https://github.com/allanpaiz/txdps/blob/main/assesment_slide_show.pdf)

## Note

This is an independent analysis of public data. Not an official Texas DPS Report.
