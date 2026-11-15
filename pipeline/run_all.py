import argparse
import runpy
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as C

STEPS = ["01_reference_data.py", "02_build_database.py", "03_analysis.py", "04_figures.py", "05_report_tables.py"]
GENERATED = [(C.OUTPUTS, "*"), (C.SITE_DATA, "*"), (C.REPORT_FIGURES, "*"), (C.REPORT_GENERATED, "*.tex")]


def remove_generated(file):
    for attempt in range(10):
        try:
            file.unlink()
            return
        except PermissionError as error:
            if getattr(error, "winerror", None) not in (32, 33) or attempt == 9:
                raise
            time.sleep(0.75)


def build_report():
    report = C.ROOT / "report"
    build = C.BUILD / "report"
    build.mkdir(parents=True, exist_ok=True)
    for file in build.glob("*.tex"):
        file.unlink()
    for file in [*report.glob("*.tex"), report / "references.bib"]:
        shutil.copyfile(file, build / file.name)
    for name in ["figures", "generated"]:
        target = build / name
        target.mkdir(exist_ok=True)
        for file in target.iterdir():
            if file.is_file():
                file.unlink()
        shutil.copytree(report / name, target, dirs_exist_ok=True)
    for suffix in ["aux", "bbl", "blg", "toc", "out"]:
        (build / f"report.{suffix}").unlink(missing_ok=True)
    latex = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "report.tex"]
    for command in [latex, ["bibtex", "report"], latex, latex]:
        result = subprocess.run(command, cwd=build, capture_output=True, text=True, errors="replace")
        if result.returncode:
            raise RuntimeError(result.stdout[-6000:] + result.stderr[-2000:])
    log = (build / "report.log").read_text(encoding="utf-8", errors="replace")
    if "undefined" in log or "Rerun to get cross-references right" in log:
        raise RuntimeError("Unresolved citations or cross-references; see build/report/report.log")
    for target in [report / "report.pdf", C.ROOT / "docs" / "report.pdf"]:
        shutil.copyfile(build / "report.pdf", target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the analysis and dashboard; --report also compiles the PDF")
    parser.add_argument("--report", action="store_true", help="Build the report and copy it to docs/report.pdf")
    args = parser.parse_args()
    if args.report and not (C.ROOT / "report" / "report.tex").is_file():
        parser.error("PDF compilation requires report/report.tex and references.bib; the public package includes the compiled PDF only")
    required = [C.ROADWAY_INVENTORY, C.COUNTY_BOUNDARIES, C.POPULATION,
                *(C.DATA / f"{month}.csv" for month in C.ALL_MONTHS)]
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        parser.error("Download the inputs listed in data/README.md: " + ", ".join(missing))
    t0 = time.time()
    C.DB_PATH.unlink(missing_ok=True)
    for folder, pattern in GENERATED:
        folder.resolve().relative_to(C.ROOT.resolve())
        for f in folder.glob(pattern):
            if f.is_file():
                remove_generated(f)
    for step in STEPS:
        print(f"\n== {step}")
        t = time.time()
        runpy.run_path(str(HERE / step), run_name="__main__")
        print(f"   done in {time.time() - t:.1f}s")
    if args.report:
        build_report()
    print(f"\nPipeline complete in {time.time() - t0:.1f}s")
